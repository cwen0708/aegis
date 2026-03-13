# Aegis P1 多頻道通訊架構（Message Bus 版）

> 狀態：正式版
> 建立日期：2026-03-09
> 參考來源：Nanobot, ZeroClaw, PicoClaw 最佳實踐
> 現有資源：LINE Bot, Telegram Bot

---

## 一、架構概覽

```
┌─────────────────────────────────────────────────────────────┐
│                    外部平台                                  │
│   Telegram Bot    LINE Bot    Discord (未來)                 │
└──────────────┬─────────────────────┬───────────────────────┘
               │                     │
┌──────────────▼─────────────────────▼───────────────────────┐
│                 Channel Adapters                            │
│         (平台 SDK → 統一格式翻譯層)                          │
│    TelegramChannel      LineChannel      DiscordChannel    │
└──────────────┬─────────────────────┬───────────────────────┘
               │ InboundMessage      │
               ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    Message Bus                              │
│              (asyncio.Queue 事件驅動)                       │
│         inbound_queue ←→ outbound_queue                    │
└──────────────┬─────────────────────┬───────────────────────┘
               │                     ▲
               ▼                     │ OutboundMessage
┌─────────────────────────────────────────────────────────────┐
│                  Message Router                             │
│           (命令解析 + 業務分派 + 回應產生)                    │
│      CommandParser → CommandHandler → ResponseBuilder       │
└──────────────┬─────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│                   Aegis Core                                │
│         (現有 runner.py, cards, tasks, members)             │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、核心設計原則

| 原則 | 說明 |
|------|------|
| **平台無關** | 核心邏輯不知道訊息來自哪個平台 |
| **單一翻譯點** | 每個頻道只負責「平台格式 ↔ 統一格式」|
| **事件驅動** | 訊息透過 Queue 傳遞，非同步處理 |
| **易於擴展** | 新增頻道只需實作 ChannelBase |

---

## 三、目錄結構

```
backend/app/channels/
├── __init__.py
├── types.py          # InboundMessage, OutboundMessage, ChannelStatus
├── base.py           # ChannelBase 抽象類
├── registry.py       # 頻道註冊表 (Factory Pattern)
├── bus.py            # MessageBus (雙向 Queue)
├── router.py         # MessageRouter (命令解析 + 業務分派)
├── adapters/
│   ├── __init__.py
│   ├── telegram.py   # TelegramChannel
│   ├── line.py       # LineChannel
│   └── discord.py    # DiscordChannel (未來)
└── commands/
    ├── __init__.py
    ├── parser.py     # CommandParser
    └── handlers.py   # 各命令處理函數
```

---

## 四、統一訊息格式

### 4.1 InboundMessage（來自平台）

```python
# backend/app/channels/types.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum

class MessageType(str, Enum):
    TEXT = "text"
    COMMAND = "command"
    CALLBACK = "callback"  # 按鈕回調
    FILE = "file"

@dataclass
class InboundMessage:
    """來自任何頻道的訊息（統一格式）"""
    id: str                          # 訊息 ID
    platform: str                    # telegram / line / discord
    user_id: str                     # 平台用戶 ID
    chat_id: str                     # 聊天室 ID
    text: str                        # 訊息內容
    timestamp: datetime
    message_type: MessageType = MessageType.TEXT
    reply_to_id: Optional[str] = None
    user_name: Optional[str] = None  # 顯示名稱（如有）
    raw_data: dict = field(default_factory=dict)  # 原始資料備查
```

### 4.2 OutboundMessage（發送到平台）

```python
class ParseMode(str, Enum):
    PLAIN = "plain"
    MARKDOWN = "markdown"
    HTML = "html"

@dataclass
class Button:
    """互動按鈕"""
    text: str
    callback_data: str

@dataclass
class OutboundMessage:
    """發送到任何頻道的訊息（統一格式）"""
    chat_id: str
    text: str
    platform: Optional[str] = None   # None = 廣播到所有平台
    parse_mode: ParseMode = ParseMode.MARKDOWN
    reply_to_id: Optional[str] = None
    buttons: list[list[Button]] = field(default_factory=list)  # 按鈕網格

    # 用於任務通知
    task_id: Optional[str] = None
    card_id: Optional[int] = None
```

### 4.3 ChannelStatus

```python
@dataclass
class ChannelStatus:
    """頻道狀態"""
    platform: str
    is_connected: bool
    last_heartbeat: Optional[datetime] = None
    error: Optional[str] = None
    stats: dict = field(default_factory=dict)  # 自訂統計
```

---

## 五、ChannelBase 抽象類

```python
# backend/app/channels/base.py
from abc import ABC, abstractmethod
from typing import AsyncIterator
from .types import InboundMessage, OutboundMessage, ChannelStatus

