"""
Aegis API Routes — 主路由（向後相容）

所有 endpoints 已遷移至模組化路由：
- app/api/projects.py — 專案 + Stage Lists + 環境變數 + Remote Control
- app/api/cards.py — 卡片 CRUD + trigger/abort/archive
- app/api/cron_jobs.py — 排程 + TaskLog/CronLog
- app/api/members.py — 成員 + 帳號 + Skills + Portrait
- app/api/channels.py — 頻道設定
- app/api/invitations.py — 邀請碼 + Bot Users + TTS
- app/api/auth.py — 認證 + CLI 管理
- app/api/runner.py — Worker 控制 + Internal APIs
- app/api/system.py — 系統狀態 + Settings + Usage
- app/api/github.py — GitHub 整合
- app/api/onestack.py — OneStack Node API
- app/api/updater_routes.py — 系統更新
- app/api/messaging.py — Email + Domain + Room + RawMessage
- app/api/deps.py — 共用 helpers
- app/api/schemas.py — 共用 schemas
"""
from fastapi import APIRouter

router = APIRouter()
