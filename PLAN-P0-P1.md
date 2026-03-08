# Aegis P0-P1 執行計畫

> Week 1-2: P0 緊急修復
> Week 3-4: P1 多頻道通訊
> 開始日期：2026-03-10

---

## Week 1: P0 緊急修復（前半）

### Day 1-2: 安全漏洞修復

#### B-C1: Gemini CLI 硬編碼路徑
- **問題**：`runner.py` 中 Gemini 路徑寫死為特定機器路徑
- **影響**：只能在特定機器上運行
- **修復**：
  ```python
  # 改為
  gemini_cmd = ["gemini"]  # 依賴 PATH
  # 或
  gemini_cmd = shutil.which("gemini") or "gemini"
  ```
- **檔案**：`backend/app/runner.py`
- **預估**：2h
- **驗證**：在不同機器測試 Gemini 任務

#### B-C2: 路徑遍歷安全漏洞
- **問題**：portrait 端點未驗證 filename，可讀任意檔案
- **影響**：安全漏洞，可讀取 `/etc/passwd` 等
- **修復**：
  ```python
  # backend/app/routes.py - portrait 端點
  import os

  def safe_join(base: str, filename: str) -> str:
      """防止路徑遍歷攻擊"""
      # 移除 .. 和絕對路徑
      filename = os.path.basename(filename)
      full_path = os.path.join(base, filename)
      # 確保仍在 base 目錄內
      if not os.path.abspath(full_path).startswith(os.path.abspath(base)):
          raise ValueError("Invalid path")
      return full_path
  ```
- **檔案**：`backend/app/routes.py`
- **預估**：2h
- **驗證**：測試 `../../../etc/passwd` 被拒絕

### Day 3-4: 並發控制修復

#### B-C3: Semaphore 競態條件
- **問題**：替換 Semaphore 時造成競態
- **影響**：並行控制失效，可能超載
- **修復**：
  ```python
  # 不要替換 Semaphore，改用 release() + 調整 _value
  async def update_max_slots(new_max: int):
      global task_semaphore
      async with semaphore_lock:
          current = task_semaphore._value
          diff = new_max - current
          if diff > 0:
              for _ in range(diff):
                  task_semaphore.release()
          # 減少槽位需等待任務完成
  ```
- **檔案**：`backend/app/runner.py`, `backend/app/poller.py`
- **預估**：4h
- **驗證**：並發測試，確認不超過限制

---

## Week 2: P0 緊急修復（後半）

### Day 5: 前端修復

#### F-C1: Toast 直接修改 Pinia
- **問題**：Toast 繞過 action 直接 push 到 state
- **影響**：可能競態，違反單向數據流
- **修復**：
  ```typescript
  // stores/toast.ts
  export const useToastStore = defineStore('toast', {
    state: () => ({ toasts: [] as Toast[] }),
    actions: {
      addToast(toast: Toast) {
        this.toasts.push({ ...toast, id: Date.now() })
      },
      removeToast(id: number) {
        this.toasts = this.toasts.filter(t => t.id !== id)
      }
    }
  })
  ```
- **檔案**：`frontend/src/stores/toast.ts`, 調用處
- **預估**：1h

#### F-C2: setInterval 未清理
- **問題**：App.vue 的 setInterval 在 HMR 時不清理
- **影響**：記憶體洩漏，多個 interval 並行
- **修復**：
  ```typescript
  // App.vue
  let intervalId: number | null = null

  onMounted(() => {
    intervalId = setInterval(fetchStatus, 5000)
  })

  onUnmounted(() => {
    if (intervalId) clearInterval(intervalId)
  })
  ```
- **檔案**：`frontend/src/App.vue`
- **預估**：1h

#### F-C3: Kanban 刪除邏輯
- **問題**：刪除卡片後詳情面板不關閉
- **影響**：UI 顯示已刪除卡片
- **修復**：
  ```typescript
  // Kanban.vue
  async function deleteCard(cardId: number) {
    await api.deleteCard(cardId)
    if (selectedCard.value?.id === cardId) {
      selectedCard.value = null  // 關閉詳情
    }
    await refreshCards()
  }
  ```
- **檔案**：`frontend/src/views/Kanban.vue`
- **預估**：1h

### Day 6-7: 測試與驗證

