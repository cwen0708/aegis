import json, urllib.request

API = 'http://127.0.0.1:8899/api/v1'
CARD_ID = 13199

DESCRIPTION = """# P1-MA-05 步驟1：Matrix 介面骨架（Shadow Mode 鋪路）

## 目的

為 Matrix 協作 Phase 1（Shadow Mode 雙寫）鋪路：**先建立 client 介面與資料模型骨架**，完全不呼叫外部 Matrix / Tuwunel 服務，不改 `ask_member`。本步驟 30 分鐘內可完成、不影響現有 `ConversationRoom`。

## ⚠️ 警示（請先讀）

- **命名衝突**：`app/core/sync_matrix.py` 是「同步矩陣」規則引擎（欄位級同步），**跟 Matrix 協議無關**。新模組一律放 `app/matrix/`，檔案 docstring 開頭要註明此區別，避免未來 grep 誤殺。
- **抽機制、不硬 port**：vendor `multi-agent-hiclaw.md` 只作為「概念參考」，本步驟用 Aegis 風格（Pydantic + 不變性）重寫，不逐行複製。
- **不實作網路呼叫**：本步驟只有介面 + NoOp 實作，**不引入** `matrix-nio` / `aiohttp` 依賴。

## 具體修改步驟

1. **新增 `backend/app/matrix/__init__.py`**（空檔，建立 package）

2. **新增 `backend/app/matrix/models.py`**：
   - `RoomType` enum：`WORKER`（3-party）/ `TEAM_WORKER`（leader+admin+worker）/ `TEAM`
   - `MatrixMessage` Pydantic model 欄位：`room_id: str`、`sender: str`、`body: str`、`timestamp: datetime`、`ref_meeting_id: str | None`（ref 對應現有 `ConversationRoom.meeting_id`）
   - `RoomConfig` Pydantic model 欄位：`room_type: RoomType`、`room_alias: str`、`members: list[str]`
   - 檔案開頭 docstring 明確寫：「此處 Matrix 指 matrix.org 協議，非 `app/core/sync_matrix.py` 的欄位級同步規則」

3. **新增 `backend/app/matrix/client.py`**：
   - `MatrixClient`（Protocol 或 abstract base）：`send_message(msg: MatrixMessage) -> str`（回傳 event_id）、`create_room(cfg: RoomConfig) -> str`（回傳 room_id）
   - `NoOpMatrixClient`（shadow 模式安全預設）：兩個方法回傳空字串 `""`、不拋例外、不做任何 I/O
   - 純不變性：輸入不 mutate，回傳新字串

4. **新增 `backend/tests/test_matrix_client.py`**（TDD，先紅再綠）：
   - `MatrixMessage` 序列化 / 反序列化（`model_dump_json` / `model_validate_json`）
   - `RoomType` enum 值（`worker` / `team_worker` / `team`）
   - `RoomConfig` 欄位驗證（缺欄位時 `ValidationError`）
   - `NoOpMatrixClient.send_message` 回傳 `""`、不拋例外
   - `NoOpMatrixClient.create_room` 回傳 `""`、不拋例外

## 驗證方式

```bash
cd backend
venv/bin/pytest -xvs tests/test_matrix_client.py
ruff check app/matrix/
```

**AC**：
- 所有測試通過
- `ruff check` 無新增錯誤
- **不引入新的第三方套件**（`matrix-nio` 留到後續步驟）
- **不改動** `ask_member` / `ConversationRoom` / `app/core/sync_matrix.py` 任何現有檔案

## 後續步驟預告（不在本卡範圍）

- Step 2：引入 `matrix-nio`，寫 `TuwunelMatrixClient`（真實實作）+ integration test
- Step 3：aegis-gs 安裝 Tuwunel（sudo / systemd）
- Step 4：`ask_member` 接 `MatrixClient`，shadow 雙寫（不切換，驗證用）
- Step 5：小良哥 Element App 驗證能旁聽 Team Room

## 跟其他卡片的關係（警示二）

- 對照 #13127 P0-MA-01 step1（TOML 團隊模板，已 completed）的風格：純資料模型 + 骨架 + TDD，不接線。
- 對照 #13195 P0-MA-02 step1（skill_index，已 completed）的命名模式。
- 本步驟**沒有機制重疊**：`app/core/sync_matrix.py` 是欄位級同步規則，本模組是 Matrix.org 即時通訊 client，用途完全不同。

## 警示檢核（審查者已核實）

- [x] 警示一：已 grep 確認 Aegis 目前無 Matrix/Tuwunel 實作；`ConversationRoom` 位於 `app/core/conversation/room.py` 確實存在
- [x] 警示二：已確認 `sync_matrix.py` 是命名撞到但用途不同；規劃時用 `app/matrix/` 獨立目錄
- [x] 警示三：本步驟完全不 port vendor 程式碼，只建立 Aegis 風格骨架
"""

data = json.dumps({'description': DESCRIPTION}).encode('utf-8')
req = urllib.request.Request(
    f'{API}/cards/{CARD_ID}',
    data=data,
    headers={'Content-Type': 'application/json'},
    method='PATCH',
)
try:
    resp = urllib.request.urlopen(req)
    print('PATCH status:', resp.status)
    print('Response:', resp.read()[:200].decode('utf-8'))
except urllib.error.HTTPError as e:
    print('HTTPError:', e.code, e.read().decode('utf-8')[:500])

card = json.loads(urllib.request.urlopen(f'{API}/cards/{CARD_ID}').read())
print('New desc len:', len(card.get('description', '')))
print('Status:', card.get('status'))
