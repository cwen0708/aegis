---
description: 自我升級流程：Code Review 通過後部署到運行環境並重啟服務。小良在「審查中」階段時使用。
globs:
---

# 自我升級（Code Review + 部署）

小茵完成開發後建立審查卡片交給你。你必須：審查 → 部署 → 驗證。

## Step 1: 查看 Commit

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

如果有改前端：
```bash
cd ~/projects/Aegis/frontend
npx vue-tsc -b --force && pnpm build
```

## Step 3: 判斷

- **通過** → 繼續 Step 4
- **不通過且無 Retry tag** → 用 aegis-api 建退回卡片給小茵，並對原卡片加 Retry tag（`curl -s -X POST "http://127.0.0.1:8899/api/v1/cards/{card_id}/tags" -H "Content-Type: application/json" -d '{"tag_name":"Retry"}'`），結束
- **不通過且已有 Retry tag** → 對原卡片加 Blocked tag（`curl -s -X POST "http://127.0.0.1:8899/api/v1/cards/{card_id}/tags" -H "Content-Type: application/json" -d '{"tag_name":"Blocked"}'`），結束

## Step 4: 部署（必須執行，不可跳過）

**以下所有命令都必須實際執行，不是參考。**

先判斷改了什麼：
```bash
cd ~/projects/Aegis
CHANGED_FILES=$(git show HEAD --name-only --format="")
echo "Changed files: $CHANGED_FILES"
```

部署到運行環境：
```bash
DEVDIR=~/projects/Aegis
RUNTIME=~/.local/aegis

# 後端 app/ 目錄（幾乎每次都要）
if echo "$CHANGED_FILES" | grep -q "backend/app/"; then
  cp -r $DEVDIR/backend/app/ $RUNTIME/backend/app/
  echo "Deployed: backend/app/"
fi

# worker.py
if echo "$CHANGED_FILES" | grep -q "backend/worker.py"; then
  cp $DEVDIR/backend/worker.py $RUNTIME/backend/worker.py
  echo "Deployed: worker.py"
fi

# runner.py
if echo "$CHANGED_FILES" | grep -q "backend/runner.py"; then
  cp $DEVDIR/backend/runner.py $RUNTIME/backend/runner.py
  echo "Deployed: runner.py"
fi

# 前端
if echo "$CHANGED_FILES" | grep -q "frontend/"; then
  cd $DEVDIR/frontend
  cp -r dist/ $RUNTIME/frontend/dist/
  echo "Deployed: frontend/dist/"
fi
```

## Step 5: 重啟服務（必須執行）

```bash
# 判斷需要重啟什麼
NEED_AEGIS=false
NEED_WORKER=false

if echo "$CHANGED_FILES" | grep -qE "backend/app/|backend/runner.py|frontend/"; then
  NEED_AEGIS=true
fi
if echo "$CHANGED_FILES" | grep -q "backend/worker.py"; then
  NEED_WORKER=true
fi

# 執行重啟
if [ "$NEED_AEGIS" = true ]; then
  sudo systemctl restart aegis
  echo "Restarted: aegis"
fi
if [ "$NEED_WORKER" = true ]; then
  sudo systemctl restart aegis-worker
  echo "Restarted: aegis-worker"
fi

# 等待啟動
sleep 3
```

## Step 6: 驗證部署（必須執行）

```bash
systemctl status aegis --no-pager | head -3
systemctl status aegis-worker --no-pager | head -3
curl -s http://127.0.0.1:8899/api/v1/runner/status | head -1
echo "Deploy verified"
```

如果服務異常，立即還原：
```bash
cd ~/.local/aegis
git checkout -- backend/
sudo systemctl restart aegis
sudo systemctl restart aegis-worker
```

## 重要

- **Step 4、5、6 是必須執行的**，不是參考文件
- 不要 git push
- 不要改 .env 或 DB
- 退回上限 1 次，超過加 Blocked tag
- **卡片狀態只能用 `completed` 或 `failed`**，不要用 `done` 或其他自創狀態
