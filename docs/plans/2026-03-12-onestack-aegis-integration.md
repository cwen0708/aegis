# OneStack ↔ Aegis 整合計畫

> 最後更新：2026-03-12

## 核心概念

- **OneStack**：雲端指揮中心（Vue 3 + Supabase）
- **Aegis**：本地/GCP 執行引擎（FastAPI + CLI 工具）
- **Supabase** 作為協調匯流排（不是資料源頭），兩邊各自保有自己的資料

## 現有基礎設施（全部 ✅）

| 組件 | 說明 |
|------|------|
| `cli_devices` 表 | Aegis 心跳註冊（每 60 秒），含 owner_id 綁定 |
| `cli_tasks` 表 | 任務佇列（OneStack 建立 → Aegis 輪詢），含 execute/analyze 類型 |
| `ai_suggestions` 表 | Aegis → OneStack 建議/結果，含 task_result 類型 |
| `aegisService.ts` | OneStack 前端：裝置管理 + 任務派發 + 結果查詢 + Realtime 訂閱 |
| `AegisDeviceSettings.vue` | 裝置綁定 UI（建立/刪除/Token 輪換/env 複製） |
| `AegisStatusWidget.vue` | Dashboard 狀態指示燈 + 最近任務列表 |
| `onestack_connector.py` | Aegis 端：心跳 + 任務輪詢 + 完成回報 + Email 摘要同步 |
| `worker.py` | Card 完成後呼叫 `report_task_completion()` |
| `create_card_from_onestack_task()` | 從 cli_task 建立 Aegis Card（含 onestack_task_id 標記） |
| 3 個 Supabase RPCs | `create_user_device`, `delete_user_device`, `rotate_device_token` |
| RLS policies | 用戶看自己裝置/任務，裝置用 token 認證讀寫 |
| CI/CD pipeline | GitHub Actions → Build → Tag → Release → Hot Update（非阻塞） |

---

## Phase 1：任務派發 MVP — ✅ 完成（2026-03-12）

**所有程式碼已到位，migrations 已 applied。**

### 資料流
```
OneStack → cli_tasks → Aegis 輪詢拾取
                         ↓
                   建立 Card → Worker 執行
                         ↓
              cli_tasks.status='completed'
              + ai_suggestions type='task_result'
                         ↓
              OneStack 顯示結果
```

### 關鍵檔案
- `OneStack/src/services/aegisService.ts`（350 行）
- `OneStack/src/components/AegisDeviceSettings.vue`（293 行）
- `OneStack/src/components/AegisStatusWidget.vue`（151 行）
- `OneStack/supabase/migrations/20260312*.sql` + `20260313*.sql`（5 個 migration）
- `Aegis/backend/app/core/onestack_connector.py`（756 行）
- `Aegis/backend/worker.py`（1062 行，line 1007-1020 回報邏輯）
- `Aegis/backend/app/api/routes.py`（line 2670+ create_card_from_onestack_task）

### 待驗證（端對端測試）
1. OneStack Dashboard 顯示 Aegis 在線（綠燈）
2. 手動建立 cli_task → Aegis 自動拾取並建 Card
3. Card 執行完成 → cli_tasks.status 更新為 completed
4. OneStack 看到 task_result 類型的 ai_suggestion

---

## Phase 2：專案繫結 — 🔲 待開發

**目標**：OneStack 專案 1:1 繫結到 Aegis 專案，任務自動路由到對應看板。

### 2.1 Supabase Migration — `project_bindings` 表

```sql
CREATE TABLE project_bindings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  onestack_project_id UUID NOT NULL REFERENCES projects(id),
  device_id UUID NOT NULL REFERENCES cli_devices(id),
  aegis_project_id INT NOT NULL,
  aegis_project_name TEXT NOT NULL,
  sync_enabled BOOLEAN DEFAULT true,
  last_synced_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(onestack_project_id, device_id)
);

-- RLS: 用戶只看自己的繫結
CREATE POLICY "Users manage own bindings"
  ON project_bindings FOR ALL TO authenticated
  USING (device_id IN (SELECT id FROM cli_devices WHERE owner_id = auth.uid()));
```

