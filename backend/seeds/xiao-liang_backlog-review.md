---
description: Backlog 審查與任務分派：掃描 Backlog 挑選一張卡片，深入規劃後分派到開發中列表。小良在「Backlog 審查」階段時使用。
globs:
---

# Backlog 審查與任務分派

你負責定期審查 AEGIS 專案的 Backlog，**挑選 1 張卡片**進行深入規劃，然後分派到「開發中」列表。

## ⛔ 嚴格限制

- **一次只處理 1 張卡片**，完成後立即結束。不要迴圈處理多張。
- **不要批量標記**。掃描列表只是為了「選出 1 張」，不是為了「處理全部」。
- 只有兩種結果：**派發到開發中**（加 Dispatched tag）或 **暫時跳過**（什麼都不做）。
- **禁止在同一次執行中處理第 2 張卡片。**

## 審查流程

### Step 1: 掃描待處理卡片（只看標題，不深入）

```bash
curl -s "http://127.0.0.1:8899/api/v1/projects/1/board" | python3 -c "
import sys, json
d = json.loads(sys.stdin.read())
for stage in d:
    if stage['name'] == 'Backlog':
        for c in stage.get('cards', []):
            tags = c.get('tags', [])
            if c['status'] == 'idle' and 'Dispatched' not in tags and 'Blocked' not in tags:
                print(f'#{c[\"id\"]} {c.get(\"title\", \"\")}')
"
```

從結果中選出 **1 張**最適合的。優先級：P0 > P1 > P2 > 其他。大任務拆小。

如果沒有合適的卡片，**直接結束，什麼都不做**。

### Step 2: 深入規劃（只針對選出的那 1 張）

1. 閱讀卡片完整描述和相關程式碼
2. 拆解成一個最小可執行的步驟（30 分鐘內能完成）
3. 列出具體修改步驟（哪個檔案、哪個函式、怎麼改）

### Step 3: 派發 + 標記（一個腳本，不可拆開）

⚠️ **必須用下面這個單一腳本完成所有操作**。不要分開執行。
將 `ORIG_ID`、`NEW_TITLE`、`DESCRIPTION` 三個變數替換為實際值後執行：

```bash
python3 -c "
import json, urllib.request

API = 'http://127.0.0.1:8899/api/v1'
ORIG_ID = 0        # ← 替換為原 Backlog 卡片 ID
NEW_TITLE = ''      # ← 替換為開發卡片標題（具體的修改描述）
DESCRIPTION = ''    # ← 替換為開發卡片描述（含修改步驟和驗證方式）

# 1) 查「開發中」list_id
board = json.loads(urllib.request.urlopen(f'{API}/projects/1/board').read())
dev_list = next(s['id'] for s in board if s['name'] == '開發中')

# 2) 建立開發卡片
data = json.dumps({'title': NEW_TITLE, 'list_id': dev_list, 'project_id': 1, 'description': DESCRIPTION}).encode()
req = urllib.request.Request(f'{API}/cards/', data=data, headers={'Content-Type': 'application/json'}, method='POST')
card = json.loads(urllib.request.urlopen(req).read())
card_id = card.get('card_id', card.get('id'))
print(f'Created dev card #{card_id}')

# 3) 觸發開發卡片
urllib.request.urlopen(urllib.request.Request(f'{API}/cards/{card_id}/trigger', method='POST'))
print(f'Triggered #{card_id}')

# 4) 加 Dispatched tag 到原卡片（建卡成功才會到這一行）
tag_data = json.dumps({'tag_name': 'Dispatched'}).encode()
urllib.request.urlopen(urllib.request.Request(f'{API}/cards/{ORIG_ID}/tags', data=tag_data, headers={'Content-Type': 'application/json'}, method='POST'))
print(f'Tagged #{ORIG_ID} as Dispatched')

print('Done.')
"
```

### Step 4: 結束

腳本執行完畢後**立即結束**。不要繼續處理下一張。

## Tag 說明
- `Dispatched` = 已派發到開發中，有對應的開發卡片
- `Blocked` = 被阻塞，需要等待其他工作完成
