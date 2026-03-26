"""
Telegram 頻道適配器

使用 python-telegram-bot v21+ (polling 模式)
"""
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes,
)
from ..base import ChannelBase
from ..registry import register_channel
from ..bus import message_bus
from ..types import (
    InboundMessage,
    OutboundMessage,
    Attachment,
    ChannelStatus,
    MessageType,
    ParseMode,
)
from datetime import datetime, timezone
from typing import AsyncIterator
from pathlib import Path
import asyncio
import logging
import os

logger = logging.getLogger(__name__)


@register_channel("telegram")
class TelegramChannel(ChannelBase):
    """
    Telegram 頻道適配器

    使用 Polling 模式接收訊息
    """

    PLATFORM = "telegram"

    def __init__(self, token: str):
        """
        Args:
            token: Telegram Bot Token (從 @BotFather 取得)
        """
        self.token = token
        self._app: Application | None = None
        self._running = False

    async def start(self):
        """啟動 Telegram Bot"""
        self._running = True

        # 建立 Application
        self._app = Application.builder().token(self.token).build()

        # 註冊 handler - 處理文字、命令和媒體訊息
        self._app.add_handler(MessageHandler(
            filters.TEXT | filters.COMMAND | filters.PHOTO
            | filters.VOICE | filters.AUDIO | filters.Document.ALL,
            self._on_message
        ))

        # 初始化並啟動
        await self._app.initialize()
        await self._app.start()

        # 啟動 polling（背景執行）
        await self._app.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )

        logger.info(f"[Telegram] Bot started (polling)")

    async def stop(self):
        """停止 Telegram Bot"""
        self._running = False

        if self._app:
            if self._app.updater and self._app.updater.running:
                await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._app = None

        logger.info("[Telegram] Bot stopped")

    # 媒體暫存目錄
    MEDIA_DIR = Path("/tmp/aegis-media")

    async def _on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """
        收到訊息回調

        將 Telegram 訊息翻譯為 InboundMessage（含媒體），發送到 Bus
        """
        if not update.message:
            return

        msg_id = str(update.message.message_id)
        text = update.message.text or update.message.caption or ""
        message_type = MessageType.TEXT
        media_type = None
        media_path = None
        media_mime = None

        # 處理媒體
        try:
            if update.message.photo:
                # 取最大尺寸的圖片
                photo = update.message.photo[-1]
                media_type = "photo"
                media_mime = "image/jpeg"
                media_path = await self._download_file(
                    await photo.get_file(), f"{msg_id}.jpg"
                )
                message_type = MessageType.PHOTO

            elif update.message.voice:
                media_type = "voice"
                media_mime = update.message.voice.mime_type or "audio/ogg"
                media_path = await self._download_file(
                    await update.message.voice.get_file(), f"{msg_id}.ogg"
                )
                message_type = MessageType.VOICE

            elif update.message.audio:
                media_type = "audio"
                media_mime = update.message.audio.mime_type or "audio/mpeg"
                ext = update.message.audio.file_name or f"{msg_id}.mp3"
                media_path = await self._download_file(
                    await update.message.audio.get_file(), ext
                )
                message_type = MessageType.AUDIO

            elif update.message.document:
                doc = update.message.document
                media_type = "document"
                media_mime = doc.mime_type or "application/octet-stream"
                fname = doc.file_name or f"{msg_id}_file"
                media_path = await self._download_file(
                    await doc.get_file(), f"{msg_id}_{fname}"
                )
                message_type = MessageType.DOCUMENT

            elif not text:
                # 不是文字也不是支援的媒體，跳過
                return

        except Exception as e:
            logger.warning(f"[Telegram] Failed to download media: {e}")
            # 下載失敗，仍處理文字部分
            if not text:
                return

        if text and text.startswith("/"):
            message_type = MessageType.COMMAND

        msg = InboundMessage(
            id=msg_id,
            platform=self.PLATFORM,
            user_id=str(update.effective_user.id),
            chat_id=str(update.effective_chat.id),
            text=text,
            timestamp=datetime.now(timezone.utc),
            message_type=message_type,
            user_name=update.effective_user.full_name,
            raw_data={"update_id": update.update_id},
            media_type=media_type,
            media_path=media_path,
            media_mime=media_mime,
            caption=update.message.caption,
        )

        await message_bus.publish_inbound(msg)

    async def _download_file(self, tg_file, filename: str) -> str:
        """下載 Telegram 檔案到暫存目錄"""
        self.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        path = self.MEDIA_DIR / filename
        await tg_file.download_to_drive(str(path))
        logger.info(f"[Telegram] Downloaded media: {path}")
        return str(path)

    async def send(self, msg: OutboundMessage) -> str | bool:
        """
        發送或編輯訊息到 Telegram

        Returns:
            成功時返回 message_id (str)，失敗返回 False
        """
        if not self._app or not self._app.bot:
            logger.warning("[Telegram] Bot not ready")
            return False

        try:
            # 轉換 parse_mode
            parse_mode = None
            if msg.parse_mode == ParseMode.MARKDOWN:
                parse_mode = "Markdown"
            elif msg.parse_mode == ParseMode.HTML:
                parse_mode = "HTML"

            # 編輯現有訊息
            if msg.edit_message_id:
                # 解析 actions 標記
                clean_text, parsed_buttons = self._parse_actions_markup(msg.text)

                if parsed_buttons:
                    # 有按鈕：先 edit 文字（去掉 actions 標記），再發新訊息帶按鈕
                    await self._app.bot.edit_message_text(
                        chat_id=int(msg.chat_id),
                        message_id=int(msg.edit_message_id),
                        text=clean_text,
                        parse_mode=parse_mode,
                    )
                    # 組裝 inline keyboard
                    keyboard = []
                    for row in parsed_buttons:
                        kb_row = []
                        for btn in row:
                            if btn.url:
                                kb_row.append(InlineKeyboardButton(text=btn.text, url=btn.url))
                            elif btn.callback_data:
                                kb_row.append(InlineKeyboardButton(text=btn.text, callback_data=btn.callback_data))
                        if kb_row:
                            keyboard.append(kb_row)
                    if keyboard:
                        # 發一則空白提示 + 按鈕
                        await self._app.bot.send_message(
                            chat_id=int(msg.chat_id),
                            text="👇 快速操作",
                            reply_markup=InlineKeyboardMarkup(keyboard),
                        )
                else:
                    await self._app.bot.edit_message_text(
                        chat_id=int(msg.chat_id),
                        message_id=int(msg.edit_message_id),
                        text=msg.text,
                        parse_mode=parse_mode,
                    )
                # 附件在 edit 後仍需發送（edit_message_text 不支援附件）
                for att in msg.attachments:
                    try:
                        await self._send_attachment(int(msg.chat_id), att)
                    except Exception as att_err:
                        logger.warning(f"[Telegram] Failed to send attachment: {att_err}")
                return msg.edit_message_id

            # 發送附件（如有）
            for att in msg.attachments:
                try:
                    await self._send_attachment(int(msg.chat_id), att)
                except Exception as att_err:
                    logger.warning(f"[Telegram] Failed to send attachment: {att_err}")

            # 發送新訊息（文字部分，可能為空如果只有附件）
            if not msg.text and msg.attachments:
                return "attachment_sent"

            # 解析 <!--actions ... --> 標記，轉成按鈕
            msg.text, parsed_buttons = self._parse_actions_markup(msg.text)

            # 組裝 inline keyboard（API 傳入的 buttons 優先，否則用解析出的）
            reply_markup = None
            all_buttons = msg.buttons or parsed_buttons
            if all_buttons:
                keyboard = []
                for row in all_buttons:
                    kb_row = []
                    for btn in row:
                        if btn.url:
                            kb_row.append(InlineKeyboardButton(text=btn.text, url=btn.url))
                        elif btn.callback_data:
                            kb_row.append(InlineKeyboardButton(text=btn.text, callback_data=btn.callback_data))
                    if kb_row:
                        keyboard.append(kb_row)
                if keyboard:
                    reply_markup = InlineKeyboardMarkup(keyboard)

            result = await self._app.bot.send_message(
                chat_id=int(msg.chat_id),
                text=msg.text,
                parse_mode=parse_mode,
                reply_to_message_id=(
                    int(msg.reply_to_id) if msg.reply_to_id else None
                ),
                reply_markup=reply_markup,
            )
            return str(result.message_id)

        except Exception as e:
            error_str = str(e)
            # Markdown 解析失敗時，改用純文字重試
            if "parse entities" in error_str.lower() or "can't find end" in error_str.lower():
                logger.warning(f"[Telegram] Markdown parse failed, retrying as plain text")
                try:
                    if msg.edit_message_id:
                        await self._app.bot.edit_message_text(
                            chat_id=int(msg.chat_id),
                            message_id=int(msg.edit_message_id),
                            text=msg.text,
                            parse_mode=None,
                        )
                        return msg.edit_message_id
                    result = await self._app.bot.send_message(
                        chat_id=int(msg.chat_id),
                        text=msg.text,
                        parse_mode=None,
                        reply_to_message_id=(
                            int(msg.reply_to_id) if msg.reply_to_id else None
                        ),
                    )
                    return str(result.message_id)
                except Exception as e2:
                    logger.error(f"[Telegram] Plain text retry also failed: {e2}")
                    return False
            logger.error(f"[Telegram] Send failed: {e}")
            return False

    async def listen(self) -> AsyncIterator[InboundMessage]:
        """
        監聽訊息（Polling 模式不需要此方法）

        訊息由 _on_message 回調處理
        """
        while self._running:
            await asyncio.sleep(1)
            # Polling 模式下，訊息透過 _on_message 處理
            # 此方法只是為了符合介面
            if False:
                yield  # type: ignore

    @staticmethod
    def _parse_actions_markup(text: str) -> tuple[str, list]:
        """
        解析 <!--actions ... --> 標記，回傳 (清理後文字, 按鈕列表)。
        格式：每行一個 [按鈕文字](url 或 callback:data)
        """
        from ..types import Button

        # 支援多種格式：<!--actions ... --> 或 ```\n<!--actions\n...\n-->\n```
        # 先清理可能包裹的 code block
        cleaned = re.sub(r'```\s*\n?(<!--\s*actions)', r'\1', text)
        cleaned = re.sub(r'(-->)\s*\n?```', r'\1', cleaned)

        pattern = r'<!--\s*actions\s*\n(.*?)\n\s*-->'
        match = re.search(pattern, cleaned, re.DOTALL)
        if not match:
            has_hint = '<!--' in text and 'actions' in text
            if has_hint:
                logger.warning(f"[Telegram] actions hint found but regex no match. text tail: {text[-200:]!r}")
            return text, []

        actions_block = match.group(1)
        clean_text = cleaned[:match.start()].rstrip()

        buttons = []
        btn_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
        for line in actions_block.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            btn_match = re.findall(btn_pattern, line)
            if btn_match:
                row = []
                for btn_text, btn_target in btn_match:
                    if btn_target.startswith('callback:'):
                        row.append(Button(text=btn_text, callback_data=btn_target[9:]))
                    else:
                        row.append(Button(text=btn_text, url=btn_target))
                if row:
                    buttons.append(row)

        logger.info(f"[Telegram] parsed {len(buttons)} action buttons")
        return clean_text, buttons

    async def _send_attachment(self, chat_id: int, att: Attachment):
        """發送附件到 Telegram"""
        if not os.path.exists(att.path):
            logger.warning(f"[Telegram] Attachment not found: {att.path}")
            return

        with open(att.path, "rb") as f:
            if att.type == "photo":
                await self._app.bot.send_photo(
                    chat_id=chat_id, photo=f, caption=att.caption or None,
                )
            elif att.type in ("document", "audio"):
                await self._app.bot.send_document(
                    chat_id=chat_id, document=f, caption=att.caption or None,
                )
            elif att.type == "voice":
                await self._app.bot.send_voice(
                    chat_id=chat_id, voice=f, caption=att.caption or None,
                )
        logger.info(f"[Telegram] Sent {att.type}: {att.path}")

    async def health_check(self) -> ChannelStatus:
        """健康檢查"""
        if not self._app or not self._app.bot:
            return ChannelStatus(
                platform=self.PLATFORM,
                is_connected=False,
                error="Bot not initialized",
            )

        try:
            me = await self._app.bot.get_me()
            return ChannelStatus(
                platform=self.PLATFORM,
                is_connected=True,
                last_heartbeat=datetime.now(timezone.utc),
                stats={
                    "bot_id": me.id,
                    "bot_username": me.username,
                    "bot_name": me.first_name,
                },
            )
        except Exception as e:
            return ChannelStatus(
                platform=self.PLATFORM,
                is_connected=False,
                error=str(e),
            )