### 2.2 Aegis API — 繫結端點

**新增** `POST /api/v1/node/bind-project`

```python
class BindProjectPayload(BaseModel):
    onestack_project_id: str
    aegis_project_id: Optional[int] = None  # None = 自動建立新專案

# 回傳 { aegis_project_id, aegis_project_name, stages: [...] }
```

**新增** `GET /api/v1/node/projects` — 回傳可用專案清單（供 OneStack 前端選擇）

### 2.3 OneStack aegisService.ts — 新增方法

```typescript
// 專案繫結
getProjectBindings(projectId?: string): Promise<ProjectBinding[]>
bindProject(params: { onestackProjectId: string, deviceId: string, aegisProjectId?: number }): Promise<ProjectBinding>
unbindProject(bindingId: string): Promise<void>
getAvailableAegisProjects(deviceId: string): Promise<AegisProject[]>
```

### 2.4 OneStack UI — 專案設定面板

**修改** `ProjectDetailView.vue`（或新增 `ProjectAegisBinding.vue` 元件）

- 「Aegis 整合」設定區塊（在專案詳情頁的設定 tab）
- 下拉選 Aegis 專案（從 `/node/projects` 取得清單）
- 繫結/解除繫結按鈕
- 顯示繫結後的 Aegis 看板狀態（卡片數、進行中數量）

### 2.5 任務派發增強

繫結後，`dispatchTask()` 自動帶入 `project_name`：
- 查 `project_bindings` 找到 `aegis_project_name`
- Aegis 收到任務時直接路由到對應專案看板

### 2.6 雙向同步規則

| 資料 | 源頭 | 方向 |
|------|------|------|
| 任務建立 | OneStack | → Aegis（透過 cli_tasks） |
| 任務執行 | Aegis | 僅 Aegis（CLI 工具） |
| 執行結果 | Aegis | → OneStack（透過 ai_suggestions） |
| 任務元資料（標題、描述） | OneStack | → Aegis |
| 專案狀態/進度 | Aegis | → OneStack（定期同步） |

### 2.7 檔案清單

| 動作 | 檔案 | 變更 |
|------|------|------|
| 新增 | `OneStack/supabase/migrations/YYYYMMDD_project_bindings.sql` | project_bindings 表 + RLS |
| 修改 | `OneStack/src/services/aegisService.ts` | +4 方法（繫結 CRUD） |
| 新增 | `OneStack/src/components/ProjectAegisBinding.vue` | 繫結 UI 元件 |
| 修改 | `OneStack/src/views/ProjectDetailView.vue` | 加入 Aegis 整合區塊 |
| 新增 | `Aegis/backend/app/api/routes.py` | `POST /node/bind-project` + `GET /node/projects` |
| 修改 | `Aegis/backend/app/core/onestack_connector.py` | 繫結驗證 + 任務路由 |

### 2.8 驗證步驟

1. 繫結 OneStack 專案 → Aegis 專案
2. OneStack 建立任務 → 自動出現在 Aegis 對應看板
3. Aegis 完成任務 → OneStack 任務狀態更新
4. 解除繫結 → 任務不再路由

---

## Phase 3：AI 代理橋接 — 🔲 待開發

**目標**：OneStack AI 代理的「建議行動」可以一鍵派發到 Aegis 執行。

### 3.1 代理 → Aegis 成員映射

| OneStack 代理 | Aegis 成員 | 用途 |
|--------------|-----------|------|
| 小陳（PM）| 任意 Planning 成員 | 任務拆解、排程規劃 |
| 阿凱（Tech Lead）| xiao-jun | 程式碼審查、架構分析 |
| 小蓁（Finance）| Gemini 成員 | 發票分析、預算報告 |
| 小雯（Marketing）| Gemini 成員 | 內容生成、案例撰寫 |
| 記憶大腦 | 系統 CronJob | 知識庫同步 |

