<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft, Save, Loader2, Trash2, Copy, AlertTriangle, Plus, X,
} from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { config } from '../../config'
import { authHeaders } from '../../utils/authFetch'

const route = useRoute()
const router = useRouter()
const store = useAegisStore()
const API = config.apiUrl

const personId = Number(route.params.id)
const loading = ref(true)
const saving = ref(false)
const confirmDelete = ref(false)

// ── Types ──
interface BotUserInfo {
  id: number
  platform: string
  username: string | null
  platform_user_id: string
  last_active_at: string | null
  level: number
  is_active: boolean
}

interface InviteCodeInfo {
  id: number
  code: string
  status: string
  used_count: number
  max_uses: number
}

interface PersonMemberInfo {
  id: number
  member_id: number
  member_name: string
  member_avatar: string
  is_default: boolean
  can_switch: boolean
}

interface PersonProjectInfo {
  id: number
  project_id: number
  display_name: string
  description: string
  can_view: boolean
  can_create_card: boolean
  can_run_task: boolean
  can_access_sensitive: boolean
  is_default: boolean
}

interface PersonDetail {
  id: number
  display_name: string
  description: string
  level: number
  extra_json: string
  access_expires_at: string | null
  default_member_id: number | null
  created_at: string
  status: string
  bot_users: BotUserInfo[]
  invite_codes: InviteCodeInfo[]
  projects: PersonProjectInfo[]
  members: PersonMemberInfo[]
}

// ── Form ──
const form = ref({
  display_name: '',
  description: '',
  level: 0,
  access_expires_at: '',
})

const person = ref<PersonDetail | null>(null)

// ── Projects list for display ──
interface ProjectOption { id: number; name: string }
const allProjects = ref<ProjectOption[]>([])

// ── Fetch ──
async function fetchPerson() {
  try {
    const res = await fetch(`${API}/api/v1/persons/${personId}`, { headers: authHeaders() })
    if (!res.ok) throw new Error('載入失敗')
    person.value = await res.json()
    form.value = {
      display_name: person.value!.display_name,
      description: person.value!.description,
      level: person.value!.level,
      access_expires_at: person.value!.access_expires_at
        ? person.value!.access_expires_at.split('T')[0] ?? ''
        : '',
    }
  } catch (e: any) {
    store.addToast(e.message || '載入失敗', 'error')
    router.push('/settings/users')
  }
}

async function fetchProjects() {
  try {
    const res = await fetch(`${API}/api/v1/projects/?all=true`, { headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      allProjects.value = data.map((p: any) => ({ id: p.id, name: p.name }))
    }
  } catch {}
}

// ── Save ──
async function savePerson() {
  saving.value = true
  try {
    const body: Record<string, unknown> = {
      display_name: form.value.display_name,
      description: form.value.description,
      level: form.value.level,
    }
    body.access_expires_at = form.value.access_expires_at
      ? form.value.access_expires_at + 'T00:00:00Z'
      : null
    const res = await fetch(`${API}/api/v1/persons/${personId}`, {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    })
    if (!res.ok) throw new Error('儲存失敗')
    store.addToast('用戶已更新', 'success')
    await fetchPerson()
  } catch (e: any) {
    store.addToast(e.message || '儲存失敗', 'error')
  }
  saving.value = false
}

// ── Delete ──
async function doDelete() {
  try {
    const res = await fetch(`${API}/api/v1/persons/${personId}`, {
      method: 'DELETE',
      headers: authHeaders(),
    })
    if (!res.ok) throw new Error('刪除失敗')
    store.addToast('用戶已刪除', 'success')
    router.push('/settings/users')
  } catch (e: any) {
    store.addToast(e.message || '刪除失敗', 'error')
  }
}

// ── Helpers ──
function platformIcon(platform: string): string {
  const icons: Record<string, string> = {
    telegram: 'TG',
    line: 'LINE',
    discord: 'DC',
    web: 'WEB',
  }
  return icons[platform] || platform.toUpperCase()
}

function getProjectName(projectId: number): string {
  return allProjects.value.find(p => p.id === projectId)?.name || `#${projectId}`
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleDateString('zh-TW', { year: 'numeric', month: '2-digit', day: '2-digit' })
}

async function copyCode(code: string) {
  try {
    await navigator.clipboard.writeText(code)
    store.addToast('已複製邀請碼', 'success')
  } catch {
    store.addToast('複製失敗', 'error')
  }
}

// ── PersonProject management ──
const showAddProject = ref(false)
const addingProjectId = ref<number | null>(null)

function availableProjects(): ProjectOption[] {
  if (!person.value) return []
  const existingIds = new Set(person.value.projects.map(p => p.project_id))
  return allProjects.value.filter(p => !existingIds.has(p.id))
}

async function addProject() {
  if (!addingProjectId.value) return
  try {
    const res = await fetch(`${API}/api/v1/persons/${personId}/projects`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ project_id: addingProjectId.value }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '新增失敗' }))
      throw new Error(err.detail)
    }
    store.addToast('專案已新增', 'success')
    showAddProject.value = false
    addingProjectId.value = null
    await fetchPerson()
  } catch (e: any) {
    store.addToast(e.message || '新增失敗', 'error')
  }
}

