<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  Plus, Copy, Loader2, Clock, ChevronRight, UserPlus, X,
  Eye, PenTool, Play, Shield,
} from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import { useAegisStore } from '../../stores/aegis'
import { config } from '../../config'
import { authHeaders } from '../../utils/authFetch'

const router = useRouter()
const store = useAegisStore()
const API = config.apiUrl

// ─── Types ──────────────────────────────────────────────

interface BotUserInfo {
  id: number
  platform: string
  username: string | null
  platform_user_id: string
  last_active_at: string | null
}

interface InviteCodeInfo {
  id: number
  code: string
  status: string
  used_count: number
  max_uses: number
}

interface PersonProjectInfo {
  id: number
  project_id: number
  display_name: string
  can_view: boolean
  can_create_card: boolean
  can_run_task: boolean
}

interface PersonItem {
  id: number
  display_name: string
  description: string
  level: number
  created_at: string
  status: 'active' | 'pending'
  bot_users: BotUserInfo[]
  invite_codes: InviteCodeInfo[]
  projects: PersonProjectInfo[]
}

interface ProjectOption { id: number; name: string }
interface MemberOption { id: number; name: string; avatar: string }

// ─── Data ──────────────────────────────────────────────

const loading = ref(true)
const persons = ref<PersonItem[]>([])
const projects = ref<ProjectOption[]>([])
const members = ref<MemberOption[]>([])

// ─── Create Dialog ──────────────────────────────────────

const showCreateDialog = ref(false)
const saving = ref(false)
const createForm = ref({
  display_name: '',
  description: '',
  target_level: 1,
  target_member_id: null as number | null,
  allowed_projects: [] as number[],
  default_can_view: true,
  default_can_create_card: false,
  default_can_run_task: false,
  default_can_access_sensitive: false,
  expires_days: 30 as number | null,
  note: '',
})

const permissionTemplates = [
  { name: '訪客', can_view: true, can_create_card: false, can_run_task: false, can_access_sensitive: false },
  { name: '成員', can_view: true, can_create_card: true, can_run_task: true, can_access_sensitive: false },
  { name: '管理員', can_view: true, can_create_card: true, can_run_task: true, can_access_sensitive: true },
]

function applyTemplate(t: typeof permissionTemplates[0]) {
  createForm.value.default_can_view = t.can_view
  createForm.value.default_can_create_card = t.can_create_card
  createForm.value.default_can_run_task = t.can_run_task
  createForm.value.default_can_access_sensitive = t.can_access_sensitive
}

// ─── Fetch ──────────────────────────────────────────────

async function fetchPersons() {
  loading.value = true
  try {
    const res = await fetch(`${API}/api/v1/persons`, { headers: authHeaders() })
    if (res.ok) persons.value = await res.json()
  } catch {
    store.addToast('載入用戶失敗', 'error')
  }
  loading.value = false
}

async function fetchProjects() {
  try {
    const res = await fetch(`${API}/api/v1/projects/?all=true`, { headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      projects.value = data.map((p: any) => ({ id: p.id, name: p.name }))
    }
  } catch {}
}

async function fetchMembers() {
  try {
    const res = await fetch(`${API}/api/v1/members?all=true`, { headers: authHeaders() })
    if (res.ok) members.value = await res.json()
  } catch {}
}

// ─── Create ──────────────────────────────────────────────

function openCreateDialog() {
  createForm.value = {
    display_name: '',
    description: '',
    target_level: 1,
    target_member_id: null,
    allowed_projects: [],
    default_can_view: true,
    default_can_create_card: false,
    default_can_run_task: false,
    default_can_access_sensitive: false,
    expires_days: 30,
    note: '',
  }
  showCreateDialog.value = true
}

async function createPerson() {
  saving.value = true
  try {
    const body = {
      display_name: createForm.value.display_name,
      description: createForm.value.description,
      target_level: createForm.value.target_level,
      target_member_id: createForm.value.target_member_id,
      allowed_projects: createForm.value.allowed_projects.length > 0 ? createForm.value.allowed_projects : undefined,
      default_can_view: createForm.value.default_can_view,
      default_can_create_card: createForm.value.default_can_create_card,
      default_can_run_task: createForm.value.default_can_run_task,
      default_can_access_sensitive: createForm.value.default_can_access_sensitive,
      expires_days: createForm.value.expires_days,
      note: createForm.value.note,
    }
    const res = await fetch(`${API}/api/v1/persons`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '建立失敗' }))
      throw new Error(err.detail)
    }
    store.addToast('用戶已建立', 'success')
    showCreateDialog.value = false
    await fetchPersons()
  } catch (e: any) {
    store.addToast(e.message || '建立失敗', 'error')
  }
  saving.value = false
}

// ─── Helpers ─────────────────────────────────────────────

function levelLabel(level: number): string {
  const labels: Record<number, string> = { 0: '未驗證', 1: '訪客', 2: '成員', 3: '管理員' }
  return labels[level] || `L${level}`
}