### 3.2 Supabase — 代理映射表

```sql
CREATE TABLE agent_member_mappings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES auth.users(id),
  agent_slug TEXT NOT NULL,        -- 'pm', 'tech', 'finance', 'marketing', 'memory'
  member_slug TEXT NOT NULL,       -- Aegis member slug
  device_id UUID REFERENCES cli_devices(id),
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(owner_id, agent_slug)
);
```

### 3.3 智慧派發流程

當 OneStack 代理產生 `PMAgentAction`（status=approved）時：

1. 用戶在 OneStack 前端點「執行」
2. 查 `agent_member_mappings` 找到對應 Aegis 成員
3. 呼叫 `aegisService.dispatchTask()` 帶入 `member_slug`
4. Aegis 接收 → 建立 Card → 指定成員執行
5. 結果回傳 → OneStack 更新 action status=executed
6. UI 顯示執行結果摘要

### 3.4 OneStack aegisService.ts — 新增方法

```typescript
// 代理橋接
getAgentMappings(): Promise<AgentMemberMapping[]>
setAgentMapping(agentSlug: string, memberSlug: string, deviceId: string): Promise<void>
dispatchAgentAction(params: {
  actionId: string,
  agentSlug: string,
  title: string,
  description: string,
  projectId?: string
}): Promise<string>  // 回傳 task_id
```

### 3.5 OneStack UI — 代理設定 + 執行按鈕

**新增** `AgentAegisMappings.vue`（Settings 頁或 Aegis 設定 tab）
- 每個代理對應一個 Aegis 成員的下拉選單
- 成員清單從 Aegis `/node/info` 取得

**修改** AI 代理建議卡片 UI
- 新增「派發到 Aegis」按鈕（當 action status=approved）
- 點擊後顯示執行進度
- 完成後顯示結果摘要

### 3.6 健康報告 CronJob

Aegis 新增 CronJob，定期對繫結專案：
- 統計卡片狀態（pending/running/done/failed）、完成率
- 推送 `ai_suggestions` type=insight 到 OneStack
- OneStack Dashboard 自動顯示健康指標

### 3.7 檔案清單

| 動作 | 檔案 | 變更 |
|------|------|------|
| 新增 | `OneStack/supabase/migrations/YYYYMMDD_agent_member_mappings.sql` | 映射表 + RLS |
| 修改 | `OneStack/src/services/aegisService.ts` | +3 方法（映射 CRUD + 派發） |
| 新增 | `OneStack/src/components/AgentAegisMappings.vue` | 代理映射設定 UI |
| 修改 | OneStack AI 代理建議 UI | 加「派發到 Aegis」按鈕 |
| 修改 | `Aegis/backend/app/core/onestack_connector.py` | 健康報告 CronJob |

### 3.8 驗證步驟

1. 設定小陳 PM → Aegis planning 成員的映射
2. 小陳建議「建立任務」→ 用戶核准 → 點「派發到 Aegis」
3. Aegis 自動建立 Card → 指定成員執行
4. 結果回傳 → OneStack 更新 action status=executed
5. 阿凱建議「修改程式碼」→ 用戶核准 → Claude CLI 執行 → 結果回傳
6. Dashboard 顯示健康報告

---

## Aegis CI/CD（2026-03-12 修復完成）

- GitHub Actions：Test → Build Frontend → Tag → Release（含 dist tarball）→ Hot Update
- `/update/apply` 非阻塞（`asyncio.create_task`），秒回
- `new_bare` 版本號 bug 已修（PATCH → NEXT_PATCH）
- 最新版：`v0.2.2-dev.9`，GCP 部署正常
