# Aegis 自我開發技能

你具備分析和改善 Aegis 自身程式碼的能力。這是一個「自我進化」流程：你運行在 Aegis 上，同時也在改善 Aegis。

## 環境架構

**重要：CLAUDE.md 告訴你專案路徑（project_path），所有檔案操作一律用絕對路徑。**

你的修改會直接寫入開發目錄（因為你用絕對路徑操作），所以 git commit 也在開發目錄執行。

## ⚠️ 最重要的事

**你必須在完成開發後執行 git commit。沒有 commit 的改動會被清除。**

## 開發流程

### Step 1: 理解任務
閱讀卡片中的規劃，確認要改什麼。

### Step 2: 閱讀現有程式碼
用 CLAUDE.md 中給出的 project_path 絕對路徑讀取：
```bash
cat <project_path>/backend/app/api/routes.py | head -50
```

### Step 3: 修改程式碼
用絕對路徑修改檔案。原則：
- 每次只改一件事
- 不要順手改不相關的程式碼
- 繁體中文註解

### Step 4: 驗證
```bash
cd <project_path>/backend && python3 -c "from app.main import app; print('OK')"

# 前端（如有改前端）
cd <project_path>/frontend && npx vue-tsc -b --force && pnpm build
```

**驗證必須全部通過才能進入 Step 5。**

### Step 5: Git Commit（必須執行，不可跳過）

```bash
cd <project_path>

# 1. 確認改動
git diff --stat

# 2. 逐一加入你改的檔案（不要 git add .）
git add <你改的檔案>

# 3. 也加入新建的檔案
git add <新建的檔案>

# 4. Commit
git commit -m "fix: 簡述改動"

# 5. 驗證 commit 成功（必須看到 commit hash）
git log --oneline -1
```

**如果 git log 沒有顯示你的 commit，代表 commit 失敗，請排查原因。**

**Commit 規範：**
- 前綴：`feat:` / `fix:` / `refactor:` / `perf:`
- 繁體中文訊息
- 不要 commit .env、*.db、node_modules
- 不要 git push — commit 留在本地，推送權在管理員

## Commit 後

Commit 完成後，你的任務就結束了。系統會自動將卡片移到「審查中」列表，由小良進行 Code Review 和部署。**你不需要手動建審查卡片。**

## 重要限制

1. **不要自己部署** — 交給小良
2. **不要 git push** — commit 留在本地，推送權在管理員
3. **不要修改運行環境**（~/.local/aegis/）
4. **每次只改一件事**
5. **驗證全部通過才 commit**
6. **一定要 git commit** — 沒有 commit = 白做
7. **卡片狀態只能用 completed 或 failed**
