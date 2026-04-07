# Aegis 編碼黃金規則

> 本文件定義 Aegis 專案的核心編碼規範。所有貢獻者（包含 AI 成員）皆須遵守。
>
> 嚴重度說明：
> - **MUST** — 強制，違反將在 code review 中被退回
> - **SHOULD** — 建議，除非有充分理由否則應遵守
> - **MAY** — 可選，視情境採用

---

## 1. 錯誤處理：logger + raise，不靜默吞掉 `[MUST]`

所有例外必須被記錄並適當傳播，禁止空的 `except: pass`。

```python
# WRONG
try:
    do_something()
except Exception:
    pass

# CORRECT
try:
    do_something()
except Exception as e:
    logger.error("do_something failed: %s", e)
    raise
```

- 在 API 層可以攔截例外並回傳錯誤回應，但仍須記錄
- 在背景任務中，必須記錄完整 traceback (`logger.exception`)

---

## 2. 日誌格式：模組級 logger `[MUST]`

每個模組頂層建立 logger，不使用 `print()` 做日誌輸出。

```python
import logging

logger = logging.getLogger(__name__)
```

- 日誌訊息應包含足夠的上下文（模組、操作、關鍵參數）
- 敏感資料（token、密碼）禁止出現在日誌中

---

## 3. API 回應：Pydantic BaseModel + response_model `[MUST]`

所有 API endpoint 必須定義 Pydantic schema 作為回應模型。

```python
from pydantic import BaseModel

class ItemResponse(BaseModel):
    id: int
    name: str
    status: str

@router.get("/items/{item_id}", response_model=ItemResponse)
async def get_item(item_id: int):
    ...
```

- Schema 定義集中放在 `api/schemas.py` 或各路由對應的 schema 模組
- 回應格式保持一致的信封結構（data / error / metadata）

---

## 4. 環境變數：統一從 .env 讀取 `[MUST]`

所有設定值從環境變數取得，禁止散落在程式碼中的硬編碼。

```python
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise RuntimeError("Missing required env var: API_KEY")
```

- 新增環境變數時須同步更新 `.env.example`
- 啟動時驗證必要環境變數是否存在

---

## 5. 資料庫：SQLModel + Session，不在路由寫原生 SQL `[MUST]`

使用 SQLModel ORM 操作資料庫，路由層禁止直接撰寫原生 SQL。

```python
# WRONG — 在 route 裡寫原生 SQL
@router.get("/members")
async def list_members():
    conn = sqlite3.connect("local.db")
    rows = conn.execute("SELECT * FROM members")
    ...

# CORRECT — 使用 SQLModel Session
from sqlmodel import Session, select
from app.database import engine

@router.get("/members")
async def list_members():
    with Session(engine) as session:
        members = session.exec(select(Member)).all()
        return members
```

- 需要複雜查詢時，封裝在 `core/` 模組或 repository 中
- 資料庫 schema 異動透過 migration 機制處理

---

## 6. 測試：新功能必須有 pytest 測試 `[MUST]`

每個新功能或 bug fix 必須附帶至少一個 happy path 測試。

```python
# backend/tests/test_card_factory.py
def test_create_card_returns_valid_id():
    card = create_card(title="Test", content="Hello")
    assert card.id is not None
    assert card.title == "Test"
```

- 測試放在 `backend/tests/` 目錄下
- 檔名格式：`test_<module>.py`
- 使用 `pytest` 執行，設定見 `pytest.ini`

---

## 7. 安全：不硬編碼密鑰、驗證輸入、參數化查詢 `[MUST]`

```python
# WRONG — 硬編碼密鑰
API_KEY = "sk-abc123..."

# WRONG — 字串拼接 SQL
query = f"SELECT * FROM users WHERE name = '{user_input}'"

# CORRECT
API_KEY = os.getenv("API_KEY")
session.exec(select(User).where(User.name == user_input))
```

- API Key、Token、密碼一律透過環境變數或密鑰管理器取得
- 所有使用者輸入必須驗證後才處理
- 錯誤訊息不得洩漏內部實作細節

---

## 8. 共用工具：優先使用 core/ 既有模組 `[SHOULD]`

`backend/app/core/` 已包含大量共用模組（http_client、model_router、cost_calculator 等）。新功能開發前先查找是否有可複用的工具。

- 新建 utility 前，先搜尋 `core/` 是否已有類似功能
- 若需要擴充既有模組，優先擴充而非建立新檔案
- 跨模組共用的邏輯應提取至 `core/`