async function removeProject(projectId: number) {
  try {
    const res = await fetch(`${API}/api/v1/persons/${personId}/projects/${projectId}`, {
      method: 'DELETE',
      headers: authHeaders(),
    })
    if (!res.ok) throw new Error('移除失敗')
    store.addToast('專案已移除', 'success')
    await fetchPerson()
  } catch (e: any) {
    store.addToast(e.message || '移除失敗', 'error')
  }
}

async function togglePermission(pp: PersonProjectInfo, field: string, value: boolean) {
  const old = (pp as any)[field]
  ;(pp as any)[field] = value
  try {
    const res = await fetch(`${API}/api/v1/persons/${personId}/projects/${pp.project_id}`, {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ [field]: value }),
    })
    if (!res.ok) throw new Error('更新失敗')
  } catch (e: any) {
    ;(pp as any)[field] = old
    store.addToast(e.message || '更新失敗', 'error')
  }
}

// ── PersonMember management ──
interface MemberOption { id: number; name: string; avatar: string }
const allMembers = ref<MemberOption[]>([])
const showAddMember = ref(false)
const addingMemberId = ref<number | null>(null)

async function fetchMembers() {
  try {
    const res = await fetch(`${API}/api/v1/members`, { headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      allMembers.value = data.map((m: any) => ({ id: m.id, name: m.name, avatar: m.avatar || '' }))
    }
  } catch {}
}

function availableMembers(): MemberOption[] {
  if (!person.value) return []
  const existingIds = new Set(person.value.members.map(m => m.member_id))
  return allMembers.value.filter(m => !existingIds.has(m.id))
}

async function addMember() {
  if (!addingMemberId.value) return
  try {
    const res = await fetch(`${API}/api/v1/persons/${personId}/members`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ member_id: addingMemberId.value }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '新增失敗' }))
      throw new Error(err.detail)
    }
    store.addToast('成員已新增', 'success')
    showAddMember.value = false
    addingMemberId.value = null
    await fetchPerson()
  } catch (e: any) {
    store.addToast(e.message || '新增失敗', 'error')
  }
}

async function removeMember(memberId: number) {
  try {
    const res = await fetch(`${API}/api/v1/persons/${personId}/members/${memberId}`, {
      method: 'DELETE',
      headers: authHeaders(),
    })
    if (!res.ok) throw new Error('移除失敗')
    store.addToast('成員已移除', 'success')
    await fetchPerson()
  } catch (e: any) {
    store.addToast(e.message || '移除失敗', 'error')
  }
}

async function toggleMemberField(pm: PersonMemberInfo, field: string, value: boolean) {
  const old = (pm as any)[field]
  ;(pm as any)[field] = value
  try {
    const res = await fetch(`${API}/api/v1/persons/${personId}/members/${pm.member_id}`, {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ [field]: value }),
    })
    if (!res.ok) throw new Error('更新失敗')
  } catch (e: any) {
    ;(pm as any)[field] = old
    store.addToast(e.message || '更新失敗', 'error')
  }
}

// ── Init ──
onMounted(async () => {
  await Promise.all([fetchPerson(), fetchProjects(), fetchMembers()])
  loading.value = false
})
</script>