function levelColor(level: number): string {
  const colors: Record<number, string> = {
    0: 'text-slate-500 bg-slate-500/10 border-slate-500/30',
    1: 'text-sky-400 bg-sky-500/10 border-sky-500/30',
    2: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
    3: 'text-amber-400 bg-amber-500/10 border-amber-500/30',
  }
  return colors[level] ?? colors[0] ?? ''
}

function platformIcon(platform: string): string {
  const icons: Record<string, string> = {
    telegram: 'TG',
    line: 'LINE',
    discord: 'DC',
    web: 'WEB',
  }
  return icons[platform] || platform.toUpperCase()
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleDateString('zh-TW', { year: 'numeric', month: '2-digit', day: '2-digit' })
}

async function copyCode(code: string, event: Event) {
  event.stopPropagation()
  try {
    await navigator.clipboard.writeText(code)
    store.addToast('已複製邀請碼', 'success')
  } catch {
    store.addToast('複製失敗', 'error')
  }
}

// ─── Init ───────────────────────────────────────────────

onMounted(() => {
  fetchPersons()
  fetchProjects()
  fetchMembers()
})
</script>

<template>
  <div class="space-y-6">
    <!-- Header Actions -->
    <Teleport to="#settings-header-actions">
      <button
        @click="openCreateDialog()"
        class="flex items-center gap-1.5 px-3 py-1.5 bg-sky-600 hover:bg-sky-500 rounded-lg text-xs font-medium transition"
      >
        <Plus class="w-3.5 h-3.5" />
        新增用戶
      </button>
    </Teleport>

    <!-- Loading -->
    <div v-if="loading" class="flex justify-center py-12">
      <Loader2 class="w-6 h-6 animate-spin text-slate-400" />
    </div>

    <!-- Person List -->
    <div v-else class="space-y-3">
      <div v-if="persons.length === 0" class="text-center py-12 text-slate-500 text-sm">
        尚無用戶，點擊「新增用戶」建立第一位
      </div>

      <div
        v-for="p in persons"
        :key="p.id"
        @click="router.push(`/settings/users/${p.id}`)"
        class="rounded-xl border p-4 cursor-pointer hover:border-slate-600/50 transition-all"
        :class="p.status === 'active'
          ? 'bg-slate-800/50 border-slate-700/50 hover:bg-slate-700/30'
          : 'bg-slate-800/30 border-dashed border-slate-700/40 opacity-60 hover:opacity-80 hover:bg-slate-700/20'"
      >
        <div class="flex items-center gap-4">
          <!-- Info -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="font-medium text-slate-200">{{ p.display_name || '(未命名)' }}</span>
              <span :class="['px-2 py-0.5 text-xs rounded border', levelColor(p.level)]">
                {{ levelLabel(p.level) }}
              </span>
              <span
                v-if="p.status === 'active'"
                class="px-2 py-0.5 text-xs rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
              >
                已綁定
              </span>
              <span
                v-else
                class="px-2 py-0.5 text-xs rounded bg-slate-500/20 text-slate-400 border border-slate-500/30"
              >
                待驗證
              </span>
            </div>

            <div v-if="p.description" class="text-xs text-slate-500 mt-1 truncate">{{ p.description }}</div>

            <!-- Bot Users -->
            <div v-if="p.bot_users.length > 0" class="flex flex-wrap gap-1.5 mt-2">
              <span
                v-for="bu in p.bot_users"
                :key="bu.id"
                class="text-[10px] px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-400 border border-sky-500/20"
              >
                {{ platformIcon(bu.platform) }} {{ bu.username || bu.platform_user_id }}
              </span>
            </div>

            <!-- Invite Code (for pending) -->
            <div v-if="p.status === 'pending' && p.invite_codes.length > 0" class="flex items-center gap-2 mt-2">
              <code class="px-2 py-0.5 bg-slate-800 rounded text-sky-300 font-mono text-xs">
                {{ p.invite_codes[0]!.code }}
              </code>
              <button
                @click="copyCode(p.invite_codes[0]!.code, $event)"
                class="p-0.5 text-slate-400 hover:text-slate-200 transition"
                title="複製邀請碼"
              >
                <Copy class="w-3.5 h-3.5" />
              </button>
            </div>

            <!-- Meta -->
            <div class="flex items-center gap-4 mt-1.5 text-xs text-slate-500">
              <span>建立: {{ formatDate(p.created_at) }}</span>
              <span v-if="p.bot_users.some(bu => bu.last_active_at)">
                <Clock class="w-3 h-3 inline" />
                最後活躍: {{ formatDate(p.bot_users.filter(bu => bu.last_active_at).sort((a, b) => new Date(b.last_active_at!).getTime() - new Date(a.last_active_at!).getTime())[0]?.last_active_at ?? null) }}
              </span>
            </div>
          </div>

          <!-- Arrow -->
          <ChevronRight class="w-4 h-4 text-slate-600 shrink-0" />
        </div>
      </div>
    </div>

    <!-- Create Person Dialog -->
    <Teleport to="body">
      <div
        v-if="showCreateDialog"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
        @click.self="showCreateDialog = false"
      >
        <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-lg p-6 space-y-4 max-h-[90vh] overflow-y-auto">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-bold text-slate-200">
              <UserPlus class="w-4 h-4 inline mr-1" />
              新增用戶
            </h3>
            <button @click="showCreateDialog = false" class="text-slate-400 hover:text-slate-200">
              <X class="w-5 h-5" />
            </button>
          </div>

          <div class="space-y-4">
            <div>
              <label class="block text-sm text-slate-400 mb-1">顯示名稱</label>
              <input
                v-model="createForm.display_name"
                type="text"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-sky-500 placeholder-slate-500"
                placeholder="如：王小華"
              />
            </div>

            <div>
              <label class="block text-sm text-slate-400 mb-1">身份描述（AI 會參考）</label>
              <textarea
                v-model="createForm.description"
                rows="2"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-sky-500 placeholder-slate-500 resize-none"
                placeholder="如：案場業主，可查看發電資料和維運進度"
              />
            </div>

            <div>
              <label class="block text-sm text-slate-400 mb-1">權限等級</label>
              <select
                v-model="createForm.target_level"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg [color-scheme:dark]"
              >
                <option :value="1">L1 一般用戶（查看、留言）</option>
                <option :value="2">L2 進階用戶（建卡、執行任務）</option>
                <option :value="3">L3 管理員（完整權限）</option>
              </select>
            </div>

            <div>
              <label class="block text-sm text-slate-400 mb-1">預設 AI 成員</label>
              <select
                v-model="createForm.target_member_id"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg [color-scheme:dark]"
              >
                <option :value="null">不指定</option>
                <option v-for="m in members" :key="m.id" :value="m.id">
                  {{ m.avatar || '' }} {{ m.name }}
                </option>
              </select>
            </div>

            <div v-if="projects.length > 0">
              <label class="block text-sm text-slate-400 mb-1">可存取專案</label>
              <div class="space-y-2 max-h-32 overflow-y-auto">
                <label
                  v-for="proj in projects"
                  :key="proj.id"
                  class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer hover:bg-slate-800"
                >
                  <input
                    type="checkbox"
                    :value="proj.id"
                    v-model="createForm.allowed_projects"
                    class="rounded bg-slate-700 border-slate-600 text-sky-500 focus:ring-sky-500"
                  />
                  <span class="text-sm text-slate-300">{{ proj.name }}</span>
                </label>
              </div>
              <p class="text-xs text-slate-500 mt-1">不勾選則可存取所有專案</p>
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
                    (createForm.default_can_view === t.can_view &&
                     createForm.default_can_create_card === t.can_create_card &&
                     createForm.default_can_run_task === t.can_run_task &&
                     createForm.default_can_access_sensitive === t.can_access_sensitive)
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
                <input type="checkbox" v-model="createForm.default_can_view" class="rounded bg-slate-700 border-slate-600 text-sky-500" />
                <Eye class="w-4 h-4 text-slate-400" />
                <span class="text-sm text-slate-300">查看卡片</span>
              </label>
              <label class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer">
                <input type="checkbox" v-model="createForm.default_can_create_card" class="rounded bg-slate-700 border-slate-600 text-sky-500" />
                <PenTool class="w-4 h-4 text-slate-400" />
                <span class="text-sm text-slate-300">建立卡片</span>
              </label>
              <label class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer">
                <input type="checkbox" v-model="createForm.default_can_run_task" class="rounded bg-slate-700 border-slate-600 text-sky-500" />
                <Play class="w-4 h-4 text-slate-400" />
                <span class="text-sm text-slate-300">執行任務</span>
              </label>
              <label class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer">
                <input type="checkbox" v-model="createForm.default_can_access_sensitive" class="rounded bg-slate-700 border-slate-600 text-sky-500" />
                <Shield class="w-4 h-4 text-slate-400" />
                <span class="text-sm text-slate-300">敏感資料</span>
              </label>
            </div>

            <div>
              <label class="block text-sm text-slate-400 mb-1">邀請碼有效天數</label>
              <input
                v-model.number="createForm.expires_days"
                type="number"
                min="1"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-sky-500 placeholder-slate-500"
                placeholder="留空則永不過期"
              />
            </div>

            <div>
              <label class="block text-sm text-slate-400 mb-1">備註</label>
              <input
                v-model="createForm.note"
                type="text"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-sky-500 placeholder-slate-500"
                placeholder="如：給客戶A用"
              />
            </div>
          </div>

          <div class="flex justify-end gap-3 pt-2">
            <button
              @click="showCreateDialog = false"
              class="px-4 py-2 text-slate-400 hover:text-slate-200 transition"
            >
              取消
            </button>
            <button
              @click="createPerson"
              :disabled="saving"
              class="flex items-center gap-2 px-4 py-2 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition"
            >
              <Loader2 v-if="saving" class="w-4 h-4 animate-spin" />
              建立
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
