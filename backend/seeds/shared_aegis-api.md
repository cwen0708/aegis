---
name: aegis-api
description: "Aegis 內部 API 工具。127.0.0.1 呼叫不需認證，用於查詢看板、建立卡片、觸發任務。"
---

# Aegis 內部 API 工具

透過 `http://127.0.0.1:8899/api/v1` 呼叫，127.0.0.1 來源不需認證。

## 查詢成員收件匣 list_id（不要寫死）

```bash
curl -s "http://127.0.0.1:8899/api/v1/projects/{project_id}/board" | \
  python3 -c "
import sys, json
board = json.loads(sys.stdin.read())
for stage in board:
    if '成員名字' in stage.get('name', ''):
        print(stage['id'])
"
```

## 建立卡片

```bash
curl -s -X POST "http://127.0.0.1:8899/api/v1/cards/" \
  -H "Content-Type: application/json" \
  -d '{"title": "...", "list_id": N, "project_id": 1, "description": "..."}'
```

## 觸發卡片

```bash
curl -s -X POST "http://127.0.0.1:8899/api/v1/cards/{card_id}/trigger"
```

## 更新卡片

```bash
curl -s -X PATCH "http://127.0.0.1:8899/api/v1/cards/{card_id}" \
  -H "Content-Type: application/json" \
  -d '{"title": "...", "description": "..."}'
```

## 注意

- list_id 要動態查詢，不要寫死
- 建立的卡片要 trigger 才會執行
- 不要自己觸發自己的卡片
