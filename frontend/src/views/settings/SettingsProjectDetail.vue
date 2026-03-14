<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, FolderOpen, Loader2, Trash2, FolderInput, Plus, Edit3, Eye, EyeOff, KeyRound, Save } from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { config } from '../../config'
import { authHeaders } from '../../utils/authFetch'

const route = useRoute()
const router = useRouter()
const store = useAegisStore()
const API = config.apiUrl

const projectId = Number(route.params.id)
const loading = ref(true)
const saving = ref(false)

// ── Project form ──
interface MemberOption {
  id: number
  name: string
  avatar: string
  provider: string
}

const form = ref({
  name: '',
  path: '',
  default_member_id: null as number | null,
  is_system: false,
  is_active: true,
})
const members = ref<MemberOption[]>([])

// Relocate
const showRelocate = ref(false)
const relocatePath = ref('')
const relocateSaving = ref(false)
const confirmRelocate = ref(false)

// Delete
const confirmDelete = ref(false)

async function fetchProject() {
  try {
    const res = await fetch(`${API}/api/v1/projects/`)
    if (!res.ok) throw new Error('載入失敗')
    const projects = await res.json()
    const p = projects.find((p: any) => p.id === projectId)
    if (!p) {
      store.addToast('專案不存在', 'error')
      router.push('/settings/projects')
      return
    }
    form.value = {
      name: p.name,
      path: p.path,
      default_member_id: p.default_member_id,
      is_system: p.is_system,
      is_active: p.is_active,
    }
  } catch (e: any) {
    store.addToast(e.message || '載入失敗', 'error')
  }
}

async function fetchMembers() {
  try {
    const res = await fetch(`${API}/api/v1/members`)
    if (res.ok) members.value = await res.json()
  } catch {}
}

async function saveProject() {
  if (!form.value.name.trim()) return
  saving.value = true
  try {
    const res = await fetch(`${API}/api/v1/projects/${projectId}`, {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        name: form.value.name,
        default_member_id: form.value.default_member_id,
        is_active: form.value.is_active,
      }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '儲存失敗' }))
      throw new Error(err.detail)
    }
    store.addToast('專案已更新', 'success')
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
  saving.value = false
}

async function doRelocate() {
  if (!relocatePath.value.trim()) return
  relocateSaving.value = true
  try {
    const res = await fetch(`${API}/api/v1/projects/${projectId}/relocate`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ new_path: relocatePath.value.trim() }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '搬移失敗' }))
      throw new Error(err.detail)
    }
    store.addToast('專案目錄已搬移', 'success')
    showRelocate.value = false
    await fetchProject()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
  relocateSaving.value = false
}

async function doDelete() {
  try {
    const res = await fetch(`${API}/api/v1/projects/${projectId}`, {
      method: 'DELETE',
      headers: authHeaders(),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '刪除失敗' }))
      throw new Error(err.detail)
    }
    store.addToast('專案已刪除', 'success')
    router.push('/settings/projects')
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}

// ── Environment Variables ──
interface EnvVar {
  id: number
  project_id: number
  key: string
  value: string
  is_secret: boolean
  description: string | null
}

const envVars = ref<EnvVar[]>([])
const envLoading = ref(false)
const envSaving = ref(false)
const envNewKey = ref('')
const envNewValue = ref('')
const envNewSecret = ref(true)
const envNewDesc = ref('')
const envEditingId = ref<number | null>(null)
const envEditKey = ref('')
const envEditValue = ref('')
const envEditSecret = ref(true)
const envEditDesc = ref('')
const envRevealIds = ref<Set<number>>(new Set())

async function fetchEnvVars() {
  envLoading.value = true
  try {
    const res = await fetch(`${API}/api/v1/projects/${projectId}/env-vars`)
    if (res.ok) envVars.value = await res.json()
  } catch {
    store.addToast('載入環境變數失敗', 'error')
  }
  envLoading.value = false
}

