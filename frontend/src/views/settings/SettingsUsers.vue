<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  Plus, Copy, Trash2, Loader2, Clock, Users, Eye, PenTool, Play, Shield,
  UserCheck, Edit3, X,
} from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { config } from '../../config'
import { authHeaders } from '../../utils/authFetch'

const store = useAegisStore()
const API = config.apiUrl

// ─── Types ──────────────────────────────────────────────

interface ProjectOption {
  id: number
  name: string
}

interface MemberOption {
  id: number
  name: string
  avatar: string
}

interface Invitation {
  id: number
  code: string
  target_level: number
  target_member_id: number | null
  allowed_projects: number[] | null
  user_display_name: string
  user_description: string
  default_can_view: boolean
  default_can_create_card: boolean
  default_can_run_task: boolean
  default_can_access_sensitive: boolean
  max_uses: number
  used_count: number
  expires_at: string | null
  created_at: string
  note: string
  status: 'active' | 'expired' | 'depleted'
}

interface BotUserInfo {
  id: number
  platform: string
  platform_user_id: string
  username: string | null
  level: number
  is_active: boolean
  default_member_id: number | null
  default_member_name: string | null
  access_expires_at: string | null
  created_at: string
  last_active_at: string | null
  projects: { id: number; project_id: number; display_name: string; can_view: boolean; can_create_card: boolean; can_run_task: boolean }[]
}

// ─── Bot Users ──────────────────────────────────────────

const usersLoading = ref(true)
const botUsers = ref<BotUserInfo[]>([])

const showEditUser = ref(false)
const editUser = ref<BotUserInfo | null>(null)
const editUserForm = ref({
  level: 0,
  is_active: true,
  access_expires_at: '',
})
const savingUser = ref(false)

const confirmDeleteUser = ref(false)
const deleteUserTarget = ref<BotUserInfo | null>(null)

async function fetchUsers() {
  usersLoading.value = true
  try {
    const res = await fetch(`${API}/api/v1/bot-users`, { headers: authHeaders() })
    if (res.ok) botUsers.value = await res.json()
  } catch {
    store.addToast('載入用戶失敗', 'error')
  }
  usersLoading.value = false
}

function userLevelLabel(level: number): string {
  const labels: Record<number, string> = { 0: '未驗證', 1: '訪客', 2: '成員', 3: '管理員' }
  return labels[level] || `L${level}`
}

function userLevelColor(level: number): string {
  const colors: Record<number, string> = {
    0: 'text-slate-500 bg-slate-500/10 border-slate-500/30',
    1: 'text-sky-400 bg-sky-500/10 border-sky-500/30',
    2: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
    3: 'text-amber-400 bg-amber-500/10 border-amber-500/30',
  }
  return colors[level] ?? colors[0] ?? ''
}

function isUserExpired(u: BotUserInfo): boolean {
  if (!u.access_expires_at) return false
  return new Date(u.access_expires_at) <= new Date()
}

function openEditUser(u: BotUserInfo) {
  editUser.value = u
  editUserForm.value = {
    level: u.level,
    is_active: u.is_active,
    access_expires_at: u.access_expires_at ? u.access_expires_at.split('T')[0] ?? '' : '',
  }
  showEditUser.value = true
}

async function saveEditUser() {
  if (!editUser.value) return
  savingUser.value = true
  try {
    const body: Record<string, unknown> = {
      level: editUserForm.value.level,
      is_active: editUserForm.value.is_active,
    }
    body.access_expires_at = editUserForm.value.access_expires_at
      ? new Date(editUserForm.value.access_expires_at).toISOString()
      : ''
    const res = await fetch(`${API}/api/v1/bot-users/${editUser.value.id}`, {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    })
    if (!res.ok) throw new Error('更新失敗')
    showEditUser.value = false
    await fetchUsers()
    store.addToast('用戶已更新', 'success')
  } catch (e: any) {
    store.addToast(e.message || '更新失敗', 'error')
  }
  savingUser.value = false
}

