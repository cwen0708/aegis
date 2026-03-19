---
name: smart-update
description: "智慧更新。當本地有進化 commit 且上游有新版本時，合併兩者並部署。"
---

# 智慧更新

上游開源 repo 有新版本，且本地有自我進化的 commit。
你負責合併兩者並部署到運行環境。

## 流程

1. `cd ~/projects/Aegis && git fetch origin`
2. 查看上游和本地差異：`git log HEAD..origin/main --oneline`
3. `git merge origin/main`
4. 無衝突 → 驗證（import check、vue-tsc）→ 部署
5. 簡單衝突 → 手動解決 → 驗證 → 部署
6. 複雜衝突 → `git merge --abort`，標記 [blocked]

## 部署

```bash
DEVDIR=~/projects/Aegis
RUNTIME=~/.local/aegis
cp -r $DEVDIR/backend/app/ $RUNTIME/backend/app/
cp $DEVDIR/backend/worker.py $RUNTIME/backend/worker.py
cp $DEVDIR/backend/runner.py $RUNTIME/backend/runner.py
cd $RUNTIME/backend && ./venv/bin/pip install -r requirements.txt -q
sudo systemctl restart aegis-worker && sleep 1
sudo systemctl restart aegis && sleep 3
systemctl status aegis --no-pager | head -3
```

## 限制

- 不要 git push
- 複雜衝突不要硬解，標記 [blocked]
- 部署後異常立即 `git checkout -- backend/` 還原
