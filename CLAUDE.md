# Aegis — Claude Code 專案指引

## 專案簡介
AI Engineering Grid & Intelligence System (Aegis)
- **Backend**: FastAPI + SQLModel + SQLite (`backend/`)
- **Frontend**: Vue 3 Composition API + Vite + Phaser 3 (`frontend/`)
- **卡片系統**: MD 檔案 (frontmatter) 為 source of truth，CardIndex 為查詢索引

## Git 遠端

| 名稱 | 用途 | URL |
|------|------|-----|
| `origin` | 私人遠端（完整版本） | `https://github.com/Yooliang/Aegis.git` |
| `public` | 開源遠端（公開版本） | `https://github.com/cwen0708/aegis.git` |

- 日常開發 push 到 `origin`
- 開源發布 push 到 `public`（注意不要推送 `private/` 目錄內容）

## 開發環境

### 啟動
- **開發**: `dev.bat` 或分別啟動 `backend/dev.py` + `npm run dev`
- **生產**: `start-aegis.bat`（自動 build frontend + 啟動兩個 server）

### 後端
```bash
cd backend
venv/Scripts/activate
python dev.py          # uvicorn + reload（排除 *.db）
python -c "from seed import seed_data; seed_data()"  # 重建種子資料
```

### 前端
```bash
cd frontend
npm run dev            # Vite dev server (port 5173)
npm run build          # Production build（跳過 type check）
```

## 重要約定

### Commit 格式
所有 commit 結尾加上：
```
Generated with [Claude Code](https://claude.ai/code)
via [Happy](https://happy.engineering)

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Happy <yesreply@happy.engineering>
```

### 語言
- UI 標籤與溝通使用**繁體中文**
- 程式碼註解可用中文或英文

### Windows 注意事項
- `asyncio.create_subprocess_exec` 在 uvicorn event loop 不支援 → 用 `subprocess.Popen` + `asyncio.to_thread`
- 子程序需移除 `CLAUDECODE` 環境變數：`env.pop("CLAUDECODE", None)`
- uvicorn `--reload` 會偵測 `*.db` 變更 → 用 `dev.py` 排除

### 敏感檔案（勿 commit）
- `private/` — 私人文件、備份
- `backend/local.db` — 本地資料庫
- `.env` / credentials — 憑證檔案
- `backend/uploads/` — 使用者上傳（example 立繪除外）
