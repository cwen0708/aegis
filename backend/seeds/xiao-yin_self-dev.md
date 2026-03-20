# Aegis 自我開發技能

你具備分析和改善 Aegis 自身程式碼的能力。這是一個「自我進化」流程：你運行在 Aegis 上，同時也在改善 Aegis。

## 環境架構

**重要：CLAUDE.md 告訴你專案路徑（project_path），所有檔案操作一律用絕對路徑。**

你的修改會直接寫入開發目錄（因為你用絕對路徑操作），所以 git commit 也在開發目錄執行。

## ⚠️ 最重要的事

**你必須在完成開發後執行 git commit。沒有 commit 的改動會被清除。**
**你必須建立審查卡片給小良。沒有審查卡片的改動不會被部署。**

這兩步如果不做，你的工作就白費了。

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
git add <你改的檔案1>
git add <你改的檔案2>

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
- **禁止 git push** — commit 只留在本地分支，推送權在管理員

### Step 6: 建立審查卡片給小良（必須執行）

用 aegis-api 工具建立卡片：

```bash
# 1. 查小良的收件匣 list_id
LIANG_LIST=$(curl -s "http://127.0.0.1:8899/api/v1/projects/1/board" | python3 -c "
import sys, json
for s in json.loads(sys.stdin.read()):
    if '小良' in s.get('name',''):
        print(s['id']); break
")

# 2. 取得 commit 資訊
COMMIT_HASH=$(cd <project_path> && git log --oneline -1 | cut -d' ' -f1)
COMMIT_MSG=$(cd <project_path> && git log -1 --format=%s)

# 3. 建卡片
RESP=$(curl -s -X POST "http://127.0.0.1:8899/api/v1/cards/" \
  -H "Content-Type: application/json" \
  -d "{
    \"title\": \"審查: $COMMIT_MSG\",
    \"list_id\": $LIANG_LIST,
    \"project_id\": 1,
    \"description\": \"Commit: $COMMIT_HASH $COMMIT_MSG\"
  }")

# 4. 觸發卡片
CARD_ID=$(echo $RESP | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('id',''))")
curl -s -X POST "http://127.0.0.1:8899/api/v1/cards/$CARD_ID/trigger"
echo "審查卡片 #$CARD_ID 已建立"
```

## 重要限制

1. **不要自己部署** — 交給小良
2. **不要 git push**
3. **不要修改運行環境**（~/.local/aegis/）
4. **每次只改一件事**
5. **Step 5 和 Step 6 是必須的** — 沒有 commit = 白做，沒有審查卡片 = 不會部署
6. **卡片狀態只能用 completed 或 failed** — 不要用 done 或其他自創狀態
