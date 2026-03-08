# API Endpoints

Base URL: `http://localhost:8899/api/v1`

## Projects

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/projects/` | List all projects |
| `POST` | `/projects/` | Create project |
| `PATCH` | `/projects/{id}` | Update project |
| `GET` | `/projects/{id}/board` | Full board (lists + cards) |

## Cards

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/cards/` | List all cards |
| `GET` | `/cards/{id}` | Get card detail |
| `POST` | `/cards/` | Create card |
| `PATCH` | `/cards/{id}` | Update card |
| `DELETE` | `/cards/{id}` | Delete card |
| `POST` | `/cards/{id}/trigger` | Manual trigger (→ pending) |
| `POST` | `/cards/{id}/abort` | Kill running task |

## Cron Jobs

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/cron-jobs/` | List cron jobs |
| `POST` | `/cron-jobs/` | Create cron job |
| `PATCH` | `/cron-jobs/{id}` | Toggle enable/disable |
| `DELETE` | `/cron-jobs/{id}` | Delete cron job |

## Runner

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/runner/pause` | Pause task poller |
| `POST` | `/runner/resume` | Resume task poller |
| `GET` | `/runner/status` | Runner state + slots |

## Members

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/members/` | List all members |
| `POST` | `/members/` | Create member |
| `PUT` | `/members/{id}` | Update member |
| `DELETE` | `/members/{id}` | Delete member |
| `GET` | `/members/{id}/history` | Get member task history |
| `POST` | `/members/{id}/portrait` | Upload portrait image |
| `POST` | `/members/{id}/generate-portrait` | AI generate portrait from photo |

## System

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/system/metrics` | Hardware metrics (CPU/RAM/Disk) |
| `GET` | `/claude/usage` | Claude account usage |
| `GET` | `/settings` | Get all settings (merged with defaults) |
| `PUT` | `/settings` | Batch update settings |
| `GET` | `/portraits/{filename}` | Get portrait image |

## WebSocket

| Method | Endpoint | Description |
|--------|----------|-------------|
| `WS` | `/ws` | WebSocket (real-time updates) |

See [websocket.md](websocket.md) for event details.