---

## 9. 不可變性：建立新物件，不修改既有物件 `[SHOULD]`

操作資料時建立新物件，避免原地修改（in-place mutation）。

```python
# WRONG — 原地修改
config["key"] = "new_value"
items.append(new_item)

# CORRECT — 建立新物件
new_config = {**config, "key": "new_value"}
new_items = [*items, new_item]
```

- Pydantic model 使用 `.model_copy(update={...})` 產生新實例
- 函式應避免修改傳入的參數

---

## 10. 檔案組織：小檔案、高內聚、低耦合 `[SHOULD]`

- 單一檔案控制在 200–400 行，上限 800 行
- 單一函式控制在 50 行以內
- 按功能/領域組織，而非按類型歸類
- 巢狀層級不超過 4 層

```
# WRONG — 一個巨大的 routes.py 包含所有路由
backend/app/api/routes.py  (2000 lines)

# CORRECT — 按領域拆分
backend/app/api/cards.py
backend/app/api/members.py
backend/app/api/projects.py
```

---

## 11. 非同步：async endpoint 中不阻塞事件迴圈 `[MUST]`

FastAPI 的 async endpoint 中禁止呼叫阻塞式 I/O。

```python
# WRONG — 在 async 中呼叫阻塞式操作
@router.get("/data")
async def get_data():
    result = requests.get("https://api.example.com")  # 阻塞!

# CORRECT — 使用 async HTTP client
@router.get("/data")
async def get_data():
    async with httpx.AsyncClient() as client:
        result = await client.get("https://api.example.com")
```

- 若必須呼叫同步函式，使用 `asyncio.to_thread()` 或 `run_in_executor`
- 資料庫操作若為同步，endpoint 宣告為 `def`（非 `async def`）

---

## 12. Git 提交：語義化 commit message `[SHOULD]`

遵循 Conventional Commits 格式：

```
<type>(<scope>): <description>

type: feat | fix | refactor | docs | test | chore
scope: 影響範圍（如 cards, auth, runner）
```

範例：
- `feat(cards): 新增卡片標籤篩選功能`
- `fix(runner): 修正 PTY 串流中斷問題`

---

## 13. 型別標註：函式簽名加型別提示 `[SHOULD]`

公開函式的參數與回傳值應標註型別。

```python
# WRONG
def calculate_cost(tokens, model):
    ...

# CORRECT
def calculate_cost(tokens: int, model: str) -> float:
    ...
```

- 內部輔助函式可視複雜度決定是否標註
- 複雜型別使用 `typing` 模組（Optional、List、Dict 等）

---

## 14. 依賴注入：路由層透過 Depends 取得共用資源 `[MAY]`

利用 FastAPI 的 `Depends` 機制注入資料庫 session 等共用資源。

```python
from fastapi import Depends
from app.api.deps import get_session

@router.get("/items")
async def list_items(session: Session = Depends(get_session)):
    ...
```

- 有助於測試時替換 mock 依賴
- 認證、權限檢查也應透過 Depends 實現

---

## 15. 前端元件：Vue 3 Composition API + 單一職責 `[MAY]`

前端元件使用 `<script setup>` 語法，保持單一職責。

```vue
<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{ title: string }>()
const count = ref(0)
const doubled = computed(() => count.value * 2)
</script>
```

- 元件檔案控制在 300 行以內
- 共用邏輯提取為 composable（`use*.ts`）
- 避免在 template 中放置複雜邏輯

---

## 快速參照表

| # | 規則 | 嚴重度 |
|---|------|--------|
| 1 | 錯誤處理：logger + raise | MUST |
| 2 | 日誌格式：模組級 logger | MUST |
| 3 | API 回應：Pydantic + response_model | MUST |
| 4 | 環境變數：統一從 .env 讀取 | MUST |
| 5 | 資料庫：SQLModel + Session | MUST |
| 6 | 測試：新功能必須有 pytest | MUST |
| 7 | 安全：不硬編碼密鑰 | MUST |
| 8 | 共用工具：優先用 core/ | SHOULD |
| 9 | 不可變性：建立新物件 | SHOULD |
| 10 | 檔案組織：小檔案高內聚 | SHOULD |
| 11 | 非同步：不阻塞事件迴圈 | MUST |
| 12 | Git 提交：語義化 message | SHOULD |
| 13 | 型別標註：函式簽名 | SHOULD |
| 14 | 依賴注入：Depends | MAY |
| 15 | 前端元件：Composition API | MAY |