async function addEnvVar() {
  if (!envNewKey.value.trim()) return
  envSaving.value = true
  try {
    const res = await fetch(`${API}/api/v1/projects/${projectId}/env-vars`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        key: envNewKey.value.trim(),
        value: envNewValue.value,
        is_secret: envNewSecret.value,
        description: envNewDesc.value || null,
      }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || '新增失敗')
    }
    envNewKey.value = ''
    envNewValue.value = ''
    envNewSecret.value = true
    envNewDesc.value = ''
    await fetchEnvVars()
    store.addToast('環境變數已新增', 'success')
  } catch (e: any) {
    store.addToast(e.message || '新增失敗', 'error')
  }
  envSaving.value = false
}

function startEditEnv(v: EnvVar) {
  envEditingId.value = v.id
  envEditKey.value = v.key
  envEditValue.value = v.is_secret ? '' : v.value
  envEditSecret.value = v.is_secret
  envEditDesc.value = v.description || ''
}

function cancelEditEnv() {
  envEditingId.value = null
}

async function saveEditEnv() {
  if (envEditingId.value === null) return
  envSaving.value = true
  try {
    const body: Record<string, any> = {
      key: envEditKey.value.trim(),
      is_secret: envEditSecret.value,
      description: envEditDesc.value || null,
    }
    if (envEditValue.value) {
      body.value = envEditValue.value
    }
    const res = await fetch(`${API}/api/v1/projects/${projectId}/env-vars/${envEditingId.value}`, {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || '更新失敗')
    }
    envEditingId.value = null
    await fetchEnvVars()
    store.addToast('環境變數已更新', 'success')
  } catch (e: any) {
    store.addToast(e.message || '更新失敗', 'error')
  }
  envSaving.value = false
}

async function deleteEnvVar(varId: number) {
  try {
    const res = await fetch(`${API}/api/v1/projects/${projectId}/env-vars/${varId}`, {
      method: 'DELETE',
      headers: authHeaders(),
    })
    if (!res.ok) throw new Error('刪除失敗')
    await fetchEnvVars()
    store.addToast('已刪除', 'success')
  } catch {
    store.addToast('刪除失敗', 'error')
  }
}

function toggleReveal(varId: number) {
  if (envRevealIds.value.has(varId)) {
    envRevealIds.value.delete(varId)
  } else {
    envRevealIds.value.add(varId)
  }
}

onMounted(async () => {
  await Promise.all([fetchProject(), fetchMembers(), fetchEnvVars()])
  loading.value = false
})
</script>

