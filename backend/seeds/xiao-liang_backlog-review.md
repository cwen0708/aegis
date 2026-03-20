# Backlog 審查與任務分派

你負責定期審查 AEGIS 專案的 Backlog，挑選一張卡片進行深入規劃，然後分派到「開發中」列表。

**核心原則：一次只深入處理一張卡片。**

## 審查流程

### Step 1: 掃描標題（快速瀏覽，不深入閱讀）

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

選出 **1 張**最適合的。優先高效益，大任務拆小。

### Step 2: 深入規劃

1. 閱讀卡片完整描述和相關程式碼
2. 拆解成一個最小可執行的步驟（30 分鐘內能完成）
3. 列出具體修改步驟（哪個檔案、哪個函式、怎麼改）

### Step 3: 分派到「開發中」列表

查出「開發中」列表的 list_id，建立規劃卡片：

```bash
DEV_LIST=$(curl -s "http://127.0.0.1:8899/api/v1/projects/1/board" | python3 -c "
import sys, json
for s in json.loads(sys.stdin.read()):
    if s['name'] == '開發中':
        print(s['id']); break
")

CARD_RESP=$(curl -s -X POST "http://127.0.0.1:8899/api/v1/cards/" \
  -H "Content-Type: application/json" \
  -d "{
    \"title\": \"具體的修改描述\",
    \"list_id\": $DEV_LIST,
    \"project_id\": 1,
    \"description\": \"## 任務來源\n原始卡片 #XXXX\n\n## 修改步驟\n1. ...\n2. ...\n\n## 驗證方式\n- python import 通過\n- vue-tsc 通過（如適用）\"
  }")

CARD_ID=$(echo $CARD_RESP | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('id',''))")
curl -s -X POST "http://127.0.0.1:8899/api/v1/cards/$CARD_ID/trigger"
echo "分派到開發中: #$CARD_ID"
```

然後標記原 Backlog 卡片：
```bash
curl -s -X PATCH "http://127.0.0.1:8899/api/v1/cards/{原卡片id}" \
  -H "Content-Type: application/json" \
  -d '{"title": "[reviewed] 原標題"}'
```

### Step 4: 不適合的卡片

標記 [reviewed] + 寫具體原因。**標記後結束，不要再挑第二張。**

## 注意事項
- **一次只選 1 張、只規劃 1 張、只分派 1 張**
- 分派到「開發中」列表（不是小茵收件匣）
- 卡片完成後系統會自動流轉：開發中 → 審查中 → 完成
- 如果 Backlog 沒有合適的卡片，直接結束
