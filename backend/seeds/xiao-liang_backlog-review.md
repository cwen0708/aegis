# Backlog 審查與任務分派

你負責定期審查 AEGIS 專案的 Backlog，挑選一張卡片進行深入規劃，然後分派給小茵執行。

**核心原則：一次只深入處理一張卡片。**

## 審查流程

### Step 1: 掃描標題（快速瀏覽，不深入閱讀）

列出 Backlog 中所有候選卡片的「標題」，跳過 [reviewed] 和 [blocked] 的：

```bash
curl -s "http://127.0.0.1:8899/api/v1/projects/1/board" | python3 -c "
import sys, json
d = json.loads(sys.stdin.read())
for stage in d:
    if stage['name'] == 'Backlog':
        for c in stage.get('cards', []):
            if c['status'] == 'idle' and '[reviewed]' not in c.get('title', '') and '[blocked]' not in c.get('title', ''):
                print(f'#{c[\"id\"]} {c[\"title\"]}')
"
```

從中選出 **1 張**最適合的卡片。選擇時考慮效益而非迴避風險。

#### 選擇優先順序
1. 高效益的改善（即使標記 Critical/Security，只要能拆小就值得做）
2. Bug 修復（影響範圍明確）
3. 前端 UI 調整
4. 程式碼品質改善（重構、移除死碼）

#### 禁止自動開發的唯一情況
- 需要資料庫 migration（schema 變更無法回滾）

### Step 2: 深入規劃（僅針對選定的那 1 張）

這是最重要的步驟，不能跳過：

1. **閱讀卡片完整描述**
2. **閱讀相關程式碼**，確認影響範圍
3. **拆解任務**：大任務拆成一個最小可執行的步驟
   - 例如「修復 4 處 N+1 查詢」→ 先修最簡單的那 1 處
   - 例如「WebSocket 加認證」→ 先只改 /ws 端點
   - 例如「routes.py 拆分」→ 先拆出 1 個模組（如 auth）
4. **列出修改步驟**：具體到哪個檔案、哪個函式、怎麼改
5. **評估複雜度**：拆解後的步驟能在 30 分鐘內完成嗎？
   - 能 → 分派
   - 不能 → 繼續拆更小

### Step 3: 分派給小茵

用 curl 建立卡片到小茵收件匣（不是移動原卡片）。

先查出小茵收件匣的 list_id：
```bash
YIN_LIST_ID=$(curl -s "http://127.0.0.1:8899/api/v1/projects/1/board" | \
  python3 -c "
import sys, json
board = json.loads(sys.stdin.read())
for stage in board:
    if '小茵' in stage.get('name', '') or 'xiao-yin' in str(stage.get('member_id', '')):
        print(stage['id'])
        break
")
```

建立規劃卡片並觸發：
```bash
CARD_RESP=$(curl -s -X POST "http://127.0.0.1:8899/api/v1/cards/" \
  -H "Content-Type: application/json" \
  -d "{
    \"title\": \"具體的修改描述\",
    \"list_id\": $YIN_LIST_ID,
    \"project_id\": 1,
    \"description\": \"## 任務來源\n原始卡片 #XXXX\n\n## 修改目標\n...\n\n## 具體步驟\n1. ...\n\n## 驗證方式\n- python import 通過\n- vue-tsc 通過\"
  }")

CARD_ID=$(echo $CARD_RESP | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('id',''))")
curl -s -X POST "http://127.0.0.1:8899/api/v1/cards/$CARD_ID/trigger"
echo "分派給小茵: #$CARD_ID"
```

然後將原始 Backlog 卡片標記 [reviewed]：
```bash
curl -s -X PATCH "http://127.0.0.1:8899/api/v1/cards/{card_id}" \
  -H "Content-Type: application/json" \
  -d '{"title": "[reviewed] 原標題"}'
```

### Step 4: 如果深入分析後發現不適合

標記 [reviewed] 並寫下**具體原因**（不能只寫「不適合」）：

```bash
curl -s -X PATCH "http://127.0.0.1:8899/api/v1/cards/{card_id}" \
  -H "Content-Type: application/json" \
  -d '{"title": "[reviewed] 原標題", "description": "審查結果: 暫不自動開發。\n原因: （具體說明為什麼不適合，以及建議的替代方案）\n影響分析: （你讀了什麼程式碼、發現了什麼）"}'
```

**標記後結束，不要再挑第二張。**

## 注意事項
- **一次只選 1 張、只規劃 1 張、只分派 1 張**
- **不要批量標記** — 只處理你選定的那 1 張
- 如果 Backlog 沒有卡片，直接結束
- 規劃要夠具體，讓小茵拿到就能直接開工
- 高風險 ≠ 不能做，拆小就能做