<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex items-center gap-3">
      <button
        @click="router.push('/settings/projects')"
        class="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 rounded-lg transition-colors"
      >
        <ArrowLeft class="w-5 h-5" />
      </button>
      <h2 class="text-xl font-semibold text-slate-200">{{ form.name || '專案設定' }}</h2>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex justify-center py-12">
      <Loader2 class="w-8 h-8 animate-spin text-slate-400" />
    </div>

    <template v-else>
      <!-- ═══ Section 1: 基本設定 ═══ -->
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-6 space-y-4">
        <h3 class="text-sm font-bold text-slate-300 uppercase tracking-wider">基本設定</h3>

        <!-- Name -->
        <div>
          <label class="block text-sm text-slate-400 mb-1">專案名稱</label>
          <input
            v-model="form.name"
            type="text"
            class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500"
            :disabled="form.is_system"
          />
        </div>

        <!-- Path -->
        <div>
          <label class="block text-sm text-slate-400 mb-1">專案路徑</label>
          <div class="flex items-center gap-2">
            <div class="flex-1 flex items-center gap-2 px-3 py-2 bg-slate-900/50 text-slate-400 border border-slate-700 rounded-lg text-sm">
              <FolderOpen class="w-4 h-4 shrink-0" />
              <span class="truncate">{{ form.path }}</span>
            </div>
            <button
              v-if="!form.is_system"
              @click="showRelocate = !showRelocate; relocatePath = form.path"
              class="p-2 text-slate-400 hover:text-emerald-400 hover:bg-slate-700 rounded-lg transition"
              title="搬移目錄"
            >
              <FolderInput class="w-4 h-4" />
            </button>
          </div>
        </div>

        <!-- Relocate Panel -->
        <div v-if="showRelocate" class="bg-slate-900/80 rounded-lg border border-slate-600 p-3 space-y-2">
          <label class="block text-sm text-slate-400">搬移至新路徑</label>
          <input
            v-model="relocatePath"
            type="text"
            class="w-full px-3 py-2 bg-slate-950 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500"
          />
          <div class="flex justify-end gap-2">
            <button @click="showRelocate = false" class="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-200">取消</button>
            <button
              @click="confirmRelocate = true"
              :disabled="relocateSaving || !relocatePath.trim() || relocatePath.trim() === form.path"
              class="flex items-center gap-1 px-3 py-1.5 text-sm bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded-lg transition"
            >
              <Loader2 v-if="relocateSaving" class="w-3 h-3 animate-spin" />
              搬移
            </button>
          </div>
        </div>

        <!-- Default Member -->
        <div>
          <label class="block text-sm text-slate-400 mb-1">預設成員</label>
          <select
            v-model="form.default_member_id"
            class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500"
          >
            <option :value="null">無（使用全域設定）</option>
            <option v-for="m in members" :key="m.id" :value="m.id">
              {{ m.avatar }} {{ m.name }} ({{ m.provider }})
            </option>
          </select>
          <p class="text-xs text-slate-500 mt-1">列表沒有指派成員時使用</p>
        </div>

        <!-- Active toggle -->
        <div v-if="!form.is_system" class="flex items-center justify-between">
          <div>
            <span class="text-sm text-slate-300">專案狀態</span>
            <p class="text-xs text-slate-500">停用後不會出現在選單和看板中</p>
          </div>
          <button
            @click="form.is_active = !form.is_active"
            :class="[
              'px-3 py-1.5 text-sm rounded-lg transition',
              form.is_active
                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                : 'bg-red-500/10 text-red-400 border border-red-500/30'
            ]"
          >
            {{ form.is_active ? '啟用中' : '已停用' }}
          </button>
        </div>

        <!-- Save / Delete actions -->
        <div class="flex items-center justify-between pt-2 border-t border-slate-700/50">
          <button
            v-if="!form.is_system"
            @click="confirmDelete = true"
            class="flex items-center gap-2 px-4 py-2 text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg transition text-sm"
          >
            <Trash2 class="w-4 h-4" />
            刪除專案
          </button>
          <div v-else></div>
          <button
            @click="saveProject"
            :disabled="saving || !form.name.trim()"
            class="flex items-center gap-2 px-5 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded-lg transition text-sm"
          >
            <Loader2 v-if="saving" class="w-4 h-4 animate-spin" />
            <Save v-else class="w-4 h-4" />
            儲存
          </button>
        </div>
      </div>

      <!-- ═══ Section 2: 環境變數 ═══ -->
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-6 space-y-4">
        <div class="flex items-center gap-2">
          <KeyRound class="w-4 h-4 text-amber-400" />
          <h3 class="text-sm font-bold text-slate-300 uppercase tracking-wider">環境變數</h3>
        </div>
        <p class="text-xs text-slate-500">
          設定的環境變數會在 AI 任務執行時自動注入 subprocess。Secret 變數值在前端不會顯示。
        </p>

        <!-- Loading -->
        <div v-if="envLoading" class="flex justify-center py-6">
          <Loader2 class="w-6 h-6 animate-spin text-slate-400" />
        </div>

        <!-- Env Var List -->
        <div v-else class="space-y-2">
          <div
            v-for="v in envVars"
            :key="v.id"
            class="bg-slate-900/50 rounded-lg border border-slate-700/50 p-3"
          >
            <!-- View Mode -->
            <div v-if="envEditingId !== v.id" class="flex items-center gap-3">
              <code class="text-sm text-amber-300 font-mono flex-shrink-0">{{ v.key }}</code>
              <span class="text-slate-500">=</span>
              <span class="text-sm text-slate-300 flex-1 truncate font-mono">
                {{ v.is_secret && !envRevealIds.has(v.id) ? '••••••' : v.value }}
              </span>
              <button
                v-if="v.is_secret"
                @click="toggleReveal(v.id)"
                class="p-1 text-slate-500 hover:text-slate-300"
                :title="envRevealIds.has(v.id) ? '隱藏' : '顯示'"
              >
                <EyeOff v-if="envRevealIds.has(v.id)" class="w-4 h-4" />
                <Eye v-else class="w-4 h-4" />
              </button>
              <button @click="startEditEnv(v)" class="p-1 text-slate-500 hover:text-slate-300" title="編輯">
                <Edit3 class="w-4 h-4" />
              </button>
              <button @click="deleteEnvVar(v.id)" class="p-1 text-slate-500 hover:text-red-400" title="刪除">
                <Trash2 class="w-4 h-4" />
              </button>
            </div>
            <!-- Edit Mode -->
            <div v-else class="space-y-2">
              <div class="grid grid-cols-2 gap-2">
                <input v-model="envEditKey" placeholder="KEY" class="px-3 py-1.5 bg-slate-800 border border-slate-600 rounded text-sm font-mono" />
                <input v-model="envEditValue" :placeholder="v.is_secret ? '（留空保持不變）' : 'value'" class="px-3 py-1.5 bg-slate-800 border border-slate-600 rounded text-sm font-mono" />
              </div>
              <div class="flex items-center gap-4">
                <label class="flex items-center gap-2 text-xs text-slate-400">
                  <input type="checkbox" v-model="envEditSecret" class="rounded" />
                  Secret
                </label>
                <input v-model="envEditDesc" placeholder="說明（選填）" class="flex-1 px-3 py-1 bg-slate-800 border border-slate-600 rounded text-xs" />
                <button @click="saveEditEnv" :disabled="envSaving" class="px-3 py-1 text-xs bg-emerald-600 hover:bg-emerald-500 rounded transition">儲存</button>
                <button @click="cancelEditEnv" class="px-3 py-1 text-xs bg-slate-700 hover:bg-slate-600 rounded transition">取消</button>
              </div>
            </div>
            <!-- Description -->
            <div v-if="v.description && envEditingId !== v.id" class="text-xs text-slate-500 mt-1">{{ v.description }}</div>
          </div>

          <!-- Empty -->
          <div v-if="envVars.length === 0" class="text-center py-6 text-slate-500 text-sm">
            尚無環境變數
          </div>
        </div>

        <!-- Add New -->
        <div class="border-t border-slate-700 pt-4 space-y-2">
          <div class="text-xs font-medium text-slate-400">新增環境變數</div>
          <div class="grid grid-cols-2 gap-2">
            <input v-model="envNewKey" placeholder="KEY_NAME" class="px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-sm font-mono" @keyup.enter="addEnvVar" />
            <input v-model="envNewValue" placeholder="value" class="px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-sm font-mono" @keyup.enter="addEnvVar" />
          </div>
          <div class="flex items-center gap-4">
            <label class="flex items-center gap-2 text-xs text-slate-400">
              <input type="checkbox" v-model="envNewSecret" class="rounded" />
              Secret（前端遮蔽值）
            </label>
            <input v-model="envNewDesc" placeholder="說明（選填）" class="flex-1 px-3 py-1.5 bg-slate-900 border border-slate-600 rounded-lg text-xs" />
          </div>
          <button
            @click="addEnvVar"
            :disabled="!envNewKey.trim() || envSaving"
            class="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm transition"
          >
            <Plus class="w-4 h-4" />
            新增
          </button>
        </div>
      </div>
    </template>

    <!-- Confirm Delete -->
    <ConfirmDialog
      v-model:show="confirmDelete"
      title="刪除專案"
      :message="`確定要刪除「${form.name}」？此操作會刪除所有相關的卡片和資料。`"
      confirm-text="刪除"
      @confirm="doDelete"
    />

    <!-- Confirm Relocate -->
    <ConfirmDialog
      v-model:show="confirmRelocate"
      title="搬移專案目錄"
      :message="`確定要將「${form.name}」搬移至\n${relocatePath}？`"
      confirm-text="搬移"
      @confirm="doRelocate"
    />
  </div>
</template>
