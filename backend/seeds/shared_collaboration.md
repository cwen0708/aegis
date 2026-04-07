---
description: 跨成員協作：建立卡片到其他成員收件匣以請求協助。
globs:
alwaysApply: true
---

# 跨成員協作

當你遇到超出自身專長的問題時，可以請求其他團隊成員協助。

## 如何請求協助

使用 aegis-api 工具中的函式，建立卡片到對方的收件匣：

```bash
# 1. 查出對方的收件匣
TARGET_LIST=$(find_list_id 1 "對方名字")

# 2. 建卡片
RESP=$(create_card "協助: 簡述問題" $TARGET_LIST 1 "## 問題\n詳細描述\n\n## 已嘗試\n...\n\n## 需要協助\n...")

# 3. 觸發
CARD_ID=$(echo $RESP | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('id',''))")
trigger_card $CARD_ID
```

## 跨專案協作

如需建到其他專案，先查出目標專案的 board：

```bash
# 查出目標專案的 list_id
TARGET_LIST=$(find_list_id <其他專案ID> "成員名字")
create_card "協助: 問題描述" $TARGET_LIST <其他專案ID> "詳細描述"
```

## 注意事項

- 問題描述要具體：包含錯誤訊息、檔案路徑、已嘗試的方法
- 不要求助自己能解決的事情
- 一個求助卡片只處理一個問題
- 不要自己觸發自己的卡片（防無限迴圈）
