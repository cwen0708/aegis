"""
LINE 頻道適配器

使用 line-bot-sdk v3 (Webhook 模式)
需要在 LINE Developers Console 設定 Webhook URL

支援兩種模式：
- active: 正常互動（收發訊息）
- passive: 只收集資料，不回應（存入 RawMessage 表）
"""
from linebot.v3.webhook import WebhookParser
from linebot.v3.webhooks import (
    MessageEvent,
    FollowEvent,
    UnfollowEvent,
    JoinEvent,
    LeaveEvent,
    PostbackEvent,
    TextMessageContent,
    ImageMessageContent,
    VideoMessageContent,
    AudioMessageContent,
    StickerMessageContent,
    FileMessageContent,
)
from linebot.v3.messaging import (
    Configuration,
    AsyncApiClient,
    AsyncMessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
)
from linebot.v3.exceptions import InvalidSignatureError
from ..base import ChannelBase
from ..registry import register_channel
from ..bus import message_bus
from ..types import (
    InboundMessage,
    OutboundMessage,
    ChannelStatus,
    MessageType,
)
from datetime import datetime, timezone, timedelta
from typing import AsyncIterator
import asyncio
import json
import logging

logger = logging.getLogger(__name__)

# Profile 快取過期天數
PROFILE_CACHE_DAYS = 7


def _extract_source(source) -> tuple[str, str, str]:
    """從 LINE event.source 取得 source_type, source_id, user_id"""
    source_type = source.type  # "user" | "group" | "room"
    user_id = getattr(source, "user_id", "") or ""

    if source_type == "group":
        source_id = source.group_id
    elif source_type == "room":
        source_id = source.room_id
    else:
        source_id = user_id

    return source_type, source_id, user_id


def _get_content_type(message) -> str:
    """從 LINE message object 取得 content_type 字串"""
    type_map = {
        TextMessageContent: "text",
        ImageMessageContent: "image",
        VideoMessageContent: "video",
        AudioMessageContent: "audio",
        StickerMessageContent: "sticker",
        FileMessageContent: "file",
    }
    for cls, name in type_map.items():
        if isinstance(message, cls):
            return name
    return "unknown"


def _get_event_type(event) -> str:
    """從 LINE event object 取得 event_type 字串"""
    type_map = {
        MessageEvent: "message",
        FollowEvent: "follow",
        UnfollowEvent: "unfollow",
        JoinEvent: "join",
        LeaveEvent: "leave",
        PostbackEvent: "postback",
    }
    for cls, name in type_map.items():
        if isinstance(event, cls):
            return name
    return "unknown"