<template>
  <div class="space-y-6">
    <!-- Header actions -->
    <Teleport to="#settings-header-actions">
      <button
        @click="savePerson"
        :disabled="saving || !form.display_name.trim()"
        class="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded-lg text-xs font-medium transition-colors"
      >
        <Loader2 v-if="saving" class="w-3.5 h-3.5 animate-spin" />
        <Save v-else class="w-3.5 h-3.5" />
        儲存
      </button>
    </Teleport>

    <!-- Header -->
    <div class="flex items-center gap-3">
      <button
        @click="router.push('/settings/users')"
        class="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 rounded-lg transition-colors"
      >
        <ArrowLeft class="w-5 h-5" />
      </button>
      <h2 class="text-xl font-semibold text-slate-200">{{ form.display_name || '用戶詳情' }}</h2>
      <span
        v-if="person"
        :class="[
          'px-2 py-0.5 text-xs rounded border',
          person.status === 'active'
            ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
            : 'bg-slate-500/20 text-slate-400 border-slate-500/30'
        ]"
      >
        {{ person.status === 'active' ? '已綁定' : '待驗證' }}
      </span>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex justify-center py-12">
      <Loader2 class="w-8 h-8 animate-spin text-slate-400" />
    </div>

    <template v-else-if="person">
      <!-- Section 1: 基本資訊 -->
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-6 space-y-4">
        <h3 class="text-sm font-bold text-slate-300 uppercase tracking-wider">基本資訊</h3>

        <div class="space-y-4">
          <div>
            <label class="block text-sm text-slate-400 mb-1">顯示名稱 <span class="text-red-400">*</span></label>
            <input
              v-model="form.display_name"
              type="text"
              class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500"
              placeholder="如：王小華"
            />
          </div>

          <div>
            <label class="block text-sm text-slate-400 mb-1">身份描述</label>
            <textarea
              v-model="form.description"
              rows="3"
              class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 resize-none"
              placeholder="如：案場業主，可查看發電資料..."
            ></textarea>
          </div>

          <div>
            <label class="block text-sm text-slate-400 mb-1">權限等級</label>
            <select
              v-model.number="form.level"
              class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg [color-scheme:dark]"
            >
              <option :value="0">L0 — 未驗證</option>
              <option :value="1">L1 — 訪客（唯讀）</option>
              <option :value="2">L2 — 成員（可執行任務）</option>
              <option :value="3">L3 — 管理員</option>
            </select>
          </div>

          <div>
            <label class="block text-sm text-slate-400 mb-1">存取到期日</label>
            <input
              v-model="form.access_expires_at"
              type="date"
              class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg [color-scheme:dark]"
            />
            <p class="text-[11px] text-slate-600 mt-1">留空表示永不過期</p>
          </div>
        </div>
      </div>

      <!-- Section 2: 平台帳號 (BotUser) -->
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-6 space-y-4">
        <h3 class="text-sm font-bold text-slate-300 uppercase tracking-wider">平台帳號</h3>

        <div v-if="person.bot_users.length === 0" class="text-center py-6 text-slate-500 text-sm">
          尚無平台帳號綁定
        </div>

        <div v-else class="space-y-2">
          <div
            v-for="bu in person.bot_users"
            :key="bu.id"
            class="flex items-center gap-3 px-4 py-3 bg-slate-900/50 rounded-xl border border-slate-700/50"
          >
            <span class="px-2 py-0.5 text-[10px] font-bold rounded bg-sky-500/20 text-sky-400 border border-sky-500/30">
              {{ platformIcon(bu.platform) }}
            </span>
            <span class="text-sm text-slate-200 flex-1 truncate">{{ bu.username || bu.platform_user_id }}</span>
            <span class="text-xs text-slate-500">L{{ bu.level }}</span>
            <span v-if="bu.last_active_at" class="text-xs text-slate-500">
              最後活躍: {{ formatDate(bu.last_active_at) }}
            </span>
            <span :class="bu.is_active ? 'text-emerald-500' : 'text-red-400'" class="text-xs">
              {{ bu.is_active ? '啟用' : '停用' }}
            </span>
          </div>
        </div>
      </div>

      <!-- Section 3: 邀請碼 -->
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-6 space-y-4">
        <h3 class="text-sm font-bold text-slate-300 uppercase tracking-wider">邀請碼</h3>

        <div v-if="person.invite_codes.length === 0" class="text-center py-6 text-slate-500 text-sm">
          無邀請碼
        </div>

        <div v-else class="space-y-2">
          <div
            v-for="ic in person.invite_codes"
            :key="ic.id"
            class="flex items-center gap-3 px-4 py-3 bg-slate-900/50 rounded-xl border border-slate-700/50"
          >
            <code class="px-2 py-1 bg-slate-800 rounded text-sky-300 font-mono text-sm">{{ ic.code }}</code>
            <button
              @click="copyCode(ic.code)"
              class="p-1 text-slate-400 hover:text-slate-200 transition"
              title="複製"
            >
              <Copy class="w-4 h-4" />
            </button>
            <span
              :class="[
                'px-2 py-0.5 text-xs rounded border',
                ic.status === 'active' ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' :
                ic.status === 'expired' ? 'bg-amber-500/20 text-amber-400 border-amber-500/30' :
                'bg-slate-500/20 text-slate-400 border-slate-500/30'
              ]"
            >
              {{ ic.status === 'active' ? '有效' : ic.status === 'expired' ? '已過期' : '已用完' }}
            </span>
            <span class="text-xs text-slate-500 ml-auto">{{ ic.used_count }} / {{ ic.max_uses }} 次</span>
          </div>
        </div>
      </div>

      <!-- Section 4: AI 成員 -->
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-6 space-y-4">
        <div class="flex items-center gap-2">
          <h3 class="text-sm font-bold text-slate-300 uppercase tracking-wider">AI 成員</h3>
          <span class="text-xs text-slate-500 ml-auto">{{ person.members.length }} / {{ allMembers.length }}</span>
          <button
            @click="showAddMember = !showAddMember"
            class="flex items-center gap-1 px-2 py-1 text-xs text-emerald-400 hover:text-emerald-300 hover:bg-emerald-500/10 border border-emerald-500/30 rounded-lg transition"
          >
            <Plus class="w-3.5 h-3.5" />
            新增成員
          </button>
        </div>

        <!-- Add member dropdown -->
        <div v-if="showAddMember" class="flex items-center gap-2 p-3 bg-slate-900/80 rounded-xl border border-slate-600">
          <select
            v-model.number="addingMemberId"
            class="flex-1 px-3 py-1.5 bg-slate-800 text-slate-200 border border-slate-600 rounded-lg text-sm [color-scheme:dark]"
          >
            <option :value="null" disabled>選擇成員...</option>
            <option v-for="m in availableMembers()" :key="m.id" :value="m.id">{{ m.avatar }} {{ m.name }}</option>
          </select>
          <button
            @click="addMember"
            :disabled="!addingMemberId"
            class="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-xs rounded-lg transition-colors"
          >
            加入
          </button>
          <button
            @click="showAddMember = false; addingMemberId = null"
            class="p-1.5 text-slate-400 hover:text-slate-200 transition"
          >
            <X class="w-4 h-4" />
          </button>
        </div>

        <div v-if="person.members.length === 0 && !showAddMember" class="text-center py-6 text-slate-500 text-sm">
          尚無 AI 成員綁定
        </div>

        <div v-else class="space-y-2">
          <div
            v-for="pm in person.members"
            :key="pm.id"
            class="flex items-center gap-3 px-4 py-3 bg-slate-900/50 rounded-xl border border-slate-700/50"
          >
            <span v-if="pm.member_avatar" class="text-lg">{{ pm.member_avatar }}</span>
            <span class="text-sm text-slate-200 font-medium">{{ pm.member_name }}</span>
            <span
              v-if="pm.is_default"
              class="px-1.5 py-0.5 text-[10px] font-bold rounded bg-amber-500/20 text-amber-400 border border-amber-500/30"
            >預設</span>
            <div class="flex items-center gap-3 ml-auto">
              <label class="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  :checked="pm.is_default"
                  @change="toggleMemberField(pm, 'is_default', !pm.is_default)"
                  class="rounded bg-slate-700 border-slate-600 text-amber-500 focus:ring-amber-500 w-3.5 h-3.5"
                />
                <span class="text-xs text-slate-400">預設</span>
              </label>
              <label class="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  :checked="pm.can_switch"
                  @change="toggleMemberField(pm, 'can_switch', !pm.can_switch)"
                  class="rounded bg-slate-700 border-slate-600 text-emerald-500 focus:ring-emerald-500 w-3.5 h-3.5"
                />
                <span class="text-xs text-slate-400">可切換</span>
              </label>
              <button
                @click="removeMember(pm.member_id)"
                class="p-1 text-slate-500 hover:text-red-400 transition"
                title="移除成員"
              >
                <X class="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Section 5: 專案權限 -->
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-6 space-y-4">
        <div class="flex items-center gap-2">
          <h3 class="text-sm font-bold text-slate-300 uppercase tracking-wider">專案權限</h3>
          <span class="text-xs text-slate-500 ml-auto">{{ person.projects.length }} / {{ allProjects.length }}</span>
          <button
            @click="showAddProject = !showAddProject"
            class="flex items-center gap-1 px-2 py-1 text-xs text-emerald-400 hover:text-emerald-300 hover:bg-emerald-500/10 border border-emerald-500/30 rounded-lg transition"
          >
            <Plus class="w-3.5 h-3.5" />
            新增專案
          </button>
        </div>

        <!-- Add project dropdown -->
        <div v-if="showAddProject" class="flex items-center gap-2 p-3 bg-slate-900/80 rounded-xl border border-slate-600">
          <select
            v-model.number="addingProjectId"
            class="flex-1 px-3 py-1.5 bg-slate-800 text-slate-200 border border-slate-600 rounded-lg text-sm [color-scheme:dark]"
          >
            <option :value="null" disabled>選擇專案...</option>
            <option v-for="p in availableProjects()" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
          <button
            @click="addProject"
            :disabled="!addingProjectId"
            class="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-xs rounded-lg transition-colors"
          >
            加入
          </button>
          <button
            @click="showAddProject = false; addingProjectId = null"
            class="p-1.5 text-slate-400 hover:text-slate-200 transition"
          >
            <X class="w-4 h-4" />
          </button>
        </div>

        <div v-if="person.projects.length === 0 && !showAddProject" class="text-center py-6 text-slate-500 text-sm">
          無專案權限設定（可存取所有專案）
        </div>

        <div v-else class="space-y-2">
          <div
            v-for="pp in person.projects"
            :key="pp.id"
            class="px-4 py-3 bg-slate-900/50 rounded-xl border border-slate-700/50"
          >
            <div class="flex items-center gap-2 mb-2">
              <span class="text-sm text-slate-200 font-medium">{{ getProjectName(pp.project_id) }}</span>
              <label class="flex items-center gap-1 ml-2 cursor-pointer">
                <input
                  type="checkbox"
                  :checked="pp.is_default"
                  @change="togglePermission(pp, 'is_default', !pp.is_default)"
                  class="rounded bg-slate-700 border-slate-600 text-amber-500 focus:ring-amber-500 w-3 h-3"
                />
                <span class="text-[10px] text-amber-400">預設</span>
              </label>
              <button
                @click="removeProject(pp.project_id)"
                class="ml-auto p-1 text-slate-500 hover:text-red-400 transition"
                title="移除專案"
              >
                <X class="w-4 h-4" />
              </button>
            </div>
            <div class="flex flex-wrap gap-3">
              <label class="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  :checked="pp.can_view"
                  @change="togglePermission(pp, 'can_view', !pp.can_view)"
                  class="rounded bg-slate-700 border-slate-600 text-emerald-500 focus:ring-emerald-500 w-3.5 h-3.5"
                />
                <span class="text-xs text-slate-400">查看</span>
              </label>
              <label class="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  :checked="pp.can_create_card"
                  @change="togglePermission(pp, 'can_create_card', !pp.can_create_card)"
                  class="rounded bg-slate-700 border-slate-600 text-emerald-500 focus:ring-emerald-500 w-3.5 h-3.5"
                />
                <span class="text-xs text-slate-400">建卡</span>
              </label>
              <label class="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  :checked="pp.can_run_task"
                  @change="togglePermission(pp, 'can_run_task', !pp.can_run_task)"
                  class="rounded bg-slate-700 border-slate-600 text-emerald-500 focus:ring-emerald-500 w-3.5 h-3.5"
                />
                <span class="text-xs text-slate-400">執行</span>
              </label>
              <label class="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  :checked="pp.can_access_sensitive"
                  @change="togglePermission(pp, 'can_access_sensitive', !pp.can_access_sensitive)"
                  class="rounded bg-slate-700 border-slate-600 text-emerald-500 focus:ring-emerald-500 w-3.5 h-3.5"
                />
                <span class="text-xs text-slate-400">敏感</span>
              </label>
            </div>
          </div>
        </div>
      </div>

      <!-- Section 6: 危險區域 -->
      <div class="bg-slate-800/50 rounded-2xl border border-red-500/20 p-6 space-y-4">
        <div class="flex items-center gap-2">
          <AlertTriangle class="w-4 h-4 text-red-400" />
          <h3 class="text-sm font-bold text-red-400 uppercase tracking-wider">危險區域</h3>
        </div>
        <div class="flex items-center justify-between">
          <div>
            <span class="text-sm text-slate-300">刪除用戶</span>
            <p class="text-xs text-slate-500">刪除此用戶及其邀請碼、專案權限。已綁定的平台帳號不會被刪除，但會解除關聯。</p>
          </div>
          <button
            @click="confirmDelete = true"
            class="flex items-center gap-2 px-4 py-2 text-red-400 hover:text-red-300 hover:bg-red-500/10 border border-red-500/30 rounded-lg transition text-sm"
          >
            <Trash2 class="w-4 h-4" />
            刪除用戶
          </button>
        </div>
      </div>
    </template>

    <!-- Confirm Delete -->
    <ConfirmDialog
      :show="confirmDelete"
      title="刪除用戶"
      :message="`確定要刪除「${form.display_name}」？關聯的邀請碼和專案權限也會移除。`"
      confirm-text="刪除"
      @confirm="doDelete"
      @cancel="confirmDelete = false"
    />
  </div>
</template>
