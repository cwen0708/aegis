"""
Email 頻道適配器

IMAP polling 收信 + SMTP 回信，全 stdlib（imaplib, smtplib, email）
參考: Nanobot email.py 設計
"""
import imaplib
import smtplib
import ssl
import json
import re
import asyncio
import logging
from email import policy
from email.parser import BytesParser
from email.message import EmailMessage as StdEmailMessage
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from ..base import ChannelBase
from ..registry import register_channel
from ..bus import message_bus
from ..types import (
    InboundMessage,
    OutboundMessage,
    ChannelStatus,
    MessageType,
)

logger = logging.getLogger(__name__)


def _decode_header_value(raw: str) -> str:
    """解碼 MIME encoded header（如 =?UTF-8?B?...?=）"""
    if not raw:
        return ""
    parts = decode_header(raw)
    decoded = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(data)
    return "".join(decoded)


def _html_to_text(html: str) -> str:
    """簡易 HTML → 純文字"""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    # unescape common entities
    for ent, ch in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                    ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")]:
        text = text.replace(ent, ch)
    return text.strip()


def _extract_body(msg, max_chars: int = 5000) -> str:
    """從 email.message 萃取純文字 body"""
    plain_parts = []
    html_parts = []

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get_content_disposition() or "")
            if "attachment" in disp:
                continue
            try:
                payload = part.get_content()
            except Exception:
                continue
            if ct == "text/plain" and isinstance(payload, str):
                plain_parts.append(payload)
            elif ct == "text/html" and isinstance(payload, str):
                html_parts.append(payload)
    else:
        ct = msg.get_content_type()
        try:
            payload = msg.get_content()
        except Exception:
            payload = ""
        if ct == "text/plain" and isinstance(payload, str):
            plain_parts.append(payload)
        elif ct == "text/html" and isinstance(payload, str):
            html_parts.append(payload)

    body = "\n".join(plain_parts) if plain_parts else _html_to_text("\n".join(html_parts))
    return body[:max_chars]


def _extract_attachments(msg) -> list[str]:
    """萃取附件檔名"""
    names = []
    if not msg.is_multipart():
        return names
    for part in msg.walk():
        disp = str(part.get_content_disposition() or "")
        if "attachment" in disp:
            fn = part.get_filename()
            if fn:
                names.append(_decode_header_value(fn))
    return names