- [ ] 所有 6 個 Critical bug 修復完成
- [ ] 手動測試每個修復
- [ ] 寫 regression test（至少 B-C2, B-C3）
- [ ] 部署到 GCP 測試

---

## Week 3: P1 多頻道通訊（架構）

### Day 8-9: 架構設計

#### 頻道管理器設計
```python
# backend/app/channels/
├── __init__.py
├── base.py          # ChannelBase 抽象類
├── manager.py       # ChannelManager 統一管理
├── telegram.py      # TelegramChannel
├── line.py          # LineChannel
└── discord.py       # DiscordChannel
```

#### 抽象類定義
```python
# backend/app/channels/base.py
from abc import ABC, abstractmethod
from typing import Optional

class ChannelBase(ABC):
    """頻道抽象基類"""

    @abstractmethod
    async def send_message(self, user_id: str, message: str) -> bool:
        """發送訊息"""
        pass

    @abstractmethod
    async def start(self) -> None:
        """啟動頻道監聽"""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """停止頻道"""
        pass

    @abstractmethod
    def parse_command(self, text: str) -> Optional[dict]:
        """解析用戶命令"""
        pass
```

#### 命令格式設計
```
/card create <title>     # 建立卡片
/card list               # 列出卡片
/card status <id>        # 查詢狀態
/task run <card_id>      # 執行任務
/task stop <card_id>     # 中止任務
/status                  # 系統狀態
```

### Day 10: 資料庫擴展

```sql
-- 新增表：頻道綁定
CREATE TABLE channel_bindings (
    id INTEGER PRIMARY KEY,
    platform TEXT NOT NULL,        -- telegram/line/discord
    platform_user_id TEXT NOT NULL,
    aegis_user_id INTEGER,         -- 可選，綁定到 Aegis 用戶
    chat_id TEXT,                  -- 群組/頻道 ID
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(platform, platform_user_id)
);

-- 新增表：頻道訊息日誌
CREATE TABLE channel_messages (
    id INTEGER PRIMARY KEY,
    platform TEXT NOT NULL,
    user_id TEXT NOT NULL,
    direction TEXT NOT NULL,       -- inbound/outbound
    message TEXT NOT NULL,
    card_id INTEGER,               -- 關聯的卡片
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## Week 4: P1 多頻道通訊（實現）

### Day 11-12: Telegram Bot

#### 安裝依賴
```bash
pip install python-telegram-bot==20.7
```

#### 實現
```python
# backend/app/channels/telegram.py
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes

