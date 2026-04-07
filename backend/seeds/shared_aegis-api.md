---
description: Aegis 內部 API 工具：透過 127.0.0.1:8899 呼叫看板、卡片、成員等 API。
globs:
alwaysApply: true
---

# Aegis 內部 API 工具

你運行在 Aegis 伺服器上，可以透過 `http://127.0.0.1:8899/api/v1` 呼叫內部 API。
來自 127.0.0.1 的請求不需要認證。

## 查詢看板

```bash
# 取得專案看板（含所有 list 和卡片）
curl -s "http://127.0.0.1:8899/api/v1/projects/{project_id}/board"
```

回傳格式：每個 stage 有 `id`（list_id）、`name`、`member_id`、`cards`。

## 查詢成員的收件匣 list_id

每個部署環境的 list_id 不同，**不要寫死**。用以下方式動態查詢：

```bash
# 查詢指定成員的收件匣 list_id（用成員名稱搜尋）
find_list_id() {
  local PROJECT_ID=$1
  local MEMBER_NAME=$2
  curl -s "http://127.0.0.1:8899/api/v1/projects/$PROJECT_ID/board" | \
    python3 -c "
import sys, json
board = json.loads(sys.stdin.read())
for stage in board:
    if '$MEMBER_NAME' in stage.get('name', ''):
        print(stage['id'])
        break
"
}

# 範例
LIANG_LIST=$(find_list_id 1 "小良")
YIN_LIST=$(find_list_id 1 "小茵")
```

## 建立卡片

```bash
# 建立卡片到指定 list
create_card() {
  local TITLE=$1
  local LIST_ID=$2
  local PROJECT_ID=$3
  local DESC=$4
  curl -s -X POST "http://127.0.0.1:8899/api/v1/cards/" \
    -H "Content-Type: application/json" \
    -d "{
      \"title\": \"$TITLE\",
      \"list_id\": $LIST_ID,
      \"project_id\": $PROJECT_ID,
      \"description\": \"$DESC\"
    }"
}

# 範例：建卡片到小良收件匣
RESP=$(create_card "審查: 修正某功能" $LIANG_LIST 1 "請審查")
echo $RESP
```

## 觸發卡片

建立的卡片預設是 idle，需要 trigger 才會被 Worker 撿起：

```bash
# 觸發卡片
trigger_card() {
  local CARD_ID=$1
  curl -s -X POST "http://127.0.0.1:8899/api/v1/cards/$CARD_ID/trigger"
}

# 範例
CARD_ID=$(echo $RESP | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('id',''))")
trigger_card $CARD_ID
```

## 更新卡片

```bash
# 更新卡片標題或描述
curl -s -X PATCH "http://127.0.0.1:8899/api/v1/cards/{card_id}" \
  -H "Content-Type: application/json" \
  -d '{"title": "新標題", "description": "新描述"}'
```

## 查詢卡片

```bash
# 取得單張卡片
curl -s "http://127.0.0.1:8899/api/v1/cards/{card_id}"
```

## 服務狀態

```bash
# Worker 狀態
curl -s "http://127.0.0.1:8899/api/v1/runner/status"

# 系統健康
curl -s "http://127.0.0.1:8899/health"
```

## 組合範例：建卡片並派給成員

```bash
# 一步到位：查 list_id → 建卡 → 觸發
MEMBER_LIST=$(find_list_id 1 "小茵")
RESP=$(create_card "任務標題" $MEMBER_LIST 1 "任務描述")
CARD_ID=$(echo $RESP | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('id',''))")
trigger_card $CARD_ID
echo "派給小茵: #$CARD_ID"
```

## 注意事項

- 只有 `127.0.0.1` 來源的寫入請求不需認證
- project_id 和 list_id 要動態查詢，不要寫死
- 建立的卡片要 trigger 才會執行
- 不要自己觸發自己的卡片（防無限迴圈）
