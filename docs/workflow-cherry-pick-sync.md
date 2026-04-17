# Dev → Main Cherry-Pick 同步工作流

> 建立日期：2026-04-17
> 狀態：SOP / 必讀
> 適用：管理 Aegis `dev` 和 `main` 分支同步的所有人（特別是小茵和開發者）

## 問題背景

Aegis 的開發流程是：

```
work on dev → cherry-pick 選擇性進 merge → merge 進 main → push main
```

**陷阱**：`git cherry-pick` 會建立**新 SHA**（因為有新的 parent）。導致：

- `git log dev..main` 或 `git log main..dev` 只比 SHA，**不比內容**
- dev 上已被 cherry-pick 過的 commits，SHA 看起來還在 dev 上獨有
- **誤判「dev 領先 N commits」實際上多數已經進 main**

### 實際受害案例

2026-04-17，重新檢查 Aegis dev 狀態時：

| 比對方式 | 結果 |
|---------|------|
| `git log aegis-dev/dev..HEAD` | 148 commits（假象）|
| `git log origin/main..HEAD` | 120 commits（SHA 比對）|
| `git cherry origin/main HEAD` | **119 commits 真未合併**（patch 比對）|

差 28 個 SHA 是 cherry-pick 造成的假差異。用 `git log` 基準就會重複 review、重複部署。

## 正確做法

### 1. 檢查「真正未合併」的 commits

用 `git cherry`（patch equivalence），**不要**用 `git log ..`（SHA equivalence）：

```bash
git fetch --all

# 列出 dev 上 patch 內容不在 main 的 commits
git cherry origin/main HEAD

# 輸出格式：
#   + <sha>   ← 真的沒合併（需 review / cherry-pick）
#   - <sha>   ← patch 已在 main（可跳過）
```

取出真正要審的清單：

```bash
git cherry origin/main HEAD | awk '$1=="+"{print $2}' > to_review.txt
wc -l to_review.txt
```

### 2. 替代指令

`git log --cherry-mark --left-right` 也可：

```bash
git log --cherry-mark --left-right origin/main...HEAD --oneline
# = 前綴    ：兩邊都有（同 patch）
# > 前綴    ：只在 dev
# < 前綴    ：只在 main
```

### 3. 長期解法：建立「已同步點」標記

每次完成 cherry-pick → main 的循環後，在 dev 打 tag 標記：

```bash
# 在 dev 分支打已同步 tag
git tag -f synced-main HEAD
git push aegis-dev synced-main --force

# 或用更精細的版本號
git tag -f synced-main-20260417 HEAD
```

下次 review 時，只看 `synced-main..HEAD`：

```bash
git log synced-main..HEAD --oneline
# = 真的是上次同步後到現在的新 commits
```

### 4. 更徹底：用 merge 代替 cherry-pick

如果能接受非線性歷史，`git merge` 會保留 SHA 追蹤：

```bash
git checkout main
git merge dev --no-ff -m "merge dev features"
```

優點：`git log main..dev` 永遠正確。
缺點：main 歷史會有 merge commits。

## SOP：每次 dev 推進 main 時

```bash
# 1. 檢查真正未合併
git fetch --all
git cherry origin/main HEAD | awk '$1=="+"' > /tmp/to_review.txt
echo "真正未合併：$(wc -l < /tmp/to_review.txt) commits"

# 2. Review（或 cherry-pick 到 merge 分支）
# ... 你的流程 ...

# 3. merge 到 main 完成後，標記同步點
git tag -f synced-main HEAD
git push aegis-dev synced-main --force
```

## 相關

- `golden-rules.md` — Aegis 編碼規範
- `runner-vs-worker.md` — ProcessPool 架構
- `CLAUDE.md`（小茵 self-dev skill） — 應加入此 SOP 到同步檢查步驟

## 作者

- 發現：小良哥（温啟良）2026-04-17
- 觸發事件：148 commits re-review 才發現 119 真未合併，28 是 cherry-pick 造成的假差異