@register_channel("email")
class EmailChannel(ChannelBase):
    """
    Email 頻道適配器

    IMAP polling 收信 + SMTP 回信
    """

    PLATFORM = "email"

    def __init__(
        self,
        imap_host: str,
        imap_port: int = 993,
        imap_user: str = "",
        imap_pass: str = "",
        imap_use_ssl: bool = True,
        smtp_host: str = "",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_pass: str = "",
        smtp_use_tls: bool = True,
        smtp_use_ssl: bool = False,
        poll_interval: int = 60,
        mark_seen: bool = True,
        max_body_chars: int = 5000,
        auto_reply_enabled: bool = False,
        sender_allowlist: list[str] | None = None,
        folders: list[str] | None = None,
        ai_classify_enabled: bool = True,
        **kwargs,
    ):
        self.imap_host = imap_host
        self.imap_port = imap_port
        self.imap_user = imap_user
        self.imap_pass = imap_pass
        self.imap_use_ssl = imap_use_ssl
        self.smtp_host = smtp_host or imap_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user or imap_user
        self.smtp_pass = smtp_pass or imap_pass
        self.smtp_use_tls = smtp_use_tls
        self.smtp_use_ssl = smtp_use_ssl
        self.poll_interval = max(10, poll_interval)
        self.mark_seen = mark_seen
        self.max_body_chars = max_body_chars
        self.auto_reply_enabled = auto_reply_enabled
        self.sender_allowlist = sender_allowlist or []
        self.folders = folders or ["INBOX"]
        self.ai_classify_enabled = ai_classify_enabled

        self._running = False
        self._poll_task: Optional[asyncio.Task] = None

    # ===== Lifecycle =====

    async def start(self):
        """啟動 IMAP polling"""
        if not self.imap_host or not self.imap_user:
            logger.warning("[Email] Missing IMAP host or user, channel disabled")
            return

        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(f"[Email] Channel started (polling every {self.poll_interval}s)")

    async def stop(self):
        """停止 polling"""
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("[Email] Channel stopped")

    # ===== IMAP Polling =====

    async def _poll_loop(self):
        """主 polling 循環"""
        while self._running:
            try:
                new_emails = await asyncio.to_thread(self._fetch_emails)
                for email_data in new_emails:
                    await self._process_email(email_data)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Email] Poll error: {e}")

            await asyncio.sleep(self.poll_interval)

    def _fetch_emails(self) -> list[dict]:
        """同步 IMAP 收信（在 thread 中執行）"""
        results = []

        for folder in self.folders:
            try:
                results.extend(self._fetch_from_folder(folder))
            except Exception as e:
                logger.error(f"[Email] Fetch error in {folder}: {e}")

        return results

    def _fetch_from_folder(self, folder: str) -> list[dict]:
        """從單一資料夾取新信"""
        results = []
        client = None

        try:
            # 連接
            if self.imap_use_ssl:
                client = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
            else:
                client = imaplib.IMAP4(self.imap_host, self.imap_port)

            client.login(self.imap_user, self.imap_pass)
            client.select(folder, readonly=not self.mark_seen)

            # 搜尋未讀
            status, data = client.search(None, "UNSEEN")
            if status != "OK" or not data[0]:
                return results

            msg_nums = data[0].split()
            logger.debug(f"[Email] Found {len(msg_nums)} unseen in {folder}")

            for num in msg_nums:
                try:
                    # 取 UID
                    uid_resp = client.fetch(num, "(UID)")
                    if uid_resp[0] != "OK":
                        continue
                    uid_data = uid_resp[1][0]
                    if isinstance(uid_data, bytes):
                        uid_match = re.search(rb"UID (\d+)", uid_data)
                        uid = uid_match.group(1).decode() if uid_match else num.decode()
                    else:
                        uid = num.decode()

                    # 去重 key: folder + uid
                    dedup_uid = f"{folder}:{uid}"

                    # DB 去重檢查
                    from sqlmodel import Session, select
                    from app.database import engine
                    from app.models.core import EmailMessage

                    with Session(engine) as session:
                        exists = session.exec(
                            select(EmailMessage).where(EmailMessage.uid == dedup_uid)
                        ).first()
                        if exists:
                            continue

                    # 取完整信件 (PEEK 不自動標已讀)
                    fetch_cmd = "(BODY.PEEK[])" if not self.mark_seen else "(RFC822)"
                    resp = client.fetch(num, fetch_cmd)
                    if resp[0] != "OK":
                        continue

                    raw_bytes = resp[1][0][1]
                    msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)

                    # 解析 header
                    from_str = msg.get("From", "")
                    from_name, from_addr = parseaddr(from_str)
                    from_name = _decode_header_value(from_name)
                    from_addr = from_addr.lower()

                    # 寄件人白名單檢查
                    if self.sender_allowlist and not self._is_allowed(from_addr):
                        logger.debug(f"[Email] Sender {from_addr} not in allowlist, skipping")
                        continue

                    to_str = msg.get("To", "")
                    _, to_addr = parseaddr(to_str)
                    subject = _decode_header_value(msg.get("Subject", ""))
                    message_id = msg.get("Message-ID", "")
                    in_reply_to = msg.get("In-Reply-To", "")

                    # 解析日期
                    date_val = None
                    date_str = msg.get("Date")
                    if date_str:
                        try:
                            date_val = parsedate_to_datetime(date_str)
                        except Exception:
                            pass

                    # 萃取 body
                    body = _extract_body(msg, self.max_body_chars)
                    attachments = _extract_attachments(msg)

                    # 存入 DB
                    with Session(engine) as session:
                        email_record = EmailMessage(
                            uid=dedup_uid,
                            message_id=message_id,
                            in_reply_to=in_reply_to,
                            from_address=from_addr,
                            from_name=from_name,
                            to_address=to_addr,
                            subject=subject,
                            date=date_val,
                            body_text=body,
                            attachment_names=json.dumps(attachments, ensure_ascii=False),
                        )
                        session.add(email_record)
                        session.commit()
                        session.refresh(email_record)
                        db_id = email_record.id

                    # 標已讀
                    if self.mark_seen:
                        client.store(num, "+FLAGS", "\\Seen")

                    results.append({
                        "db_id": db_id,
                        "uid": dedup_uid,
                        "from_addr": from_addr,
                        "from_name": from_name,
                        "subject": subject,
                        "body": body,
                        "message_id": message_id,
                    })

                except Exception as e:
                    logger.error(f"[Email] Parse error for msg {num}: {e}")
                    continue

        finally:
            if client:
                try:
                    client.logout()
                except Exception:
                    pass

        return results

    def _is_allowed(self, addr: str) -> bool:
        """寄件人白名單檢查（支援完整 email 或 @domain）"""
        for pattern in self.sender_allowlist:
            pattern = pattern.lower().strip()
            if pattern.startswith("@"):
                if addr.endswith(pattern):
                    return True
            elif addr == pattern:
                return True
        return False

    async def _process_email(self, email_data: dict):
        """將新信發佈到 MessageBus"""
        text = f"[{email_data['subject']}]\n\n{email_data['body']}"

        msg = InboundMessage(
            id=email_data["uid"],
            platform=self.PLATFORM,
            user_id=email_data["from_addr"],
            chat_id=email_data["from_addr"],
            text=text,
            timestamp=datetime.now(timezone.utc),
            message_type=MessageType.TEXT,
            user_name=email_data["from_name"] or email_data["from_addr"],
            raw_data={
                "email_message_db_id": email_data["db_id"],
                "message_id": email_data["message_id"],
                "ai_classify_enabled": self.ai_classify_enabled,
            },
        )

        await message_bus.publish_inbound(msg)
        logger.info(f"[Email] New mail from {email_data['from_addr']}: {email_data['subject'][:60]}")

    # ===== SMTP Send =====

    async def send(self, msg: OutboundMessage) -> str | bool:
        """SMTP 回信"""
        if not self.auto_reply_enabled:
            logger.debug("[Email] Auto-reply disabled, skipping send")
            return False

        if not self.smtp_host:
            logger.warning("[Email] SMTP not configured")
            return False

        try:
            return await asyncio.to_thread(self._smtp_send, msg)
        except Exception as e:
            logger.error(f"[Email] SMTP send failed: {e}")
            return False

    def _smtp_send(self, msg: OutboundMessage) -> str | bool:
        """同步 SMTP 發送（在 thread 中執行）"""
        email_msg = StdEmailMessage()
        email_msg["From"] = self.smtp_user
        email_msg["To"] = msg.chat_id
        email_msg["Subject"] = f"Re: {msg.task_id}" if msg.task_id else "Aegis Reply"
        email_msg.set_content(msg.text)

        # 串連 header（從 raw_data 取 message_id）
        if hasattr(msg, "raw_data") and msg.raw_data:
            ref = msg.raw_data.get("message_id", "")
            if ref:
                email_msg["In-Reply-To"] = ref
                email_msg["References"] = ref

        timeout = 30

        if self.smtp_use_ssl:
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=timeout) as smtp:
                smtp.login(self.smtp_user, self.smtp_pass)
                smtp.send_message(email_msg)
        else:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=timeout) as smtp:
                if self.smtp_use_tls:
                    smtp.starttls(context=ssl.create_default_context())
                smtp.login(self.smtp_user, self.smtp_pass)
                smtp.send_message(email_msg)

        return email_msg["Message-ID"] or True

    # ===== Interface Methods =====

    async def listen(self) -> AsyncIterator[InboundMessage]:
        """Polling 模式不需要此方法"""
        while self._running:
            await asyncio.sleep(1)
            if False:
                yield  # type: ignore

    async def health_check(self) -> ChannelStatus:
        """健康檢查：嘗試 IMAP 登入"""
        try:
            def _check():
                if self.imap_use_ssl:
                    c = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
                else:
                    c = imaplib.IMAP4(self.imap_host, self.imap_port)
                c.login(self.imap_user, self.imap_pass)
                c.logout()

            await asyncio.to_thread(_check)
            return ChannelStatus(
                platform=self.PLATFORM,
                is_connected=True,
                last_heartbeat=datetime.now(timezone.utc),
                stats={"imap_host": self.imap_host, "user": self.imap_user},
            )
        except Exception as e:
            return ChannelStatus(
                platform=self.PLATFORM,
                is_connected=False,
                error=str(e),
            )
