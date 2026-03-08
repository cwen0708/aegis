# Aegis Code Review Report — 2026-03-08

## Overview

| Severity | Backend | Frontend | Total |
|----------|---------|----------|-------|
| Critical | 3 | 3 | **6** |
| Important | 7 | 7 | **14** |
| Minor | 4 | 6 | **10** |
| Info | 3 | 4 | **7** |

---

## Critical

### B-C1: Gemini CLI hardcoded absolute path
**File:** `backend/app/core/runner.py:44`

```python
"cmd_base": [r"C:\Users\cwen0708\AppData\Roaming\npm\gemini.cmd"],
```

Hardcoded user-specific path. All Gemini tasks fail for any other user. Should use `["gemini"]` and rely on PATH.

### B-C2: Path traversal in portrait endpoint
**File:** `backend/app/api/routes.py:1136-1146`

```python
filepath = UPLOAD_DIR / filename  # filename not validated
```

Attacker can send `../../../etc/passwd`. Fix: add `filepath.resolve().is_relative_to(UPLOAD_DIR.resolve())` check.

### B-C3: Semaphore replacement race condition
**File:** `backend/app/core/runner.py:14,17-24`

`update_max_workstations` replaces the global `workstation_semaphore` object. Coroutines holding references to the old semaphore bypass concurrency limits.

### F-C1: Toast directly mutates Pinia store state
**File:** `frontend/src/components/ToastNotification.vue:8`

```ts
store.toasts = store.toasts.filter(t => t.id !== id)
```

Bypasses encapsulation. Race condition with `addToast`'s `setTimeout`. Should add `removeToast()` action to store.

### F-C2: App.vue setInterval never cleared
**File:** `frontend/src/App.vue:62`

```ts
setInterval(fetchProjects, 30000)  // no clearInterval, no saved reference
```

Memory leak on HMR hot reload. Store return value and clear in `onUnmounted`.

### F-C3: Kanban delete logic bug — null comparison
**File:** `frontend/src/views/Kanban.vue:197-210`

```ts
deleteTargetCardId.value = null          // (A) cleared first
if (selectedCard.value?.id === deleteTargetCardId.value) {  // (B) always null
```

Card detail modal never closes after deletion. Fix: save targetId before clearing.

---

## Important

### Backend

| # | Issue | File | Description |
|---|-------|------|-------------|
| B-I1 | Full table scan for max ID | `routes.py:235-238` | Loads all Cards to find max ID. Use `select(func.max(Card.id))` |
| B-I2 | `_internal_writes` not cleaned on failure | `card_file.py:13-27` | If `write_card` throws after `mark_internal_write`, path stays in set forever |
| B-I3 | Poller marks running before busy check | `poller.py:50-116` | pending->running->pending rollback causes unnecessary state churn |
| B-I4 | No file size limit on upload | `routes.py:1101-1133` | `await file.read()` loads entire file to memory. Add 10MB limit |
| B-I5 | `task_stats` full table scan | `routes.py:1041` | Loads all TaskLog rows in Python. Use SQL aggregation |
| B-I6 | `datetime.utcnow` deprecated + mixed | `models/core.py:23` | Mix of naive and aware datetimes. Standardize to `datetime.now(timezone.utc)` |
| B-I7 | `max_workstations` not validated | `routes.py:807-809` | `int("abc")` raises unhandled ValueError. No allowlist for settings keys |

### Frontend

| # | Issue | File | Description |
|---|-------|------|-------------|
| F-I1 | Bare `fetch` without `res.ok` check | Multiple views | Error responses assigned directly to refs, crashes UI |
| F-I2 | WebSocket module-level singleton | `useWebSocket.ts:3-6` | HMR reload creates ghost connections, breaks refCount |
| F-I3 | `setTimeout(100)` for Phaser init | `Office.vue:335-355` | Magic delay instead of proper scene ready events |
| F-I4 | `children.getAll().forEach(destroy)` | `OfficeScene.ts:113` | May destroy system objects. Use explicit layer/group |
| F-I5 | Win32 native packages in dependencies | `package.json:14-16` | Should be `optionalDependencies` for cross-platform |
| F-I6 | Production `console.log` | `OfficeScene.ts:465`, `Office.vue:315` | Debug logs pollute console |
| F-I7 | Native `confirm()` dialogs | `Agents.vue:114,215`, `Team.vue:216` | Should use existing `ConfirmDialog.vue` component |

---

## Minor

### Backend

| # | Issue | File |
|---|-------|------|
| B-M1 | WebSocket zombie clients on broadcast | `main.py:256-264` |
| B-M2 | `tmp.replace()` may fail on Windows if file locked | `card_file.py:75` |
| B-M3 | `create_member` never generates slug | `routes.py:942-948` |
| B-M4 | `_services_cache` not thread-safe | `routes.py:622-748` |

### Frontend

| # | Issue | File |
|---|-------|------|
| F-M1 | `ref<any[]>` type annotations | `App.vue:41` and multiple views |
| F-M2 | Async click handler not awaited in template | `Kanban.vue:503-504` |
| F-M3 | Two separate `onMounted` in App.vue | `App.vue:36-38, 52-63` |
| F-M4 | `fetchProjects` missing error handling | `CronJobs.vue:59-62` |
| F-M5 | Duplicate `.custom-scrollbar` CSS | `Kanban.vue`, `App.vue`, `TerminalViewer.vue`, `CronJobs.vue` |
| F-M6 | `intervalId: number` type incorrect | `Dashboard.vue:9` |

---

## Info / Observations

### Architecture
- `routes.py` exceeds 1400 lines — should split by domain (projects, cards, members)
- `frontend/dist/` committed to git — build artifacts should be gitignored
- No CI/CD (no GitHub Actions, no pre-commit hooks)
- Duplicate `get_card_lock` in `routes.py` and `poller.py` with separate `_card_locks` dicts — locks don't actually protect anything

### Dead Code / Incomplete
- `git_safety.py` — fully implemented but never imported or called anywhere
- `task_log` WebSocket event — documented and handled in frontend, but runner never broadcasts it
- `gemini_usage.py:58` — `datetime.fromisoformat()` without importing `datetime` (NameError)
- `select_best_account` — complete logic but runner uses hardcoded paths instead
- `HelloWorld.vue` — Vite template remnant, unused

### Dependencies
- `python-jose` has known CVE-2024-33663, and JWT auth is not used in this project
- `passlib[bcrypt]` unused (no auth feature)
- `pytest`/`pytest-asyncio` in production requirements (should be dev-only)
- `vuedraggable` and `@dnd-kit/vue` both installed (duplicate drag-and-drop libs)

### Test Coverage
- Core data layer (card/index/watcher/memory): ~57 tests, good coverage
- API endpoints (routes.py): **zero tests**
- Business logic (poller/runner): **zero tests**
- Frontend: **zero tests** (no Vitest/Cypress)
