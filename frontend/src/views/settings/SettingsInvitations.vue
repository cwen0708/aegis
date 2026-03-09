<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Mail, Plus, Copy, Trash2, Loader2, Clock, Users, Eye, PenTool, Play, Shield } from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'
import ConfirmDialog from '../../components/ConfirmDialog.vue'

const store = useAegisStore()
const API = ''

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

const loading = ref(true)
const saving = ref(false)
const invitations = ref<Invitation[]>([])
const projects = ref<ProjectOption[]>([])
const members = ref<MemberOption[]>([])

// Dialog
const showDialog = ref(false)
const editingInvitation = ref<Invitation | null>(null)
const form = ref({
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
  note: '',
})

// Delete confirm
const confirmDelete = ref(false)
const deleteTarget = ref<Invitation | null>(null)

// 權限模板
const permissionTemplates = [
  { name: '訪客', can_view: true, can_create_card: false, can_run_task: false, can_access_sensitive: false },
  { name: '成員', can_view: true, can_create_card: true, can_run_task: true, can_access_sensitive: false },
  { name: '管理員', can_view: true, can_create_card: true, can_run_task: true, can_access_sensitive: true },
]

const currentTemplate = computed(() => {
  const t = permissionTemplates.find(t =>
    t.can_view === form.value.default_can_view &&
    t.can_create_card === form.value.default_can_create_card &&
    t.can_run_task === form.value.default_can_run_task &&
    t.can_access_sensitive === form.value.default_can_access_sensitive
  )
  return t?.name || '自訂'
})

function applyTemplate(template: typeof permissionTemplates[0]) {
  form.value.default_can_view = template.can_view
  form.value.default_can_create_card = template.can_create_card
  form.value.default_can_run_task = template.can_run_task
  form.value.default_can_access_sensitive = template.can_access_sensitive
}

async function fetchInvitations() {
  loading.value = true
  try {
    const res = await fetch(`${API}/api/v1/invitations`)
    if (!res.ok) throw new Error('載入失敗')
    invitations.value = await res.json()
  } catch (e: any) {
    store.addToast(e.message || '邀請碼載入失敗', 'error')
  }
  loading.value = false
}

async function fetchProjects() {
  try {
    const res = await fetch(`${API}/api/v1/projects/`)
    if (res.ok) {
      const data = await res.json()
      projects.value = data.map((p: any) => ({ id: p.id, name: p.name }))
    }
  } catch {}
}

async function fetchMembers() {
  try {
    const res = await fetch(`${API}/api/v1/members`)
    if (res.ok) members.value = await res.json()
  } catch {}
}

onMounted(() => {
  fetchInvitations()
  fetchProjects()
  fetchMembers()
})

function openDialog(invitation?: Invitation) {
  if (invitation) {
    editingInvitation.value = invitation
    form.value = {
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
      note: invitation.note,
    }
  } else {
    editingInvitation.value = null
    form.value = {
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
      note: '',
    }
  }
  showDialog.value = true
}

async function saveInvitation() {
  saving.value = true
  try {
    const url = editingInvitation.value
      ? `${API}/api/v1/invitations/${editingInvitation.value.id}`
      : `${API}/api/v1/invitations`
    const method = editingInvitation.value ? 'PATCH' : 'POST'

    const body = editingInvitation.value
      ? {
          user_display_name: form.value.user_display_name,
          user_description: form.value.user_description,
          default_can_view: form.value.default_can_view,
          default_can_create_card: form.value.default_can_create_card,
          default_can_run_task: form.value.default_can_run_task,
          default_can_access_sensitive: form.value.default_can_access_sensitive,
          max_uses: form.value.max_uses,
          expires_days: form.value.expires_days,
          note: form.value.note,
        }
      : {
          code: form.value.code || undefined,
          target_level: form.value.target_level,
          target_member_id: form.value.target_member_id,
          allowed_projects: form.value.allowed_projects.length > 0 ? form.value.allowed_projects : undefined,
          user_display_name: form.value.user_display_name,
          user_description: form.value.user_description,
          default_can_view: form.value.default_can_view,
          default_can_create_card: form.value.default_can_create_card,
          default_can_run_task: form.value.default_can_run_task,
          default_can_access_sensitive: form.value.default_can_access_sensitive,
          max_uses: form.value.max_uses,
          expires_days: form.value.expires_days,
          note: form.value.note,
        }

    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '儲存失敗' }))
      throw new Error(err.detail)
    }
    store.addToast(editingInvitation.value ? '邀請碼已更新' : '邀請碼已建立', 'success')
    showDialog.value = false
    await fetchInvitations()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
  saving.value = false
}