async function doDeleteUser() {
  if (!deleteUserTarget.value) return
  try {
    const res = await fetch(`${API}/api/v1/bot-users/${deleteUserTarget.value.id}`, {
      method: 'DELETE',
      headers: authHeaders(),
    })
    if (!res.ok) throw new Error('刪除失敗')
    await fetchUsers()
    store.addToast('用戶已刪除', 'success')
  } catch {
    store.addToast('刪除失敗', 'error')
  }
}

// ─── Invitations ────────────────────────────────────────

const invLoading = ref(true)
const invitations = ref<Invitation[]>([])
const projects = ref<ProjectOption[]>([])
const members = ref<MemberOption[]>([])

const showInvDialog = ref(false)
const editingInvitation = ref<Invitation | null>(null)
const invForm = ref({
  code: '',
  target_level: 1,
  target_member_id: null as number | null,
  allowed_projects: [] as number[],
  user_display_name: '',
  user_description: '',
  default_can_view: true,
  default_can_create_card: false,
  default_can_run_task: false,
  default_can_access_sensitive: false,
  max_uses: 1,
  expires_days: null as number | null,
  access_valid_days: null as number | null,
  note: '',
})
const savingInv = ref(false)

const confirmDeleteInv = ref(false)
const deleteInvTarget = ref<Invitation | null>(null)

const permissionTemplates = [
  { name: '訪客', can_view: true, can_create_card: false, can_run_task: false, can_access_sensitive: false },
  { name: '成員', can_view: true, can_create_card: true, can_run_task: true, can_access_sensitive: false },
  { name: '管理員', can_view: true, can_create_card: true, can_run_task: true, can_access_sensitive: true },
]

const currentTemplate = computed(() => {
  const t = permissionTemplates.find(t =>
    t.can_view === invForm.value.default_can_view &&
    t.can_create_card === invForm.value.default_can_create_card &&
    t.can_run_task === invForm.value.default_can_run_task &&
    t.can_access_sensitive === invForm.value.default_can_access_sensitive
  )
  return t?.name || '自訂'
})

function applyTemplate(template: typeof permissionTemplates[0]) {
  invForm.value.default_can_view = template.can_view
  invForm.value.default_can_create_card = template.can_create_card
  invForm.value.default_can_run_task = template.can_run_task
  invForm.value.default_can_access_sensitive = template.can_access_sensitive
}

async function fetchInvitations() {
  invLoading.value = true
  try {
    const res = await fetch(`${API}/api/v1/invitations`)
    if (!res.ok) throw new Error('載入失敗')
    invitations.value = await res.json()
  } catch (e: any) {
    store.addToast(e.message || '邀請碼載入失敗', 'error')
  }
  invLoading.value = false
}

async function fetchProjects() {
  try {
    const res = await fetch(`${API}/api/v1/projects/?all=true`)
    if (res.ok) {
      const data = await res.json()
      projects.value = data.map((p: any) => ({ id: p.id, name: p.name }))
    }
  } catch {}
}

async function fetchMembers() {
  try {
    const res = await fetch(`${API}/api/v1/members?all=true`)
    if (res.ok) members.value = await res.json()
  } catch {}
}

function openInvDialog(invitation?: Invitation) {
  if (invitation) {
    editingInvitation.value = invitation
    invForm.value = {
      code: invitation.code,
      target_level: invitation.target_level,
      target_member_id: invitation.target_member_id,
      allowed_projects: invitation.allowed_projects || [],
      user_display_name: invitation.user_display_name,
      user_description: invitation.user_description,
      default_can_view: invitation.default_can_view,
      default_can_create_card: invitation.default_can_create_card,
      default_can_run_task: invitation.default_can_run_task,
      default_can_access_sensitive: invitation.default_can_access_sensitive,
      max_uses: invitation.max_uses,
      expires_days: null,
      access_valid_days: null,
      note: invitation.note,
    }
  } else {
    editingInvitation.value = null
    invForm.value = {
      code: '',
      target_level: 1,
      target_member_id: null,
      allowed_projects: [],
      user_display_name: '',
      user_description: '',
      default_can_view: true,
      default_can_create_card: false,
      default_can_run_task: false,
      default_can_access_sensitive: false,
      max_uses: 1,
      expires_days: 30,
      access_valid_days: null,
      note: '',
    }
  }
  showInvDialog.value = true
}

