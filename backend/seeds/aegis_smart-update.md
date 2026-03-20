# 智慧更新

當上游開源 repo 有新版本，且本地有自我進化的 commit 時，你負責合併兩者並部署。

## 觸發條件
自動更新腳本偵測到本地有未推送的進化 commit，會建立卡片交給你處理。
卡片描述中會列出上游新 commit 和本地進化 commit。

## 執行流程

### Step 1: 檢查狀態

```bash
cd ~/projects/Aegis

# 確認上游和本地的差異
git fetch origin
echo "=== 上游新 commit ==="
git log HEAD..origin/main --oneline
echo "=== 本地進化 commit ==="
git log origin/main..HEAD --oneline
```

### Step 2: 嘗試合併

```bash
cd ~/projects/Aegis
git merge origin/main
```

#### 2a. 無衝突 → 繼續 Step 3
#### 2b. 有衝突

查看衝突檔案：
```bash
git diff --name-only --diff-filter=U
```

嘗試解決：
- **簡單衝突**（格式、import 順序）：手動修正，`git add` + `git commit`
- **複雜衝突**（邏輯衝突、大幅重構）：`git merge --abort`，標記 [blocked]，等人工介入

### Step 3: 驗證

```bash
# 後端
cd ~/projects/Aegis/backend
python3 -c "from app.main import app; print('Import OK')"

# 前端（如果有前端變更）
cd ~/projects/Aegis/frontend
npx vue-tsc -b --force && pnpm build
```

驗證失敗 → `git merge --abort`，標記 [blocked]。

### Step 4: 部署到運行環境

```bash
DEVDIR=~/projects/Aegis
RUNTIME=~/.local/aegis

# 同步所有後端程式碼
cp -r $DEVDIR/backend/app/ $RUNTIME/backend/app/
cp $DEVDIR/backend/worker.py $RUNTIME/backend/worker.py
cp $DEVDIR/backend/runner.py $RUNTIME/backend/runner.py

# 如果有新的 requirements
cd $RUNTIME/backend && ./venv/bin/pip install -r requirements.txt -q

# 前端：從 GitHub Release 下載或本地 build
cd $DEVDIR/frontend
if [ -d dist ]; then
  cp -r dist/ $RUNTIME/frontend/dist/
fi

# 更新 VERSION
cd $RUNTIME
TAG=$(git -C $DEVDIR describe --tags --abbrev=0 2>/dev/null)
if [ -n "$TAG" ]; then
  echo "${TAG#v}" > backend/VERSION
fi
```

### Step 5: 重啟服務

```bash
sudo systemctl restart aegis-worker
sleep 1
sudo systemctl restart aegis
sleep 3

# 驗證
systemctl status aegis --no-pager | head -3
systemctl status aegis-worker --no-pager | head -3
curl -s http://127.0.0.1:8899/api/v1/runner/status | head -1
echo "Smart update deployed"
```

### Step 6: 回報

如果部署後服務異常，立即還原：
```bash
cd ~/.local/aegis
git checkout -- backend/
sudo systemctl restart aegis
sudo systemctl restart aegis-worker
```

## 重要限制

- **不要 git push** — 推送權在管理者
- **複雜衝突不要硬解** — 標記 [blocked] 等人工處理
- **部署後一定要驗證服務狀態**
- **還原要快** — 服務掛了就立即 git checkout 還原