function requestDelete(invitation: Invitation) {
  deleteTarget.value = invitation
  confirmDelete.value = true
}

async function doDelete() {
  if (!deleteTarget.value) return
  try {
    const res = await fetch(`${API}/api/v1/invitations/${deleteTarget.value.id}`, { method: 'DELETE' })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '刪除失敗' }))
      throw new Error(err.detail)
    }
    store.addToast('邀請碼已刪除', 'success')
    confirmDelete.value = false
    deleteTarget.value = null
    showDialog.value = false
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

function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleDateString('zh-TW')
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
</script>

<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-3">
        <Mail class="w-6 h-6 text-sky-400" />
        <h2 class="text-xl font-semibold">邀請管理</h2>
      </div>
      <button
        @click="openDialog()"
        class="flex items-center gap-2 px-4 py-2 bg-sky-600 hover:bg-sky-500 rounded-lg transition"
      >
        <Plus class="w-4 h-4" />
        新增邀請碼
      </button>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex justify-center py-12">
      <Loader2 class="w-8 h-8 animate-spin text-slate-400" />
    </div>

    <!-- Invitation List -->
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
              <!-- Code -->
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
              <!-- Status -->
              <span
                :class="['px-2 py-0.5 text-xs rounded border', getStatusColor(inv.status)]"
              >
                {{ getStatusText(inv.status) }}
              </span>
              <!-- Level -->
              <span class="px-2 py-0.5 text-xs rounded bg-violet-500/20 text-violet-400 border border-violet-500/30">
                {{ getLevelText(inv.target_level) }}
              </span>
            </div>

            <!-- User info -->
            <div v-if="inv.user_display_name || inv.user_description" class="mt-2 text-sm">
              <span v-if="inv.user_display_name" class="text-slate-300">{{ inv.user_display_name }}</span>
              <span v-if="inv.user_description" class="text-slate-500 ml-2">{{ inv.user_description }}</span>
            </div>

            <!-- Meta -->
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

            <!-- Permissions -->
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
              @click="openDialog(inv)"
              class="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-200 hover:bg-slate-700 rounded-lg transition"
            >
              編輯
            </button>
            <button
              @click="requestDelete(inv)"
              class="p-2 text-slate-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition"
              title="刪除"
            >
              <Trash2 class="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      <!-- Empty State -->
      <div v-if="invitations.length === 0" class="text-center py-12 text-slate-500">
        尚無邀請碼，點擊「新增邀請碼」開始
      </div>
    </div>

    <!-- Dialog: Add/Edit Invitation -->
    <Teleport to="body">
      <div
        v-if="showDialog"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
        @click.self="showDialog = false"
      >
        <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-lg p-6 space-y-4 max-h-[90vh] overflow-y-auto">
          <h3 class="text-lg font-semibold">
            {{ editingInvitation ? '編輯邀請碼' : '新增邀請碼' }}
          </h3>

          <div class="space-y-4">
            <!-- Code (only for new) -->
            <div v-if="!editingInvitation">
              <label class="block text-sm text-slate-400 mb-1">邀請碼</label>
              <input
                v-model="form.code"
                type="text"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-sky-500 placeholder-slate-500 font-mono uppercase"
                placeholder="留空自動生成"
              />
            </div>

            <!-- User Display Name -->
            <div>
              <label class="block text-sm text-slate-400 mb-1">用戶顯示名稱</label>
              <input
                v-model="form.user_display_name"
                type="text"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-sky-500 placeholder-slate-500"
                placeholder="如：王小華"
              />
            </div>

            <!-- User Description -->
            <div>
              <label class="block text-sm text-slate-400 mb-1">身份描述（AI 會參考）</label>
              <textarea
                v-model="form.user_description"
                rows="2"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-sky-500 placeholder-slate-500 resize-none"
                placeholder="如：案場業主，可查看發電資料和維運進度"
              />
            </div>

            <!-- Level (only for new) -->
            <div v-if="!editingInvitation">
              <label class="block text-sm text-slate-400 mb-1">權限等級</label>
              <select
                v-model="form.target_level"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-sky-500"
              >
                <option :value="1">L1 一般用戶（查看、留言）</option>
                <option :value="2">L2 進階用戶（建卡、執行任務）</option>
                <option :value="3">L3 管理員（完整權限）</option>
              </select>
            </div>

            <!-- Allowed Projects (only for new) -->
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
                    v-model="form.allowed_projects"
                    class="rounded bg-slate-700 border-slate-600 text-sky-500 focus:ring-sky-500"
                  />
                  <span class="text-sm text-slate-300">{{ p.name }}</span>
                </label>
              </div>
              <p class="text-xs text-slate-500 mt-1">
                不勾選則可存取所有專案
              </p>
            </div>

            <!-- Permission Template -->
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

            <!-- Fine-grained Permissions -->
            <div class="grid grid-cols-2 gap-2">
              <label class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer">
                <input type="checkbox" v-model="form.default_can_view" class="rounded bg-slate-700 border-slate-600 text-sky-500" />
                <Eye class="w-4 h-4 text-slate-400" />
                <span class="text-sm text-slate-300">查看卡片</span>
              </label>
              <label class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer">
                <input type="checkbox" v-model="form.default_can_create_card" class="rounded bg-slate-700 border-slate-600 text-sky-500" />
                <PenTool class="w-4 h-4 text-slate-400" />
                <span class="text-sm text-slate-300">建立卡片</span>
              </label>
              <label class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer">
                <input type="checkbox" v-model="form.default_can_run_task" class="rounded bg-slate-700 border-slate-600 text-sky-500" />
                <Play class="w-4 h-4 text-slate-400" />
                <span class="text-sm text-slate-300">執行任務</span>
              </label>
              <label class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer">
                <input type="checkbox" v-model="form.default_can_access_sensitive" class="rounded bg-slate-700 border-slate-600 text-sky-500" />
                <Shield class="w-4 h-4 text-slate-400" />
                <span class="text-sm text-slate-300">敏感資料</span>
              </label>
            </div>

            <!-- Max Uses -->
            <div>
              <label class="block text-sm text-slate-400 mb-1">可使用次數</label>
              <input
                v-model.number="form.max_uses"
                type="number"
                min="1"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-sky-500"
              />
            </div>

            <!-- Expires Days -->
            <div>
              <label class="block text-sm text-slate-400 mb-1">有效天數</label>
              <input
                v-model.number="form.expires_days"
                type="number"
                min="1"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-sky-500 placeholder-slate-500"
                placeholder="留空則永不過期"
              />
            </div>

            <!-- Note -->
            <div>
              <label class="block text-sm text-slate-400 mb-1">備註</label>
              <input
                v-model="form.note"
                type="text"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-sky-500 placeholder-slate-500"
                placeholder="如：給客戶A用"
              />
            </div>
          </div>

          <!-- Actions -->
          <div class="flex justify-between pt-2">
            <!-- Left: Delete (only when editing) -->
            <div>
              <button
                v-if="editingInvitation"
                @click="requestDelete(editingInvitation)"
                class="flex items-center gap-2 px-4 py-2 text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg transition"
              >
                <Trash2 class="w-4 h-4" />
                刪除
              </button>
            </div>
            <!-- Right: Cancel & Save -->
            <div class="flex gap-3">
              <button
                @click="showDialog = false"
                class="px-4 py-2 text-slate-400 hover:text-slate-200 transition"
              >
                取消
              </button>
              <button
                @click="saveInvitation"
                :disabled="saving"
                class="flex items-center gap-2 px-4 py-2 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition"
              >
                <Loader2 v-if="saving" class="w-4 h-4 animate-spin" />
                {{ editingInvitation ? '儲存' : '建立' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Confirm Delete -->
    <ConfirmDialog
      v-model:show="confirmDelete"
      title="刪除邀請碼"
      :message="`確定要刪除邀請碼「${deleteTarget?.code}」？`"
      confirm-text="刪除"
      @confirm="doDelete"
    />
  </div>
</template>