class ChannelBase(ABC):
    """頻道抽象基類 — 只負責平台翻譯"""

    PLATFORM: str = "unknown"

    @abstractmethod
    async def start(self) -> None:
        """啟動頻道連線"""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """停止頻道"""
        pass

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> bool:
        """發送訊息到平台（翻譯 OutboundMessage → 平台格式）"""
        pass

    @abstractmethod
    async def listen(self) -> AsyncIterator[InboundMessage]:
        """監聽平台訊息（翻譯平台格式 → InboundMessage）"""
        pass

    @abstractmethod
    async def health_check(self) -> ChannelStatus:
        """健康檢查"""
        pass
```

---

## 六、頻道註冊表（Factory Pattern）

```python
# backend/app/channels/registry.py
from typing import Type, Callable
from .base import ChannelBase
import logging

logger = logging.getLogger(__name__)

# 全域註冊表
_CHANNEL_REGISTRY: dict[str, Type[ChannelBase]] = {}

def register_channel(name: str):
    """裝飾器：註冊頻道類別"""
    def decorator(cls: Type[ChannelBase]):
        _CHANNEL_REGISTRY[name] = cls
        cls.PLATFORM = name
        logger.info(f"Channel registered: {name}")
        return cls
    return decorator

def create_channel(name: str, **config) -> ChannelBase:
    """工廠函數：建立頻道實例"""
    if name not in _CHANNEL_REGISTRY:
        raise ValueError(f"Unknown channel: {name}")
    return _CHANNEL_REGISTRY[name](**config)

def list_channels() -> list[str]:
    """列出所有已註冊頻道"""
    return list(_CHANNEL_REGISTRY.keys())
```

---

## 七、Message Bus

```python
# backend/app/channels/bus.py
import asyncio
from typing import Optional
from .types import InboundMessage, OutboundMessage
import logging

logger = logging.getLogger(__name__)

class MessageBus:
    """訊息總線 — 解耦頻道與核心邏輯"""

    def __init__(self, maxsize: int = 1000):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=maxsize)
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=maxsize)
        self._running = False

    async def publish_inbound(self, msg: InboundMessage):
        """頻道調用：發布收到的訊息"""
        await self.inbound.put(msg)
        logger.debug(f"Inbound: [{msg.platform}] {msg.user_id}: {msg.text[:50]}")

    async def publish_outbound(self, msg: OutboundMessage):
        """核心調用：發布要發送的訊息"""
        await self.outbound.put(msg)
        logger.debug(f"Outbound: [{msg.platform or 'broadcast'}] {msg.text[:50]}")

    async def consume_inbound(self) -> InboundMessage:
        """Router 調用：取得待處理訊息"""
        return await self.inbound.get()

    async def consume_outbound(self) -> OutboundMessage:
        """頻道調用：取得待發送訊息"""
        return await self.outbound.get()

# 全域 Bus 實例
message_bus = MessageBus()
```

---

## 八、Message Router

```python
# backend/app/channels/router.py
import asyncio
from .bus import message_bus
from .types import InboundMessage, OutboundMessage, MessageType
from .commands.parser import parse_command
from .commands.handlers import handle_command
import logging

logger = logging.getLogger(__name__)