async function saveInvitation() {
  savingInv.value = true
  try {
    const url = editingInvitation.value
      ? `${API}/api/v1/invitations/${editingInvitation.value.id}`
      : `${API}/api/v1/invitations`
    const method = editingInvitation.value ? 'PATCH' : 'POST'

    const body = editingInvitation.value
      ? {
          user_display_name: invForm.value.user_display_name,
          user_description: invForm.value.user_description,
          default_can_view: invForm.value.default_can_view,
          default_can_create_card: invForm.value.default_can_create_card,
          default_can_run_task: invForm.value.default_can_run_task,
          default_can_access_sensitive: invForm.value.default_can_access_sensitive,
          max_uses: invForm.value.max_uses,
          expires_days: invForm.value.expires_days,
          note: invForm.value.note,
        }
      : {
          code: invForm.value.code || undefined,
          target_level: invForm.value.target_level,
          target_member_id: invForm.value.target_member_id,
          allowed_projects: invForm.value.allowed_projects.length > 0 ? invForm.value.allowed_projects : undefined,
          user_display_name: invForm.value.user_display_name,
          user_description: invForm.value.user_description,
          default_can_view: invForm.value.default_can_view,
          default_can_create_card: invForm.value.default_can_create_card,
          default_can_run_task: invForm.value.default_can_run_task,
          default_can_access_sensitive: invForm.value.default_can_access_sensitive,
          max_uses: invForm.value.max_uses,
          expires_days: invForm.value.expires_days,
          note: invForm.value.note,
        }

    const res = await fetch(url, {
      method,
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '儲存失敗' }))
      throw new Error(err.detail)
    }
    store.addToast(editingInvitation.value ? '邀請碼已更新' : '邀請碼已建立', 'success')
    showInvDialog.value = false
    await fetchInvitations()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
  savingInv.value = false
}

function requestDeleteInv(invitation: Invitation) {
  deleteInvTarget.value = invitation
  confirmDeleteInv.value = true
}

async function doDeleteInv() {
  if (!deleteInvTarget.value) return
  try {
    const res = await fetch(`${API}/api/v1/invitations/${deleteInvTarget.value.id}`, { method: 'DELETE', headers: authHeaders() })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '刪除失敗' }))
      throw new Error(err.detail)
    }
    store.addToast('邀請碼已刪除', 'success')
    confirmDeleteInv.value = false
    deleteInvTarget.value = null
    showInvDialog.value = false
    await fetchInvitations()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}

async function copyCode(code: string) {
  try {
    await navigator.clipboard.writeText(code)
    store.addToast('已複製邀請碼', 'success')
  } catch {
    store.addToast('複製失敗', 'error')
  }
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleDateString('zh-TW', { year: 'numeric', month: '2-digit', day: '2-digit' })
}

function getProjectNames(projectIds: number[] | null): string {
  if (!projectIds || projectIds.length === 0) return '所有專案'
  return projectIds
    .map(id => projects.value.find(p => p.id === id)?.name || `#${id}`)
    .join(', ')
}

function getStatusColor(status: string) {
  switch (status) {
    case 'active': return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
    case 'expired': return 'bg-amber-500/20 text-amber-400 border-amber-500/30'
    case 'depleted': return 'bg-slate-500/20 text-slate-400 border-slate-500/30'
    default: return ''
  }
}

function getStatusText(status: string) {
  switch (status) {
    case 'active': return '有效'
    case 'expired': return '已過期'
    case 'depleted': return '已用完'
    default: return status
  }
}

function getLevelText(level: number) {
  switch (level) {
    case 1: return 'L1 一般'
    case 2: return 'L2 進階'
    case 3: return 'L3 管理員'
    default: return `L${level}`
  }
}

