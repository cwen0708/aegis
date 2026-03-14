<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { UserCheck, Shield, Clock, Trash2, Edit3, Loader2, X, ChevronDown } from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { config } from '../../config'
import { authHeaders } from '../../utils/authFetch'

const store = useAegisStore()
const API = config.apiUrl

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

const loading = ref(true)
const users = ref<BotUserInfo[]>([])

// Edit dialog
const showEdit = ref(false)
const editUser = ref<BotUserInfo | null>(null)
const editForm = ref({
  level: 0,
  is_active: true,
  access_expires_at: '',
})
const saving = ref(false)

// Delete confirm
const confirmDelete = ref(false)
const deleteTarget = ref<BotUserInfo | null>(null)

async function fetchUsers() {
  loading.value = true
  try {
    const res = await fetch(`${API}/api/v1/bot-users`, { headers: authHeaders() })
    if (res.ok) users.value = await res.json()
  } catch {
    store.addToast('載入用戶失敗', 'error')
  }
  loading.value = false
}

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
  return colors[level] || colors[0]
}

function isExpired(u: BotUserInfo): boolean {
  if (!u.access_expires_at) return false
  return new Date(u.access_expires_at) <= new Date()
}

function formatDate(d: string | null): string {
  if (!d) return '-'
  return new Date(d).toLocaleDateString('zh-TW', { year: 'numeric', month: '2-digit', day: '2-digit' })
}

function openEdit(u: BotUserInfo) {
  editUser.value = u
  editForm.value = {
    level: u.level,
    is_active: u.is_active,
    access_expires_at: u.access_expires_at ? u.access_expires_at.split('T')[0] : '',
  }
  showEdit.value = true
}

async function saveEdit() {
  if (!editUser.value) return
  saving.value = true
  try {
    const body: Record<string, unknown> = {
      level: editForm.value.level,
      is_active: editForm.value.is_active,
    }
    body.access_expires_at = editForm.value.access_expires_at
      ? new Date(editForm.value.access_expires_at).toISOString()
      : ''
    const res = await fetch(`${API}/api/v1/bot-users/${editUser.value.id}`, {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    })
    if (!res.ok) throw new Error('更新失敗')
    showEdit.value = false
    await fetchUsers()
    store.addToast('用戶已更新', 'success')
  } catch (e: any) {
    store.addToast(e.message || '更新失敗', 'error')
  }
  saving.value = false
}

async function doDelete() {
  if (!deleteTarget.value) return
  try {
    const res = await fetch(`${API}/api/v1/bot-users/${deleteTarget.value.id}`, {
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

onMounted(fetchUsers)
</script>

<template>
  <div class="space-y-4">
    <!-- Loading -->
    <div v-if="loading" class="flex justify-center py-12">
      <Loader2 class="w-8 h-8 animate-spin text-slate-400" />
    </div>

    <!-- User List -->
    <div v-else class="space-y-3">
      <div
        v-for="u in users"
        :key="u.id"
        class="bg-slate-900/50 rounded-xl border border-slate-700/50 p-4"
        :class="{ 'opacity-50': !u.is_active }"
      >
        <div class="flex items-center justify-between">
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="font-medium text-slate-200">{{ u.username || u.platform_user_id }}</span>
              <span :class="['px-2 py-0.5 text-xs rounded border', levelColor(u.level)]">
                {{ levelLabel(u.level) }}
              </span>
              <span class="text-xs text-slate-500 bg-slate-800 px-1.5 py-0.5 rounded">{{ u.platform }}</span>
              <span v-if="!u.is_active" class="px-2 py-0.5 text-xs rounded bg-red-500/20 text-red-400 border border-red-500/30">
                已封鎖
              </span>
              <span v-if="isExpired(u)" class="px-2 py-0.5 text-xs rounded bg-orange-500/20 text-orange-400 border border-orange-500/30">
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
              @click="openEdit(u)"
              class="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-700 rounded-lg transition"
              title="編輯"
            >
              <Edit3 class="w-4 h-4" />
            </button>
            <button
              @click="deleteTarget = u; confirmDelete = true"
              class="p-2 text-slate-400 hover:text-red-400 hover:bg-slate-700 rounded-lg transition"
              title="刪除"
            >
              <Trash2 class="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      <div v-if="users.length === 0" class="text-center py-12 text-slate-500">
        尚無已驗證的 Bot 用戶
      </div>
    </div>

    <!-- Edit Dialog -->
    <Teleport to="body">
      <div
        v-if="showEdit && editUser"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
        @click.self="showEdit = false"
      >
        <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-md p-6 space-y-4">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-bold text-slate-200">
              編輯用戶 — {{ editUser.username || editUser.platform_user_id }}
            </h3>
            <button @click="showEdit = false" class="text-slate-400 hover:text-slate-200">
              <X class="w-5 h-5" />
            </button>
          </div>

          <!-- Level -->
          <div>
            <label class="block text-sm text-slate-400 mb-1">權限等級</label>
            <select
              v-model.number="editForm.level"
              class="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-sm"
            >
              <option :value="0">L0 — 未驗證</option>
              <option :value="1">L1 — 訪客（唯讀）</option>
              <option :value="2">L2 — 成員（可執行任務）</option>
              <option :value="3">L3 — 管理員</option>
            </select>
          </div>

          <!-- Active -->
          <div class="flex items-center gap-3">
            <label class="text-sm text-slate-400">帳號狀態</label>
            <button
              @click="editForm.is_active = !editForm.is_active"
              :class="[
                'relative inline-flex h-6 w-11 items-center rounded-full transition-colors',
                editForm.is_active ? 'bg-emerald-600' : 'bg-slate-600'
              ]"
            >
              <span
                :class="[
                  'inline-block h-4 w-4 transform rounded-full bg-white transition-transform',
                  editForm.is_active ? 'translate-x-6' : 'translate-x-1'
                ]"
              />
            </button>
            <span class="text-sm" :class="editForm.is_active ? 'text-emerald-400' : 'text-red-400'">
              {{ editForm.is_active ? '啟用' : '封鎖' }}
            </span>
          </div>

          <!-- Expires -->
          <div>
            <label class="block text-sm text-slate-400 mb-1">存取到期日</label>
            <input
              v-model="editForm.access_expires_at"
              type="date"
              class="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-sm"
            />
            <p class="text-[11px] text-slate-600 mt-1">留空表示永不過期。過期後用戶無法對話，但資料保留。</p>
          </div>

          <!-- Actions -->
          <div class="flex justify-end gap-2 pt-2">
            <button
              @click="showEdit = false"
              class="px-4 py-2 text-sm bg-slate-700 hover:bg-slate-600 rounded-lg transition"
            >
              取消
            </button>
            <button
              @click="saveEdit"
              :disabled="saving"
              class="px-4 py-2 text-sm bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded-lg transition"
            >
              儲存
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Confirm Delete -->
    <ConfirmDialog
      v-model:show="confirmDelete"
      title="刪除用戶"
      :message="`確定要刪除「${deleteTarget?.username || deleteTarget?.platform_user_id}」？\n此操作會刪除該用戶的所有對話記錄和權限設定。`"
      confirm-text="刪除"
      @confirm="doDelete"
    />
  </div>
</template>