class MessageRouter:
    """訊息路由器 — 處理 inbound，產生 outbound"""

    def __init__(self):
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self):
        """啟動路由循環"""
        self._running = True
        self._task = asyncio.create_task(self._route_loop())
        logger.info("MessageRouter started")

    async def stop(self):
        """停止路由"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MessageRouter stopped")

    async def _route_loop(self):
        """主路由循環"""
        while self._running:
            try:
                msg = await asyncio.wait_for(
                    message_bus.consume_inbound(),
                    timeout=1.0
                )
                await self._handle_message(msg)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Router error: {e}")

    async def _handle_message(self, msg: InboundMessage):
        """處理單一訊息"""
        # 解析命令
        cmd = parse_command(msg.text)

        if cmd:
            # 執行命令
            response_text = await handle_command(cmd, msg)
        else:
            # 非命令訊息（未來可接 AI 對話）
            response_text = None

        # 產生回應
        if response_text:
            await message_bus.publish_outbound(OutboundMessage(
                chat_id=msg.chat_id,
                platform=msg.platform,
                text=response_text,
                reply_to_id=msg.id,
            ))
```

---

## 九、命令解析

```python
# backend/app/channels/commands/parser.py
import re
from dataclasses import dataclass
from typing import Optional
from enum import Enum

class CommandType(str, Enum):
    CARD_CREATE = "card.create"
    CARD_LIST = "card.list"
    CARD_VIEW = "card.view"
    TASK_RUN = "task.run"
    TASK_STOP = "task.stop"
    STATUS = "status"
    HELP = "help"

@dataclass
class ParsedCommand:
    cmd_type: CommandType
    args: list[str]
    raw: str

# 命令模式
PATTERNS = [
    (r"^/card\s+create\s+(.+)$", CommandType.CARD_CREATE),
    (r"^/card\s+list$", CommandType.CARD_LIST),
    (r"^/card\s+(\d+)$", CommandType.CARD_VIEW),
    (r"^/task\s+run\s+(\d+)$", CommandType.TASK_RUN),
    (r"^/task\s+stop\s+(\d+)$", CommandType.TASK_STOP),
    (r"^/status$", CommandType.STATUS),
    (r"^/(help|start)$", CommandType.HELP),
]

def parse_command(text: str) -> Optional[ParsedCommand]:
    """解析命令文字"""
    text = text.strip()
    for pattern, cmd_type in PATTERNS:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            return ParsedCommand(
                cmd_type=cmd_type,
                args=list(match.groups()),
                raw=text,
            )
    return None
```

---

## 十、Telegram Adapter 範例

```python
# backend/app/channels/adapters/telegram.py
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from ..base import ChannelBase
from ..registry import register_channel
from ..bus import message_bus
from ..types import InboundMessage, OutboundMessage, ChannelStatus, MessageType
from datetime import datetime, timezone
import asyncio
import logging

logger = logging.getLogger(__name__)

@register_channel("telegram")
class TelegramChannel(ChannelBase):
    """Telegram 頻道適配器"""

    PLATFORM = "telegram"

    def __init__(self, token: str):
        self.token = token
        self._app: Application | None = None
        self._send_task: asyncio.Task | None = None
        self._running = False

    async def start(self):
        self._running = True

        # 建立 Telegram Application
        self._app = Application.builder().token(self.token).build()
        self._app.add_handler(MessageHandler(
            filters.TEXT | filters.COMMAND,
            self._on_message
        ))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)

        # 啟動發送循環
        self._send_task = asyncio.create_task(self._send_loop())
        logger.info("TelegramChannel started")

    async def stop(self):
        self._running = False
        if self._app and self._app.updater.running:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        if self._send_task:
            self._send_task.cancel()
        logger.info("TelegramChannel stopped")

    async def _on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """收到訊息 → 翻譯為 InboundMessage → 發到 Bus"""
        if not update.message or not update.message.text:
            return

        msg = InboundMessage(
            id=str(update.message.message_id),
            platform=self.PLATFORM,
            user_id=str(update.effective_user.id),
            chat_id=str(update.effective_chat.id),
            text=update.message.text,
            timestamp=datetime.now(timezone.utc),
            message_type=MessageType.COMMAND if update.message.text.startswith("/") else MessageType.TEXT,
            user_name=update.effective_user.full_name,
            raw_data={"update": update.to_dict()},
        )
        await message_bus.publish_inbound(msg)

    async def _send_loop(self):
        """發送循環：從 Bus 取訊息 → 翻譯為 Telegram 格式 → 發送"""
        while self._running:
            try:
                msg = await asyncio.wait_for(
                    message_bus.consume_outbound(),
                    timeout=1.0
                )
                # 只處理發給此平台或廣播的訊息
                if msg.platform and msg.platform != self.PLATFORM:
                    # 放回 Queue（讓其他頻道處理）
                    await message_bus.publish_outbound(msg)
                    continue

                await self.send(msg)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Telegram send loop error: {e}")

    async def send(self, msg: OutboundMessage) -> bool:
        """發送單一訊息"""
        if not self._app:
            return False
        try:
            parse_mode = "Markdown" if msg.parse_mode.value == "markdown" else None
            await self._app.bot.send_message(
                chat_id=int(msg.chat_id),
                text=msg.text,
                parse_mode=parse_mode,
                reply_to_message_id=int(msg.reply_to_id) if msg.reply_to_id else None,
            )
            return True
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    async def listen(self):
        # Polling 模式由 _on_message 處理，此方法備用
        while self._running:
            await asyncio.sleep(1)
            yield  # 實際訊息透過 _on_message → Bus

    async def health_check(self) -> ChannelStatus:
        if self._app and self._app.bot:
            try:
                me = await self._app.bot.get_me()
                return ChannelStatus(
                    platform=self.PLATFORM,
                    is_connected=True,
                    last_heartbeat=datetime.now(timezone.utc),
                    stats={"bot_username": me.username},
                )
            except Exception as e:
                return ChannelStatus(
                    platform=self.PLATFORM,
                    is_connected=False,
                    error=str(e),
                )
        return ChannelStatus(platform=self.PLATFORM, is_connected=False)
```

---

## 十一、ChannelManager 整合

```python
# backend/app/channels/manager.py
import asyncio
from typing import Optional
from .base import ChannelBase
from .bus import message_bus
from .router import MessageRouter
from .types import ChannelStatus
import logging

logger = logging.getLogger(__name__)

class ChannelManager:
    """頻道管理器"""

    def __init__(self):
        self.channels: dict[str, ChannelBase] = {}
        self.router = MessageRouter()

    def register(self, channel: ChannelBase):
        """註冊頻道實例"""
        self.channels[channel.PLATFORM] = channel

    async def start_all(self):
        """啟動所有頻道 + Router"""
        # 先啟動 Router
        await self.router.start()

        # 再啟動各頻道
        for name, channel in self.channels.items():
            try:
                await channel.start()
                logger.info(f"Channel started: {name}")
            except Exception as e:
                logger.error(f"Failed to start {name}: {e}")

    async def stop_all(self):
        """停止所有頻道 + Router"""
        for name, channel in self.channels.items():
            try:
                await channel.stop()
            except Exception as e:
                logger.error(f"Failed to stop {name}: {e}")

        await self.router.stop()

    async def health_check_all(self) -> dict[str, ChannelStatus]:
        """所有頻道健康檢查"""
        results = {}
        for name, channel in self.channels.items():
            results[name] = await channel.health_check()
        return results

    async def broadcast(self, text: str, exclude: list[str] = None):
        """廣播訊息到所有頻道的所有已綁定用戶"""
        # TODO: 從 ChannelBinding 取得所有用戶
        pass

# 全域實例（或用 FastAPI Depends）
channel_manager = ChannelManager()
```

---

## 十二、與現有 Aegis 整合

```python
# backend/app/main.py（修改）
import os
from contextlib import asynccontextmanager
from app.channels.manager import channel_manager
from app.channels.adapters.telegram import TelegramChannel
from app.channels.adapters.line import LineChannel

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 現有初始化...

    # 頻道初始化
    if token := os.getenv("TELEGRAM_BOT_TOKEN"):
        channel_manager.register(TelegramChannel(token))

    if secret := os.getenv("LINE_CHANNEL_SECRET"):
        channel_manager.register(LineChannel(
            channel_secret=secret,
            access_token=os.getenv("LINE_ACCESS_TOKEN"),
        ))

    await channel_manager.start_all()

    yield

    await channel_manager.stop_all()
```

---

## 十三、任務完成通知

```python
# backend/app/core/runner.py（修改）

async def _on_task_complete(task_id: str, card_id: int, result: str):
    """任務完成回調 — 發送通知到 Bus"""
    from app.channels.bus import message_bus
    from app.channels.types import OutboundMessage

    # 通知所有有綁定的用戶（platform=None 表示廣播）
    await message_bus.publish_outbound(OutboundMessage(
        chat_id="BROADCAST",  # 特殊標記
        platform=None,
        text=f"✅ 任務完成\n📋 卡片 #{card_id}\n\n{result[:500]}",
        task_id=task_id,
        card_id=card_id,
    ))
```

---

## 十四、與 HappyNAS 的關係

| 面向 | HappyNAS 現狀 | Aegis 新架構 |
|------|---------------|--------------|
| Bot Token | 現有 LINE/Telegram Bot | **共用**（環境變數） |
| Webhook | Flask on GCP | **可共用或獨立** |
| 核心邏輯 | Happy Server → Claude CLI | Aegis Runner → Claude/Gemini |
| 訊息格式 | 各自處理 | **統一 Inbound/Outbound** |

**建議**：
1. Aegis 獨立運行，與 HappyNAS 分開（避免複雜度）
2. 可共用 Bot Token，但各自處理（用 Webhook secret 區分）
3. 或建立新的 Bot（@aegis_bot）

---

## 十五、實作時程

| Day | 任務 |
|-----|------|
| 1 | types.py, base.py, registry.py |
| 2 | bus.py, router.py |
| 3 | commands/parser.py, commands/handlers.py |
| 4 | adapters/telegram.py + 測試 |
| 5 | adapters/line.py + Webhook |
| 6 | manager.py + main.py 整合 |
| 7 | 任務通知 + 測試部署 |

---

## 十六、檔案清單

建立順序：
1. `backend/app/channels/__init__.py`
2. `backend/app/channels/types.py`
3. `backend/app/channels/base.py`
4. `backend/app/channels/registry.py`
5. `backend/app/channels/bus.py`
6. `backend/app/channels/router.py`
7. `backend/app/channels/commands/__init__.py`
8. `backend/app/channels/commands/parser.py`
9. `backend/app/channels/commands/handlers.py`
10. `backend/app/channels/adapters/__init__.py`
11. `backend/app/channels/adapters/telegram.py`
12. `backend/app/channels/adapters/line.py`
13. `backend/app/channels/manager.py`

---

*版本：v2.0（Message Bus 架構）*
*草案 v1.0 已存檔為 PLAN-P1-MULTICHANNEL-DRAFT.md*
