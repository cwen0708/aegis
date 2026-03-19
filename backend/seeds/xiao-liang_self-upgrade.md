---
name: self-upgrade
description: "自我升級。審查小茵的開發成果，通過後部署到運行環境。"
---

# 自我升級（Code Review + 部署）

小茵完成開發後建立審查卡片交給你。你必須：審查 → 部署 → 驗證。

## Step 1: 查看改動

```bash
cd ~/projects/Aegis
git log --oneline -3
git show HEAD --stat
git show HEAD
```

## Step 2: 品質檢查

```bash
cd ~/projects/Aegis/backend
python3 -c "from app.main import app; print('Import OK')"
```

## Step 3: 判斷

- 通過 → Step 4
- 不通過且無 [retry:1] → 退回小茵，標 [retry:1]
- 不通過且有 [retry:1] → 標 [blocked]，結束

## Step 4: 部署（必須執行，不可跳過）

```bash
cd ~/projects/Aegis
CHANGED_FILES=$(git show HEAD --name-only --format='')
DEVDIR=~/projects/Aegis
RUNTIME=~/.local/aegis

if echo "$CHANGED_FILES" | grep -q "backend/app/"; then
  cp -r $DEVDIR/backend/app/ $RUNTIME/backend/app/
fi
if echo "$CHANGED_FILES" | grep -q "backend/worker.py"; then
  cp $DEVDIR/backend/worker.py $RUNTIME/backend/worker.py
fi
if echo "$CHANGED_FILES" | grep -q "backend/runner.py"; then
  cp $DEVDIR/backend/runner.py $RUNTIME/backend/runner.py
fi
if echo "$CHANGED_FILES" | grep -q "frontend/"; then
  cp -r $DEVDIR/frontend/dist/ $RUNTIME/frontend/dist/
fi
```

## Step 5: 重啟（必須執行）

```bash
sudo systemctl restart aegis
sudo systemctl restart aegis-worker
sleep 3
systemctl status aegis --no-pager | head -3
curl -s http://127.0.0.1:8899/api/v1/runner/status | head -1
```

## 限制

- Step 4、5 是必須執行的，不是參考
- 不要 git push
- 不要改 .env 或 DB
- 退回上限 1 次
- **卡片狀態只能用 `completed` 或 `failed`**，不要用 `done` 或其他自創狀態
- 部署後異常：`cd ~/.local/aegis && git checkout -- backend/ && sudo systemctl restart aegis`