// ─── Init ───────────────────────────────────────────────

onMounted(() => {
  fetchUsers()
  fetchInvitations()
  fetchProjects()
  fetchMembers()
})
</script>

<template>
  <div class="space-y-8">
    <!-- Header Actions (Teleport to layout header) -->
    <Teleport to="#settings-header-actions">
      <button
        @click="openInvDialog()"
        class="flex items-center gap-1.5 px-3 py-1.5 bg-sky-600 hover:bg-sky-500 rounded-lg text-xs font-medium transition"
      >
        <Plus class="w-3.5 h-3.5" />
        建立邀請碼
      </button>
    </Teleport>

    <!-- ═══ Section 1: 已驗證用戶 ═══ -->
    <section>
      <h2 class="text-sm font-bold text-slate-300 mb-3 flex items-center gap-2">
        <UserCheck class="w-4 h-4 text-emerald-400" />
        已驗證用戶
      </h2>

      <div v-if="usersLoading" class="flex justify-center py-8">
        <Loader2 class="w-6 h-6 animate-spin text-slate-400" />
      </div>

      <div v-else class="space-y-3">
        <div
          v-for="u in botUsers"
          :key="u.id"
          class="bg-slate-900/50 rounded-xl border border-slate-700/50 p-4"
          :class="{ 'opacity-50': !u.is_active }"
        >
          <div class="flex items-center justify-between">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="font-medium text-slate-200">{{ u.username || u.platform_user_id }}</span>
                <span :class="['px-2 py-0.5 text-xs rounded border', userLevelColor(u.level)]">
                  {{ userLevelLabel(u.level) }}
                </span>
                <span class="text-xs text-slate-500 bg-slate-800 px-1.5 py-0.5 rounded">{{ u.platform }}</span>
                <span v-if="!u.is_active" class="px-2 py-0.5 text-xs rounded bg-red-500/20 text-red-400 border border-red-500/30">
                  已封鎖
                </span>
                <span v-if="isUserExpired(u)" class="px-2 py-0.5 text-xs rounded bg-orange-500/20 text-orange-400 border border-orange-500/30">
                  已過期
                </span>
              </div>
              <div class="flex items-center gap-4 mt-1.5 text-xs text-slate-500">
                <span v-if="u.default_member_name">AI: {{ u.default_member_name }}</span>
                <span>建立: {{ formatDate(u.created_at) }}</span>
                <span v-if="u.access_expires_at">
                  <Clock class="w-3 h-3 inline" />
                  到期: {{ formatDate(u.access_expires_at) }}
                </span>
                <span v-if="u.last_active_at">最後活躍: {{ formatDate(u.last_active_at) }}</span>
              </div>
              <div v-if="u.projects.length" class="flex flex-wrap gap-1 mt-1.5">
                <span
                  v-for="p in u.projects"
                  :key="p.id"
                  class="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700"
                >
                  {{ p.display_name || `#${p.project_id}` }}
                </span>
              </div>
            </div>
            <div class="flex items-center gap-2 ml-4">
              <button
                @click="openEditUser(u)"
                class="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-700 rounded-lg transition"
                title="編輯"
              >
                <Edit3 class="w-4 h-4" />
              </button>
              <button
                @click="deleteUserTarget = u; confirmDeleteUser = true"
                class="p-2 text-slate-400 hover:text-red-400 hover:bg-slate-700 rounded-lg transition"
                title="刪除"
              >
                <Trash2 class="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>

        <div v-if="botUsers.length === 0" class="text-center py-8 text-slate-500 text-sm">
          尚無已驗證的 Bot 用戶
        </div>
      </div>
    </section>

    <!-- ═══ Section 2: 邀請碼 ═══ -->
    <section>
      <h2 class="text-sm font-bold text-slate-300 mb-3 flex items-center gap-2">
        <Shield class="w-4 h-4 text-sky-400" />
        邀請碼
      </h2>

      <!-- 說明 -->
      <div class="bg-slate-800/30 rounded-xl border border-slate-700/30 p-5 space-y-3 mb-4">
        <p class="text-sm text-slate-300">
          邀請碼用於控制誰可以透過 Telegram、LINE 等頻道與你的 AI 成員互動。
          用戶在 Bot 中輸入 <code class="text-sky-400 bg-slate-800 px-1.5 py-0.5 rounded text-xs">/verify 邀請碼</code> 驗證身份後，即獲得對應權限，可開始對話。
        </p>
        <p class="text-xs text-slate-500">
          每組邀請碼可限制使用次數（幾人可用它驗證）。用戶驗證成功後身份永久保留，不受邀請碼過期影響。
          身份描述會注入到 AI 的 prompt 中，讓 AI 知道對方是誰、能做什麼。
        </p>
        <div class="text-xs text-slate-500 space-y-2">
          <p class="font-medium text-slate-400">情境範例：</p>
          <ul class="space-y-2 ml-3">
            <li>
              <span class="text-slate-300">外部客戶</span>
              — L1 唯讀、限定特定專案、使用 1 次。身份描述填：<span class="text-slate-400 italic">「王先生是 A 專案客戶，可查看進度報告和數據摘要，不可查看財務資料和內部文件」</span>
            </li>
            <li>
              <span class="text-slate-300">內部同事</span>
              — L2 進階、可建卡片和執行任務、綁定特定 AI 成員。身份描述填：<span class="text-slate-400 italic">「張工程師是維運部同事，負責現場巡檢，可存取所有設備數據和工單」</span>
            </li>
            <li>
              <span class="text-slate-300">產品展示</span>
              — L1 唯讀、不限次數、30 天到期。分享給多人體驗 AI 對話功能，無需個別設定身份
            </li>
            <li>
              <span class="text-slate-300">合作廠商</span>
              — L1 唯讀、限定特定專案、使用 3 次（團隊共用）。身份描述填：<span class="text-slate-400 italic">「B 公司維修團隊，可查看設備告警和維修記錄，不可操作排程」</span>
            </li>
            <li>
              <span class="text-slate-300">臨時訪客</span>
              — L1 唯讀、使用 1 次、7 天到期。一對一場景，對方驗證後邀請碼自動失效
            </li>
          </ul>
        </div>
      </div>

      <div v-if="invLoading" class="flex justify-center py-8">
        <Loader2 class="w-6 h-6 animate-spin text-slate-400" />
      </div>

      <div v-else class="space-y-3">
        <div
          v-for="inv in invitations"
          :key="inv.id"
          class="bg-slate-900/50 rounded-xl border border-slate-700/50 p-4"
        >
          <div class="flex items-start justify-between gap-4">
            <!-- Left: Info -->
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <code class="px-2 py-1 bg-slate-800 rounded text-sky-300 font-mono text-sm">
                  {{ inv.code }}
                </code>
                <button
                  @click="copyCode(inv.code)"
                  class="p-1 text-slate-400 hover:text-slate-200 transition"
                  title="複製邀請碼"
                >
                  <Copy class="w-4 h-4" />
                </button>
                <span
                  :class="['px-2 py-0.5 text-xs rounded border', getStatusColor(inv.status)]"
                >
                  {{ getStatusText(inv.status) }}
                </span>
                <span class="px-2 py-0.5 text-xs rounded bg-violet-500/20 text-violet-400 border border-violet-500/30">
                  {{ getLevelText(inv.target_level) }}
                </span>
              </div>

              <div v-if="inv.user_display_name || inv.user_description" class="mt-2 text-sm">
                <span v-if="inv.user_display_name" class="text-slate-300">{{ inv.user_display_name }}</span>
                <span v-if="inv.user_description" class="text-slate-500 ml-2">{{ inv.user_description }}</span>
              </div>

              <div class="flex items-center gap-4 mt-2 text-xs text-slate-500 flex-wrap">
                <span class="flex items-center gap-1">
                  <Users class="w-3.5 h-3.5" />
                  {{ inv.used_count }} / {{ inv.max_uses }} 次
                </span>
                <span v-if="inv.expires_at" class="flex items-center gap-1">
                  <Clock class="w-3.5 h-3.5" />
                  {{ formatDate(inv.expires_at) }} 到期
                </span>
                <span>
                  {{ getProjectNames(inv.allowed_projects) }}
                </span>
                <span v-if="inv.note" class="text-slate-600">
                  {{ inv.note }}
                </span>
              </div>

              <div class="flex items-center gap-2 mt-2">
                <span v-if="inv.default_can_view" class="flex items-center gap-1 px-1.5 py-0.5 text-xs rounded bg-slate-800 text-slate-400">
                  <Eye class="w-3 h-3" /> 查看
                </span>
                <span v-if="inv.default_can_create_card" class="flex items-center gap-1 px-1.5 py-0.5 text-xs rounded bg-slate-800 text-slate-400">
                  <PenTool class="w-3 h-3" /> 建卡
                </span>
                <span v-if="inv.default_can_run_task" class="flex items-center gap-1 px-1.5 py-0.5 text-xs rounded bg-slate-800 text-slate-400">
                  <Play class="w-3 h-3" /> 執行
                </span>
                <span v-if="inv.default_can_access_sensitive" class="flex items-center gap-1 px-1.5 py-0.5 text-xs rounded bg-slate-800 text-slate-400">
                  <Shield class="w-3 h-3" /> 敏感
                </span>
              </div>
            </div>

            <!-- Right: Actions -->
            <div class="flex items-center gap-2">
              <button
                @click="openInvDialog(inv)"
                class="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-200 hover:bg-slate-700 rounded-lg transition"
              >
                編輯
              </button>
              <button
                @click="requestDeleteInv(inv)"
                class="p-2 text-slate-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition"
                title="刪除"
              >
                <Trash2 class="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>

        <div v-if="invitations.length === 0" class="text-center py-8 text-slate-500 text-sm">
          尚無邀請碼，點擊「建立邀請碼」開始
        </div>
      </div>
    </section>

    <!-- ═══ Dialog: Edit Bot User ═══ -->
    <Teleport to="body">
      <div
        v-if="showEditUser && editUser"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
        @click.self="showEditUser = false"
      >
        <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-md p-6 space-y-4">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-bold text-slate-200">
              編輯用戶 — {{ editUser.username || editUser.platform_user_id }}
            </h3>
            <button @click="showEditUser = false" class="text-slate-400 hover:text-slate-200">
              <X class="w-5 h-5" />
            </button>
          </div>

          <div>
            <label class="block text-sm text-slate-400 mb-1">權限等級</label>
            <select
              v-model.number="editUserForm.level"
              class="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-sm"
            >
              <option :value="0">L0 — 未驗證</option>
              <option :value="1">L1 — 訪客（唯讀）</option>
              <option :value="2">L2 — 成員（可執行任務）</option>
              <option :value="3">L3 — 管理員</option>
            </select>
          </div>

          <div class="flex items-center gap-3">
            <label class="text-sm text-slate-400">帳號狀態</label>
            <button
              @click="editUserForm.is_active = !editUserForm.is_active"
              :class="[
                'relative inline-flex h-6 w-11 items-center rounded-full transition-colors',
                editUserForm.is_active ? 'bg-emerald-600' : 'bg-slate-600'
              ]"
            >
              <span
                :class="[
                  'inline-block h-4 w-4 transform rounded-full bg-white transition-transform',
                  editUserForm.is_active ? 'translate-x-6' : 'translate-x-1'
                ]"
              />
            </button>
            <span class="text-sm" :class="editUserForm.is_active ? 'text-emerald-400' : 'text-red-400'">
              {{ editUserForm.is_active ? '啟用' : '封鎖' }}
            </span>
          </div>

          <div>
            <label class="block text-sm text-slate-400 mb-1">存取到期日</label>
            <input
              v-model="editUserForm.access_expires_at"
              type="date"
              class="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-sm"
            />
            <p class="text-[11px] text-slate-600 mt-1">留空表示永不過期。過期後用戶無法對話，但資料保留。</p>
          </div>

          <div class="flex justify-end gap-2 pt-2">
            <button
              @click="showEditUser = false"
              class="px-4 py-2 text-sm bg-slate-700 hover:bg-slate-600 rounded-lg transition"
            >
              取消
            </button>
            <button
              @click="saveEditUser"
              :disabled="savingUser"
              class="px-4 py-2 text-sm bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded-lg transition"
            >
              儲存
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ═══ Dialog: Add/Edit Invitation ═══ -->
    <Teleport to="body">
      <div
        v-if="showInvDialog"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
        @click.self="showInvDialog = false"
      >
        <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-lg p-6 space-y-4 max-h-[90vh] overflow-y-auto">
          <h3 class="text-sm font-bold text-slate-200">
            {{ editingInvitation ? '編輯邀請碼' : '新增邀請碼' }}
          </h3>

          <div class="space-y-4">
            <div v-if="!editingInvitation">
              <label class="block text-sm text-slate-400 mb-1">邀請碼</label>
              <input
                v-model="invForm.code"
                type="text"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-sky-500 placeholder-slate-500 font-mono uppercase"
                placeholder="留空自動生成"
              />
            </div>

            <div>
              <label class="block text-sm text-slate-400 mb-1">用戶顯示名稱</label>
              <input
                v-model="invForm.user_display_name"
                type="text"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-sky-500 placeholder-slate-500"
                placeholder="如：王小華"
              />
            </div>

            <div>
              <label class="block text-sm text-slate-400 mb-1">身份描述（AI 會參考）</label>
              <textarea
                v-model="invForm.user_description"
                rows="2"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-sky-500 placeholder-slate-500 resize-none"
                placeholder="如：案場業主，可查看發電資料和維運進度"
              />
            </div>

            <div v-if="!editingInvitation">
              <label class="block text-sm text-slate-400 mb-1">權限等級</label>
              <select
                v-model="invForm.target_level"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-sky-500"
              >
                <option :value="1">L1 一般用戶（查看、留言）</option>
                <option :value="2">L2 進階用戶（建卡、執行任務）</option>
                <option :value="3">L3 管理員（完整權限）</option>
              </select>
            </div>

            <div>
              <label class="block text-sm text-slate-400 mb-1">預設 AI 成員</label>
              <select
                v-model="invForm.target_member_id"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-sky-500"
              >
                <option :value="null">不指定</option>
                <option v-for="m in members" :key="m.id" :value="m.id">
                  {{ m.avatar || '' }} {{ m.name }}
                </option>
              </select>
              <p class="text-[11px] text-slate-600 mt-1">用戶驗證後預設與哪個 AI 成員對話</p>
            </div>

            <div v-if="!editingInvitation && projects.length > 0">
              <label class="block text-sm text-slate-400 mb-1">可存取專案</label>
              <div class="space-y-2 max-h-32 overflow-y-auto">
                <label
                  v-for="p in projects"
                  :key="p.id"
                  class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer hover:bg-slate-800"
                >
                  <input
                    type="checkbox"
                    :value="p.id"
                    v-model="invForm.allowed_projects"
                    class="rounded bg-slate-700 border-slate-600 text-sky-500 focus:ring-sky-500"
                  />
                  <span class="text-sm text-slate-300">{{ p.name }}</span>
                </label>
              </div>
              <p class="text-xs text-slate-500 mt-1">
                不勾選則可存取所有專案
              </p>
            </div>

            <div>
              <label class="block text-sm text-slate-400 mb-1">權限模板</label>
              <div class="flex gap-2">
                <button
                  v-for="t in permissionTemplates"
                  :key="t.name"
                  @click="applyTemplate(t)"
                  :class="[
                    'px-3 py-1.5 text-sm rounded-lg transition',
                    currentTemplate === t.name
                      ? 'bg-sky-600 text-white'
                      : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                  ]"
                >
                  {{ t.name }}
                </button>
              </div>
            </div>

            <div class="grid grid-cols-2 gap-2">
              <label class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer">
                <input type="checkbox" v-model="invForm.default_can_view" class="rounded bg-slate-700 border-slate-600 text-sky-500" />
                <Eye class="w-4 h-4 text-slate-400" />
                <span class="text-sm text-slate-300">查看卡片</span>
              </label>
              <label class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer">
                <input type="checkbox" v-model="invForm.default_can_create_card" class="rounded bg-slate-700 border-slate-600 text-sky-500" />
                <PenTool class="w-4 h-4 text-slate-400" />
                <span class="text-sm text-slate-300">建立卡片</span>
              </label>
              <label class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer">
                <input type="checkbox" v-model="invForm.default_can_run_task" class="rounded bg-slate-700 border-slate-600 text-sky-500" />
                <Play class="w-4 h-4 text-slate-400" />
                <span class="text-sm text-slate-300">執行任務</span>
              </label>
              <label class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer">
                <input type="checkbox" v-model="invForm.default_can_access_sensitive" class="rounded bg-slate-700 border-slate-600 text-sky-500" />
                <Shield class="w-4 h-4 text-slate-400" />
                <span class="text-sm text-slate-300">敏感資料</span>
              </label>
            </div>

            <div>
              <label class="block text-sm text-slate-400 mb-1">可使用次數</label>
              <input
                v-model.number="invForm.max_uses"
                type="number"
                min="1"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-sky-500"
              />
            </div>

            <div>
              <label class="block text-sm text-slate-400 mb-1">邀請碼有效天數</label>
              <input
                v-model.number="invForm.expires_days"
                type="number"
                min="1"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-sky-500 placeholder-slate-500"
                placeholder="留空則永不過期"
              />
              <p class="text-[11px] text-slate-600 mt-1">過期後此邀請碼無法再被新用戶驗證。已驗證的用戶不受影響。</p>
            </div>

            <div>
              <label class="block text-sm text-slate-400 mb-1">對話有效天數</label>
              <input
                v-model.number="invForm.access_valid_days"
                type="number"
                min="1"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-sky-500 placeholder-slate-500"
                placeholder="留空則永久有效"
              />
              <p class="text-[11px] text-slate-600 mt-1">用戶驗證後可與 AI 對話的天數。過期後無法對話，但資料保留，管理員可延期。</p>
            </div>

            <div>
              <label class="block text-sm text-slate-400 mb-1">備註</label>
              <input
                v-model="invForm.note"
                type="text"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-sky-500 placeholder-slate-500"
                placeholder="如：給客戶A用"
              />
            </div>
          </div>

          <div class="flex justify-between pt-2">
            <div>
              <button
                v-if="editingInvitation"
                @click="requestDeleteInv(editingInvitation)"
                class="flex items-center gap-2 px-4 py-2 text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg transition"
              >
                <Trash2 class="w-4 h-4" />
                刪除
              </button>
            </div>
            <div class="flex gap-3">
              <button
                @click="showInvDialog = false"
                class="px-4 py-2 text-slate-400 hover:text-slate-200 transition"
              >
                取消
              </button>
              <button
                @click="saveInvitation"
                :disabled="savingInv"
                class="flex items-center gap-2 px-4 py-2 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition"
              >
                <Loader2 v-if="savingInv" class="w-4 h-4 animate-spin" />
                {{ editingInvitation ? '儲存' : '建立' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ═══ Confirm Dialogs ═══ -->
    <ConfirmDialog
      v-model:show="confirmDeleteUser"
      title="刪除用戶"
      :message="`確定要刪除「${deleteUserTarget?.username || deleteUserTarget?.platform_user_id}」？\n此操作會刪除該用戶的所有對話記錄和權限設定。`"
      confirm-text="刪除"
      @confirm="doDeleteUser"
    />

    <ConfirmDialog
      v-model:show="confirmDeleteInv"
      title="刪除邀請碼"
      :message="`確定要刪除邀請碼「${deleteInvTarget?.code}」？`"
      confirm-text="刪除"
      @confirm="doDeleteInv"
    />
  </div>
</template>
