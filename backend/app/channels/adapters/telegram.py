"""
Telegram 頻道適配器

使用 python-telegram-bot v21+ (polling 模式)
"""
from telegram import Update
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
    ChannelStatus,
    MessageType,
    ParseMode,
)
from datetime import datetime, timezone
from typing import AsyncIterator
import asyncio
import logging

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

        # 註冊 handler - 處理所有文字訊息和命令
        self._app.add_handler(MessageHandler(
            filters.TEXT | filters.COMMAND,
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

    async def _on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """
        收到訊息回調

        將 Telegram 訊息翻譯為 InboundMessage，發送到 Bus
        """
        if not update.message or not update.message.text:
            return

        # 翻譯為統一格式
        msg = InboundMessage(
            id=str(update.message.message_id),
            platform=self.PLATFORM,
            user_id=str(update.effective_user.id),
            chat_id=str(update.effective_chat.id),
            text=update.message.text,
            timestamp=datetime.now(timezone.utc),
            message_type=(
                MessageType.COMMAND
                if update.message.text.startswith("/")
                else MessageType.TEXT
            ),
            user_name=update.effective_user.full_name,
            raw_data={"update_id": update.update_id},
        )

        # 發送到 Bus
        await message_bus.publish_inbound(msg)

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
                await self._app.bot.edit_message_text(
                    chat_id=int(msg.chat_id),
                    message_id=int(msg.edit_message_id),
                    text=msg.text,
                    parse_mode=parse_mode,
                )
                return msg.edit_message_id

            # 發送新訊息
            result = await self._app.bot.send_message(
                chat_id=int(msg.chat_id),
                text=msg.text,
                parse_mode=parse_mode,
                reply_to_message_id=(
                    int(msg.reply_to_id) if msg.reply_to_id else None
                ),
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
