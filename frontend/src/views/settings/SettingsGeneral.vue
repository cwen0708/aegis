<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Globe, Cpu, Save, Loader2, Lock, Sparkles, ShieldCheck, Github, CheckCircle2, Unplug } from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'
import { useAuthStore } from '../../stores/auth'

import { config } from '../../config'
import { authHeaders } from '../../utils/authFetch'

const store = useAegisStore()
const auth = useAuthStore()
const API = config.apiUrl

// Worker 暫停控制
const workerPaused = ref(false)
const workerToggling = ref(false)

async function fetchWorkerStatus() {
  try {
    const res = await fetch(`${API}/api/v1/system/services`)
    if (res.ok) {
      const data = await res.json()
      workerPaused.value = data.engines?.task_worker?.is_paused ?? false
    }
  } catch {}
}

async function toggleWorkerPaused() {
  workerToggling.value = true
  try {
    const endpoint = workerPaused.value ? 'resume' : 'pause'
    const res = await fetch(`${API}/api/v1/runner/${endpoint}`, { method: 'POST', headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      workerPaused.value = data.is_paused
      store.addToast(workerPaused.value ? 'Worker 已暫停' : 'Worker 已恢復', 'success')
    }
  } catch {
    store.addToast('操作失敗', 'error')
  } finally {
    workerToggling.value = false
  }
}

async function toggleLoginToView() {
  const newVal = !requireLoginToView.value
  try {
    await store.updateSettings({ require_login_to_view: String(newVal) })
    requireLoginToView.value = newVal
    auth.requireLoginToView = newVal
  } catch {
    store.addToast('設定失敗', 'error')
  }
}

const loading = ref(true)
const saving = ref(false)

const requireLoginToView = ref(false)

const form = ref({
  timezone: 'Asia/Taipei',
  max_workstations: '3',
  memory_short_term_days: '30',
  gemini_api_key: '',
})

// 密碼修改
const passwordForm = ref({
  current: '',
  new: '',
  confirm: '',
})
const passwordSaving = ref(false)
const passwordError = ref('')
const passwordSuccess = ref('')

async function changePassword() {
  passwordError.value = ''
  passwordSuccess.value = ''

  if (!passwordForm.value.current) {
    passwordError.value = '請輸入目前密碼'
    return
  }
  if (!passwordForm.value.new || passwordForm.value.new.length < 6) {
    passwordError.value = '新密碼至少需要 6 個字元'
    return
  }
  if (passwordForm.value.new !== passwordForm.value.confirm) {
    passwordError.value = '新密碼與確認密碼不符'
    return
  }

  passwordSaving.value = true
  try {
    const res = await fetch(`${API}/api/v1/auth/change-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        current_password: passwordForm.value.current,
        new_password: passwordForm.value.new,
      }),
    })
    const data = await res.json()
    if (res.ok) {
      passwordSuccess.value = '密碼已更新'
      passwordForm.value = { current: '', new: '', confirm: '' }
      // 清除 session，下次進入需重新驗證
      sessionStorage.removeItem('aegis-admin-auth')
    } else {
      passwordError.value = data.detail || '修改失敗'
    }
  } catch {
    passwordError.value = '修改失敗，請稍後再試'
  } finally {
    passwordSaving.value = false
  }
}

// GitHub 連線
const githubStatus = ref<{ connected: boolean; login?: string; name?: string; error?: string }>({ connected: false })
const githubToken = ref('')
const githubVerifying = ref(false)
const githubLoading = ref(true)

async function fetchGithubStatus() {
  githubLoading.value = true
  try {
    const res = await fetch(`${API}/api/v1/github/status`)
    if (res.ok) githubStatus.value = await res.json()
  } catch {}
  githubLoading.value = false
}

async function connectGithub() {
  if (!githubToken.value.trim()) return
  githubVerifying.value = true
  try {
    const res = await fetch(`${API}/api/v1/github/verify`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ token: githubToken.value.trim() }),
    })
    if (!res.ok) {
      const data = await res.json()
      store.addToast(data.detail || 'Token 無效', 'error')
      return
    }
    // 驗證成功，儲存 token
    await store.updateSettings({ github_pat: githubToken.value.trim() })
    githubToken.value = ''
    await fetchGithubStatus()
    store.addToast('GitHub 已連線', 'success')
  } catch {
    store.addToast('連線失敗', 'error')
  } finally {
    githubVerifying.value = false
  }
}

async function disconnectGithub() {
  await store.updateSettings({ github_pat: '' })
  githubStatus.value = { connected: false }
  store.addToast('GitHub 已斷開', 'info')
}

const timezoneOptions = [
  'Asia/Taipei',
  'Asia/Tokyo',
  'Asia/Shanghai',
  'Asia/Hong_Kong',
  'Asia/Singapore',
  'Asia/Seoul',
  'UTC',
  'America/New_York',
  'America/Los_Angeles',
  'Europe/London',
  'Europe/Berlin',
]

onMounted(async () => {
  await Promise.all([store.fetchSettings(), fetchWorkerStatus(), fetchGithubStatus()])
  form.value.timezone = store.settings.timezone || 'Asia/Taipei'
  form.value.max_workstations = store.settings.max_workstations || '3'
  form.value.memory_short_term_days = store.settings.memory_short_term_days || '30'
  form.value.gemini_api_key = store.settings.gemini_api_key || ''
  requireLoginToView.value = store.settings.require_login_to_view === 'true'
  loading.value = false
})

async function saveSettings() {
  saving.value = true
  try {
    await store.updateSettings({
      timezone: form.value.timezone,
      max_workstations: form.value.max_workstations,
      memory_short_term_days: form.value.memory_short_term_days,
      gemini_api_key: form.value.gemini_api_key,
    })
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="max-w-2xl space-y-6">
    <!-- 一般設定 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Globe class="w-4 h-4 text-emerald-400" />
          <h2 class="text-sm font-semibold text-slate-200">一般設定</h2>
          <Loader2 v-if="loading" class="w-4 h-4 text-slate-500 animate-spin ml-auto" />
        </div>
      </div>
      <div class="p-6 space-y-4">
        <div v-if="loading" class="text-sm text-slate-500">讀取中...</div>
        <div v-else>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">時區</label>
          <select
            v-model="form.timezone"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none text-sm"
          >
            <option v-for="tz in timezoneOptions" :key="tz" :value="tz">{{ tz }}</option>
          </select>
          <p class="text-[11px] text-slate-500 mt-1">排程時間、日誌時間戳記所使用的時區</p>
        </div>
      </div>
    </div>

    <!-- 執行設定 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Cpu class="w-4 h-4 text-blue-400" />
          <h2 class="text-sm font-semibold text-slate-200">執行設定</h2>
        </div>
      </div>
      <div class="p-6 space-y-4">
        <!-- Worker 暫停開關 -->
        <div class="flex items-center justify-between">
          <div>
            <label class="block text-xs font-medium text-slate-400">Worker 任務執行</label>
            <p class="text-[11px] text-slate-500 mt-0.5">暫停後 Worker 不會拾取新的 pending 卡片</p>
          </div>
          <button
            @click="toggleWorkerPaused"
            :disabled="workerToggling"
            :class="[
              'relative w-11 h-6 rounded-full transition-colors',
              workerPaused ? 'bg-red-500/60' : 'bg-emerald-500'
            ]"
          >
            <div
              :class="[
                'absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform shadow',
                workerPaused ? 'left-0.5' : 'left-5.5'
              ]"
            ></div>
          </button>
          <span :class="['text-xs font-medium ml-2 w-10', workerPaused ? 'text-red-400' : 'text-emerald-400']">
            {{ workerPaused ? '已暫停' : '運行中' }}
          </span>
        </div>

        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">工作台數量</label>
          <input
            v-model="form.max_workstations"
            type="number"
            min="1"
            max="10"
            class="w-32 bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none text-sm font-mono"
          />
          <p class="text-[11px] text-slate-500 mt-1">同時間可使用的工作台數量</p>
        </div>
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">短期記憶保留天數</label>
          <input
            v-model="form.memory_short_term_days"
            type="number"
            min="1"
            max="365"
            class="w-32 bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none text-sm font-mono"
          />
          <p class="text-[11px] text-slate-500 mt-1">AEGIS 系統短期記憶的保留天數，超過自動清理</p>
        </div>
      </div>
    </div>

    <!-- GitHub 連線 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Github class="w-4 h-4 text-slate-300" />
          <h2 class="text-sm font-semibold text-slate-200">GitHub 連線</h2>
          <Loader2 v-if="githubLoading" class="w-3.5 h-3.5 text-slate-500 animate-spin ml-auto" />
        </div>
      </div>
      <div class="p-6 space-y-4">
        <!-- 已連線 -->
        <div v-if="githubStatus.connected" class="flex items-center justify-between">
          <div class="flex items-center gap-3">
            <CheckCircle2 class="w-5 h-5 text-emerald-400" />
            <div>
              <div class="text-sm text-slate-200 font-medium">{{ githubStatus.login }}</div>
              <div v-if="githubStatus.name" class="text-[11px] text-slate-500">{{ githubStatus.name }}</div>
            </div>
          </div>
          <button @click="disconnectGithub" class="flex items-center gap-1.5 px-3 py-1.5 text-xs text-red-400 hover:bg-red-400/10 rounded-lg transition-colors">
            <Unplug class="w-3.5 h-3.5" />
            斷開連線
          </button>
        </div>
        <!-- 未連線 -->
        <div v-else>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">Personal Access Token</label>
          <div class="flex gap-2">
            <input
              v-model="githubToken"
              type="password"
              placeholder="ghp_xxxx 或 github_pat_xxxx"
              class="flex-1 bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-slate-500 outline-none text-sm font-mono"
              @keyup.enter="connectGithub"
            />
            <button
              @click="connectGithub"
              :disabled="githubVerifying || !githubToken.trim()"
              class="flex items-center gap-1.5 px-4 py-2 bg-slate-600 hover:bg-slate-500 disabled:opacity-50 text-white rounded-lg text-xs font-medium transition-all"
            >
              <Loader2 v-if="githubVerifying" class="w-3.5 h-3.5 animate-spin" />
              {{ githubVerifying ? '驗證中...' : '連線' }}
            </button>
          </div>
          <p class="text-[11px] text-slate-500 mt-1.5">
            AI 成員執行任務時將使用此 Token 存取私有 Git 倉庫。可在
            <a href="https://github.com/settings/tokens" target="_blank" class="text-slate-400 hover:underline">GitHub Settings → Tokens</a> 建立
          </p>
        </div>
      </div>
    </div>

    <!-- 立繪生成 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Sparkles class="w-4 h-4 text-purple-400" />
          <h2 class="text-sm font-semibold text-slate-200">立繪生成</h2>
        </div>
      </div>
      <div class="p-6 space-y-4">
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">Gemini API Key</label>
          <input
            v-model="form.gemini_api_key"
            type="password"
            placeholder="AIza..."
            class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-purple-500 outline-none text-sm font-mono"
          />
          <p class="text-[11px] text-slate-500 mt-1">
            用於 AI 產生成員立繪。可在
            <a href="https://aistudio.google.com/apikey" target="_blank" class="text-purple-400 hover:underline">Google AI Studio</a> 取得
          </p>
        </div>
      </div>
    </div>

    <!-- 儲存按鈕 -->
    <div class="flex justify-end">
      <button
        @click="saveSettings"
        :disabled="saving || loading"
        class="flex items-center gap-2 px-6 py-2.5 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-lg font-bold text-sm transition-all shadow-lg shadow-emerald-500/20"
      >
        <Save class="w-4 h-4" />
        {{ saving ? '儲存中...' : '儲存設定' }}
      </button>
    </div>

    <!-- 存取控制 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <ShieldCheck class="w-4 h-4 text-cyan-400" />
          <h2 class="text-sm font-semibold text-slate-200">存取控制</h2>
        </div>
      </div>
      <div class="p-6 space-y-4">
        <div class="flex items-center justify-between">
          <div>
            <label class="block text-xs font-medium text-slate-400">強制登入才能瀏覽</label>
            <p class="text-[11px] text-slate-500 mt-0.5">開啟後，未登入的使用者無法瀏覽任何頁面（會被導向登入畫面）</p>
            <p class="text-[11px] text-slate-500">關閉時，未登入可瀏覽但操作按鈕（新增、刪除、拖曳等）會被隱藏</p>
          </div>
          <button
            @click="toggleLoginToView"
            :class="[
              'relative w-11 h-6 rounded-full transition-colors shrink-0 ml-4',
              requireLoginToView ? 'bg-cyan-500' : 'bg-slate-600'
            ]"
          >
            <div
              :class="[
                'absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform shadow',
                requireLoginToView ? 'left-5.5' : 'left-0.5'
              ]"
            ></div>
          </button>
        </div>
      </div>
    </div>

    <!-- 管理員密碼 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Lock class="w-4 h-4 text-amber-400" />
          <h2 class="text-sm font-semibold text-slate-200">管理員密碼</h2>
        </div>
      </div>
      <div class="p-6 space-y-4">
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">目前密碼</label>
          <input
            v-model="passwordForm.current"
            type="password"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-amber-500 outline-none text-sm"
          />
        </div>
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">新密碼</label>
          <input
            v-model="passwordForm.new"
            type="password"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-amber-500 outline-none text-sm"
          />
          <p class="text-[11px] text-slate-500 mt-1">至少 6 個字元</p>
        </div>
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">確認新密碼</label>
          <input
            v-model="passwordForm.confirm"
            type="password"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-amber-500 outline-none text-sm"
            @keyup.enter="changePassword"
          />
        </div>

        <div v-if="passwordError" class="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
          {{ passwordError }}
        </div>
        <div v-if="passwordSuccess" class="text-xs text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-3 py-2">
          {{ passwordSuccess }}
        </div>

        <div class="flex justify-end">
          <button
            @click="changePassword"
            :disabled="passwordSaving"
            class="flex items-center gap-2 px-4 py-2 bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-white rounded-lg font-bold text-xs transition-all"
          >
            <Loader2 v-if="passwordSaving" class="w-3.5 h-3.5 animate-spin" />
            {{ passwordSaving ? '更新中...' : '更新密碼' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