@register_channel("line")
class LineChannel(ChannelBase):
    """
    LINE 頻道適配器

    使用 Webhook 模式接收訊息（需要 HTTPS 公網端點）
    mode="active": 正常互動（預設）
    mode="passive": 只收集資料到 RawMessage 表
    """

    PLATFORM = "line"

    def __init__(self, channel_secret: str, access_token: str, mode: str = "active"):
        """
        Args:
            channel_secret: LINE Channel Secret
            access_token: LINE Channel Access Token
            mode: "active"（互動）或 "passive"（只收集）
        """
        self.channel_secret = channel_secret
        self.parser = WebhookParser(channel_secret)
        self.config = Configuration(access_token=access_token)
        self.mode = mode
        self._api_client: AsyncApiClient | None = None
        self._api: AsyncMessagingApi | None = None
        self._running = False

    async def start(self):
        """初始化 LINE API Client"""
        self._running = True
        self._api_client = AsyncApiClient(self.config)
        self._api = AsyncMessagingApi(self._api_client)
        logger.info(f"[LINE] Channel ready (webhook, mode={self.mode})")

    async def stop(self):
        """關閉 API Client"""
        self._running = False
        if self._api_client:
            await self._api_client.close()
            self._api_client = None
            self._api = None
        logger.info("[LINE] Channel stopped")

    # ------------------------------------------
    # Passive mode: 原始訊息收集
    # ------------------------------------------

    async def _store_raw_message(self, event, event_type: str):
        """將事件存入 RawMessage 表"""
        from app.database import engine
        from app.models.core import RawMessage
        from sqlmodel import Session

        source_type, source_id, user_id = _extract_source(event.source)

        # 取得內容
        content = ""
        content_type = ""
        if event_type == "message" and hasattr(event, "message"):
            content_type = _get_content_type(event.message)
            if content_type == "text":
                content = event.message.text
            elif content_type == "sticker":
                content = f"sticker:{event.message.sticker_id}"
            elif content_type in ("image", "video", "audio", "file"):
                # 存 messageId，用於後續下載
                msg_id = getattr(event.message, "id", "")
                file_name = getattr(event.message, "file_name", "") if content_type == "file" else ""
                content = f"msgId:{msg_id}" + (f"|{file_name}" if file_name else "")
        elif event_type == "postback" and hasattr(event, "postback"):
            content_type = "postback"
            content = event.postback.data

        # 序列化 payload
        try:
            payload = json.dumps(event.to_dict(), ensure_ascii=False, default=str)
        except Exception:
            payload = "{}"

        raw = RawMessage(
            platform=self.PLATFORM,
            source_type=source_type,
            source_id=source_id,
            user_id=user_id,
            event_type=event_type,
            content_type=content_type or event_type,
            content=content,
            payload=payload,
        )

        with Session(engine) as session:
            session.add(raw)
            session.commit()

        # 非同步更新 profile/group 快取（不阻塞 webhook 回應）
        asyncio.create_task(self._ensure_caches(source_type, source_id, user_id))

    async def _ensure_caches(self, source_type: str, source_id: str, user_id: str):
        """確保 user/group 快取存在且未過期"""
        try:
            if user_id:
                await self._cache_user_profile(user_id, source_type, source_id)
            if source_type in ("group", "room"):
                await self._cache_group_info(source_type, source_id)
        except Exception as e:
            logger.warning(f"[LINE] Cache update failed: {e}")

    async def _cache_user_profile(self, user_id: str, source_type: str, source_id: str):
        """快取用戶 profile（過期則刷新）"""
        from app.database import engine
        from app.models.core import RawMessageUser
        from sqlmodel import Session, select

        with Session(engine) as session:
            stmt = select(RawMessageUser).where(
                RawMessageUser.platform == self.PLATFORM,
                RawMessageUser.user_id == user_id,
            )
            cached = session.exec(stmt).first()

            # 未過期就跳過
            if cached:
                age = datetime.now(timezone.utc) - cached.updated_at
                if age < timedelta(days=PROFILE_CACHE_DAYS):
                    return

        # 呼叫 LINE API 取 profile
        if not self._api:
            return

        try:
            if source_type == "group":
                profile = await self._api.get_group_member_profile(source_id, user_id)
            elif source_type == "room":
                profile = await self._api.get_room_member_profile(source_id, user_id)
            else:
                profile = await self._api.get_profile(user_id)
        except Exception as e:
            logger.debug(f"[LINE] Profile API failed for {user_id}: {e}")
            return

        with Session(engine) as session:
            stmt = select(RawMessageUser).where(
                RawMessageUser.platform == self.PLATFORM,
                RawMessageUser.user_id == user_id,
            )
            existing = session.exec(stmt).first()

            now = datetime.now(timezone.utc)
            if existing:
                existing.display_name = profile.display_name or ""
                existing.picture_url = getattr(profile, "picture_url", "") or ""
                existing.status_message = getattr(profile, "status_message", "") or ""
                existing.updated_at = now
            else:
                session.add(RawMessageUser(
                    platform=self.PLATFORM,
                    user_id=user_id,
                    display_name=profile.display_name or "",
                    picture_url=getattr(profile, "picture_url", "") or "",
                    status_message=getattr(profile, "status_message", "") or "",
                    updated_at=now,
                ))
            session.commit()
            logger.info(f"[LINE] Cached profile: {profile.display_name} ({user_id})")

    async def _cache_group_info(self, source_type: str, source_id: str):
        """快取群組資訊（過期則刷新）"""
        from app.database import engine
        from app.models.core import RawMessageGroup
        from sqlmodel import Session, select

        with Session(engine) as session:
            stmt = select(RawMessageGroup).where(
                RawMessageGroup.platform == self.PLATFORM,
                RawMessageGroup.group_id == source_id,
            )
            cached = session.exec(stmt).first()

            if cached:
                age = datetime.now(timezone.utc) - cached.updated_at
                if age < timedelta(days=PROFILE_CACHE_DAYS):
                    return

        if not self._api or source_type != "group":
            return

        try:
            summary = await self._api.get_group_summary(source_id)
        except Exception as e:
            logger.debug(f"[LINE] Group summary API failed for {source_id}: {e}")
            return

        # 取成員數
        member_count = 0
        try:
            count_resp = await self._api.get_group_member_count(source_id)
            member_count = count_resp if isinstance(count_resp, int) else 0
        except Exception:
            pass

        with Session(engine) as session:
            stmt = select(RawMessageGroup).where(
                RawMessageGroup.platform == self.PLATFORM,
                RawMessageGroup.group_id == source_id,
            )
            existing = session.exec(stmt).first()

            now = datetime.now(timezone.utc)
            if existing:
                existing.group_name = summary.group_name or ""
                existing.picture_url = getattr(summary, "picture_url", "") or ""
                existing.member_count = member_count
                existing.updated_at = now
            else:
                session.add(RawMessageGroup(
                    platform=self.PLATFORM,
                    group_id=source_id,
                    group_name=summary.group_name or "",
                    picture_url=getattr(summary, "picture_url", "") or "",
                    member_count=member_count,
                    updated_at=now,
                ))
            session.commit()
            logger.info(f"[LINE] Cached group: {summary.group_name} ({source_id})")

    # ------------------------------------------
    # Webhook 處理
    # ------------------------------------------

    async def handle_webhook(self, body: str, signature: str) -> int:
        """
        處理 LINE Webhook（由 FastAPI route 調用）

        active mode: 轉為 InboundMessage 發到 message_bus
        passive mode: 存入 RawMessage 表，不回應
        """
        events = self.parser.parse(body, signature)
        count = 0

        for event in events:
            event_type = _get_event_type(event)

            if self.mode == "passive":
                # Passive: 存原始資料，不進 bus
                await self._store_raw_message(event, event_type)
                count += 1
                continue

            # Active: 現有行為（只處理文字訊息）
            if isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
                source_type, source_id, user_id = _extract_source(event.source)
                msg = InboundMessage(
                    id=event.message.id,
                    platform=self.PLATFORM,
                    user_id=user_id,
                    chat_id=source_id,
                    text=event.message.text,
                    timestamp=datetime.now(timezone.utc),
                    message_type=(
                        MessageType.COMMAND
                        if event.message.text.startswith("/")
                        else MessageType.TEXT
                    ),
                    raw_data={"reply_token": event.reply_token},
                )
                await message_bus.publish_inbound(msg)
                count += 1

        return count

    # ------------------------------------------
    # 發送（active mode 專用）
    # ------------------------------------------

    async def send(self, msg: OutboundMessage) -> str | bool:
        """
        發送訊息（Push API，免費版每月 200 則限制）

        注意：LINE 不支援編輯訊息，edit_message_id 會被忽略
        """
        if not self._api:
            logger.warning("[LINE] API not ready")
            return False

        # LINE 不支援編輯訊息，直接跳過 thinking 訊息
        if msg.edit_message_id:
            # 編輯 = 發送新訊息（LINE 限制）
            pass

        try:
            result = await self._api.push_message(
                PushMessageRequest(
                    to=msg.chat_id,
                    messages=[TextMessage(text=msg.text)]
                )
            )
            # LINE push API 不返回 message_id，用時間戳代替
            import time
            return str(int(time.time() * 1000))
        except Exception as e:
            logger.error(f"[LINE] Send failed: {e}")
            return False

    async def reply(self, reply_token: str, text: str) -> bool:
        """
        使用 Reply Token 回覆（不計入訊息額度）
        """
        if not self._api:
            return False

        try:
            await self._api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[TextMessage(text=text)]
                )
            )
            return True
        except Exception as e:
            logger.error(f"[LINE] Reply failed: {e}")
            return False

    async def listen(self) -> AsyncIterator[InboundMessage]:
        """Webhook 模式不需要此方法"""
        while self._running:
            await asyncio.sleep(1)
            if False:
                yield  # type: ignore

    async def health_check(self) -> ChannelStatus:
        """健康檢查"""
        if not self._api:
            return ChannelStatus(
                platform=self.PLATFORM,
                is_connected=False,
                error="API not initialized",
            )

        try:
            return ChannelStatus(
                platform=self.PLATFORM,
                is_connected=True,
                last_heartbeat=datetime.now(timezone.utc),
                stats={"mode": self.mode},
            )
        except Exception as e:
            return ChannelStatus(
                platform=self.PLATFORM,
                is_connected=False,
                error=str(e),
            )
