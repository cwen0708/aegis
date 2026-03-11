"""
訊息路由器 — 處理 inbound 訊息，產生 outbound 回應
"""
import asyncio
from .bus import message_bus
from .types import InboundMessage, OutboundMessage, MessageType, ParseMode
from .commands.parser import parse_command
from .commands.handlers import handle_command
from .bot_user import get_or_create_bot_user
from .chat_handler import handle_chat
import logging

logger = logging.getLogger(__name__)

# 思考中提示訊息
THINKING_MESSAGE = "🤔 思考中..."


class MessageRouter:
    """
    訊息路由器

    職責：
    - 從 Bus 消費 InboundMessage
    - 解析命令
    - 執行業務邏輯
    - 產生 OutboundMessage 發回 Bus
    """

    def __init__(self):
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self):
        """啟動路由循環"""
        self._running = True
        self._task = asyncio.create_task(self._route_loop())
        logger.info("[Router] MessageRouter started")

    async def stop(self):
        """停止路由"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[Router] MessageRouter stopped")

    async def _route_loop(self):
        """主路由循環"""
        while self._running:
            try:
                msg = await message_bus.consume_inbound(timeout=1.0)
                if msg:
                    await self._handle_message(msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Router] Error: {e}", exc_info=True)

    async def _handle_message(self, msg: InboundMessage):
        """處理單一訊息"""
        logger.debug(f"[Router] Processing: [{msg.platform}] {msg.text[:50]}")

        # Email 走專用處理流程（AI 分類 + 摘要，不走一般對話）
        if msg.platform == "email":
            await self._handle_email(msg)
            return

        # P2: 取得或建立 BotUser
        bot_user = get_or_create_bot_user(msg.platform, msg.user_id, msg.user_name)

        # 解析命令
        cmd = parse_command(msg.text)

        response_text: str | None = None

        if cmd:
            # 執行命令（帶入 bot_user 做權限檢查）
            response_text = await handle_command(cmd, msg, bot_user)
            # 命令回應走 queue
            if response_text:
                await message_bus.publish_outbound(OutboundMessage(
                    chat_id=msg.chat_id,
                    platform=msg.platform,
                    text=response_text,
                    reply_to_id=msg.id,
                ))
        else:
            # P2: 非命令訊息 → AI 對話（先回再更新）
            await self._handle_ai_chat(msg, bot_user)

    async def _handle_ai_chat(self, msg: InboundMessage, bot_user):
        """
        處理 AI 對話（先發「思考中...」再更新）
        """
        from .manager import channel_manager

        channel = channel_manager.get_channel(msg.platform)
        if not channel:
            logger.warning(f"[Router] Channel not found: {msg.platform}")
            return

        # 1. 先發送「思考中...」
        placeholder_msg = OutboundMessage(
            chat_id=msg.chat_id,
            platform=msg.platform,
            text=THINKING_MESSAGE,
            parse_mode=ParseMode.PLAIN,
        )
        message_id = await channel.send(placeholder_msg)

        if not message_id:
            logger.warning("[Router] Failed to send placeholder")
            return

        # 2. 執行 AI 對話
        response_text = await handle_chat(msg, bot_user)

        if not response_text:
            response_text = "（無回應）"

        # 3. 編輯訊息為實際回應
        edit_msg = OutboundMessage(
            chat_id=msg.chat_id,
            platform=msg.platform,
            text=response_text,
            edit_message_id=str(message_id),
        )
        await channel.send(edit_msg)

    async def _handle_email(self, msg: InboundMessage):
        """
        Email 專用處理：收信已存入 DB，AI 分類由 CronJob 排程處理。
        此處只做日誌記錄，不走一般 AI 對話流程。
        """
        email_db_id = msg.raw_data.get("email_message_db_id")
        logger.info(f"[Router] Email received and stored (db_id={email_db_id}), "
                     f"AI classification will run via CronJob")


# 全域 Router 實例
message_router = MessageRouter()
