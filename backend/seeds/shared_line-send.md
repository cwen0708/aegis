---
description: LINE 群組訊息發送：將報告、通知等內容發送到 LINE 群組。
globs:
---

# LINE 群組訊息發送

當你需要將報告、通知、摘要等內容發送到 LINE 群組時，使用此技能。

## 查詢可用群組

```bash
curl -s "http://127.0.0.1:8899/api/v1/raw-messages/groups/" | python3 -c "
import sys, json
for g in json.load(sys.stdin):
    print(f'{g[\"group_name\"]}: {g[\"group_id\"]}')"
```

## 發送訊息

```bash
send_line_message() {
  local GROUP_ID=$1
  local MESSAGE=$2

  # 透過 Aegis API 讀取 LINE access token
  local LINE_TOKEN=$(curl -s "http://127.0.0.1:8899/api/v1/channels" | \
    python3 -c "import sys,json; print(json.load(sys.stdin)['line']['access_token'])")

  if [ -z "$LINE_TOKEN" ]; then
    echo "[LINE] Error: access token not found"
    return 1
  fi

  # 呼叫 LINE Push API
  local RESPONSE=$(curl -s -X POST https://api.line.me/v2/bot/message/push \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $LINE_TOKEN" \
    -d "$(python3 -c "
import json, sys
msg = sys.argv[1]
if len(msg) > 4990:
    msg = msg[:4987] + '...'
print(json.dumps({
    'to': sys.argv[2],
    'messages': [{'type': 'text', 'text': msg}]
}))
" "$MESSAGE" "$GROUP_ID")")

  echo "[LINE] Send result: $RESPONSE"
}
```

### 使用範例

```bash
# 先查詢群組 ID
# curl -s "http://127.0.0.1:8899/api/v1/raw-messages/groups/" | ...

# 發送訊息到指定群組
send_line_message "<GROUP_ID>" "訊息內容"
```

## 注意事項

1. **免費額度**：LINE Push API 免費版每月 200 則，請勿頻繁發送
2. **純文字**：LINE 不支援 Markdown，請用純文字 + emoji 排版
3. **長度限制**：單則訊息上限 5000 字，超過會自動截斷
4. **不要用於閒聊**：僅用於報告、通知、警示等正式用途