class TelegramChannel(ChannelBase):
    def __init__(self, token: str):
        self.token = token
        self.app = Application.builder().token(token).build()
        self._setup_handlers()

    def _setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("card", self._cmd_card))
        self.app.add_handler(CommandHandler("task", self._cmd_task))
        self.app.add_handler(CommandHandler("status", self._cmd_status))

    async def _cmd_card(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        args = ctx.args
        if not args:
            await update.message.reply_text("用法: /card [create|list|status]")
            return

        action = args[0]
        if action == "create":
            title = " ".join(args[1:]) if len(args) > 1 else "新卡片"
            card = await create_card(title)
            await update.message.reply_text(f"✅ 卡片 #{card.id} 已建立: {title}")
        elif action == "list":
            cards = await list_cards(limit=10)
            text = "\n".join([f"#{c.id} {c.title} [{c.status}]" for c in cards])
            await update.message.reply_text(text or "沒有卡片")
        # ...

    async def start(self):
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

    async def stop(self):
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()
```

### Day 13: LINE Bot

#### 安裝依賴
```bash
pip install line-bot-sdk==3.5.0
```

#### 實現（復用 HappyNAS 經驗）
```python
# backend/app/channels/line.py
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import MessagingApi, TextMessage

class LineChannel(ChannelBase):
    def __init__(self, channel_secret: str, access_token: str):
        self.handler = WebhookHandler(channel_secret)
        self.api = MessagingApi(access_token)
        self._setup_handlers()

    def _setup_handlers(self):
        @self.handler.add(MessageEvent, message=TextMessage)
        def handle_message(event):
            text = event.message.text
            if text.startswith("/"):
                response = self._handle_command(text, event.source.user_id)
                self.api.reply_message(event.reply_token, TextMessage(text=response))

    # Webhook 端點需要在 routes.py 中添加
```

### Day 14: Discord Bot

#### 安裝依賴
```bash
pip install discord.py==2.3.2
```

#### 實現
```python
# backend/app/channels/discord.py
import discord
from discord.ext import commands

class DiscordChannel(ChannelBase):
    def __init__(self, token: str):
        intents = discord.Intents.default()
        intents.message_content = True
        self.bot = commands.Bot(command_prefix="/", intents=intents)
        self._setup_commands()

    def _setup_commands(self):
        @self.bot.command(name="card")
        async def card_cmd(ctx, action: str, *args):
            if action == "create":
                title = " ".join(args) if args else "新卡片"
                card = await create_card(title)
                await ctx.send(f"✅ 卡片 #{card.id} 已建立")
            # ...

    async def start(self):
        await self.bot.start(self.token)

    async def stop(self):
        await self.bot.close()
```

### Day 15: 整合與測試

#### ChannelManager
```python
# backend/app/channels/manager.py
class ChannelManager:
    def __init__(self):
        self.channels: dict[str, ChannelBase] = {}

    def register(self, name: str, channel: ChannelBase):
        self.channels[name] = channel

    async def start_all(self):
        for name, channel in self.channels.items():
            try:
                await channel.start()
                logger.info(f"Channel {name} started")
            except Exception as e:
                logger.error(f"Failed to start {name}: {e}")

    async def stop_all(self):
        for name, channel in self.channels.items():
            await channel.stop()

    async def broadcast(self, message: str, exclude: list[str] = None):
        """廣播訊息到所有頻道"""
        for name, channel in self.channels.items():
            if exclude and name in exclude:
                continue
            # 發送到該頻道的所有訂閱者
```

#### 啟動整合
```python
# backend/app/main.py
from app.channels.manager import ChannelManager
from app.channels.telegram import TelegramChannel
from app.channels.line import LineChannel
from app.channels.discord import DiscordChannel

channel_manager = ChannelManager()

@app.on_event("startup")
async def startup():
    # 根據環境變數啟用頻道
    if os.getenv("TELEGRAM_TOKEN"):
        channel_manager.register("telegram", TelegramChannel(os.getenv("TELEGRAM_TOKEN")))
    if os.getenv("LINE_CHANNEL_SECRET"):
        channel_manager.register("line", LineChannel(
            os.getenv("LINE_CHANNEL_SECRET"),
            os.getenv("LINE_ACCESS_TOKEN")
        ))
    if os.getenv("DISCORD_TOKEN"):
        channel_manager.register("discord", DiscordChannel(os.getenv("DISCORD_TOKEN")))

    await channel_manager.start_all()

@app.on_event("shutdown")
async def shutdown():
    await channel_manager.stop_all()
```

---

## 驗收標準

### P0 完成標準
- [ ] 6 個 Critical bug 全部修復
- [ ] 無安全漏洞（路徑遍歷測試通過）
- [ ] 並發控制正常（3 個任務並行）
- [ ] 前端無記憶體洩漏
- [ ] GCP 部署正常運行

### P1 完成標準
- [ ] Telegram Bot 可用（/card, /task, /status）
- [ ] LINE Bot 可用
- [ ] Discord Bot 可用
- [ ] 遠端建卡功能正常
- [ ] 任務狀態查詢正常
- [ ] 任務中止功能正常

---

## 環境變數新增

```bash
# .env 新增
TELEGRAM_TOKEN=your_telegram_bot_token
LINE_CHANNEL_SECRET=your_line_channel_secret
LINE_ACCESS_TOKEN=your_line_access_token
DISCORD_TOKEN=your_discord_bot_token
```

---

## 風險與備案

| 風險 | 機率 | 影響 | 備案 |
|------|------|------|------|
| Semaphore 修復影響現有任務 | 中 | 高 | 先在測試環境驗證 |
| LINE Webhook 需要 HTTPS | 高 | 中 | 使用 ngrok 或 GCP 部署 |
| Discord Bot 需要 Intent 權限 | 中 | 低 | 申請 Message Content Intent |
| Telegram 被牆 | 高 | 中 | GCP 部署（非中國區） |

---

*計畫建立日期：2026-03-09*
*預計完成：2026-04-07*
