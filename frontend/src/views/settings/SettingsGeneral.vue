<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { Globe, Cpu, Save, Loader2, Lock, RefreshCw, Download, Clock, Link } from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'

import { config } from '../../config'

const store = useAegisStore()
const API = config.apiUrl

const loading = ref(true)
const saving = ref(false)

const form = ref({
  timezone: 'Asia/Taipei',
  max_workstations: '3',
  memory_short_term_days: '30',
  onestack_owner_id: '',
})

// 更新狀態
const updateStatus = ref({
  current_version: '',
  latest_version: '',
  has_update: false,
  is_updating: false,
  update_stage: 'idle',
  progress: 0,
  message: '',
  error: '',
  available_versions: [] as string[],
  is_deployed: false,
  auto_update_enabled: false,
  auto_update_time: '03:00',
  update_keep_versions: 3,
  update_channel: 'development' as 'development' | 'stable',
})
const checkingUpdate = ref(false)
const applyingUpdate = ref(false)

const updateStageText = computed(() => {
  const stages: Record<string, string> = {
    idle: '',
    checking: '檢查中...',
    downloading: '下載中...',
    building: '建構中...',
    waiting: '等待任務完成...',
    applying: '套用中...',
    done: '完成',
    failed: '失敗',
  }
  return stages[updateStatus.value.update_stage] || ''
})

async function fetchUpdateStatus() {
  try {
    const res = await fetch(`${API}/api/v1/update/status`)
    if (res.ok) {
      updateStatus.value = await res.json()
    }
  } catch (e) {
    console.error('Failed to fetch update status:', e)
  }
}

async function checkForUpdates() {
  checkingUpdate.value = true
  try {
    const res = await fetch(`${API}/api/v1/update/check`, { method: 'POST' })
    const data = await res.json()
    updateStatus.value = { ...updateStatus.value, ...data }
  } catch (e) {
    console.error('Failed to check for updates:', e)
  } finally {
    checkingUpdate.value = false
  }
}

let pollInterval: ReturnType<typeof setInterval> | null = null

async function applyUpdate() {
  if (!confirm(`確定要更新到 v${updateStatus.value.latest_version}？\n\n執行中的任務會等待完成後再套用更新。`)) {
    return
  }

  applyingUpdate.value = true
  try {
    const res = await fetch(`${API}/api/v1/update/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ wait_timeout: 300 }),
    })
    const data = await res.json()
    if (data.ok) {
      // 開始輪詢更新狀態
      startPolling()
    } else {
      alert(`更新失敗：${data.error || data.detail}`)
      applyingUpdate.value = false
    }
  } catch (e) {
    console.error('Failed to apply update:', e)
    alert('更新失敗，請檢查伺服器狀態。')
    applyingUpdate.value = false
  }
}

function startPolling() {
  if (pollInterval) return

  pollInterval = setInterval(async () => {
    try {
      const res = await fetch(`${API}/api/v1/update/status`)
      if (res.ok) {
        const data = await res.json()
        updateStatus.value = { ...updateStatus.value, ...data }

        // 檢查是否完成
        if (data.update_stage === 'done') {
          stopPolling()
          applyingUpdate.value = false
          alert('更新成功！頁面即將重新載入。')
          setTimeout(() => window.location.reload(), 2000)
        } else if (data.update_stage === 'failed') {
          stopPolling()
          applyingUpdate.value = false
          alert(`更新失敗：${data.error}`)
        }
      }
    } catch {
      // 服務重啟中，等待恢復
      updateStatus.value.message = '服務重啟中，等待恢復...'
    }
  }, 2000)
}

function stopPolling() {
  if (pollInterval) {
    clearInterval(pollInterval)
    pollInterval = null
  }
}

async function saveAutoUpdateSettings() {
  try {
    await fetch(`${API}/api/v1/update/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        auto_update_enabled: updateStatus.value.auto_update_enabled,
        auto_update_time: updateStatus.value.auto_update_time,
        update_keep_versions: updateStatus.value.update_keep_versions,
        update_channel: updateStatus.value.update_channel,
      }),
    })
  } catch (e) {
    console.error('Failed to save auto update settings:', e)
  }
}

async function changeChannel(channel: 'development' | 'stable') {
  updateStatus.value.update_channel = channel
  await saveAutoUpdateSettings()
  // 切換頻道後自動檢查更新
  await checkForUpdates()
}

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
  await Promise.all([
    store.fetchSettings(),
    fetchUpdateStatus(),
  ])
  form.value.timezone = store.settings.timezone || 'Asia/Taipei'
  form.value.max_workstations = store.settings.max_workstations || '3'
  form.value.memory_short_term_days = store.settings.memory_short_term_days || '30'
  form.value.onestack_owner_id = store.settings.onestack_owner_id || ''
  loading.value = false

  // 如果正在更新中，恢復輪詢
  if (updateStatus.value.is_updating) {
    applyingUpdate.value = true
    startPolling()
  }

  // 頁面載入時自動檢查更新
  checkForUpdates()
})

onUnmounted(() => {
  stopPolling()
})

async function saveSettings() {
  saving.value = true
  try {
    await store.updateSettings({
      timezone: form.value.timezone,
      max_workstations: form.value.max_workstations,
      memory_short_term_days: form.value.memory_short_term_days,
      onestack_owner_id: form.value.onestack_owner_id,
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

    <!-- OneStack 整合 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Link class="w-4 h-4 text-violet-400" />
          <h2 class="text-sm font-semibold text-slate-200">OneStack 整合</h2>
        </div>
      </div>
      <div class="p-6 space-y-4">
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">Owner ID</label>
          <input
            v-model="form.onestack_owner_id"
            type="text"
            placeholder="填入 OneStack 個人頁面上的序號（UUID）"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-violet-500 outline-none text-sm font-mono"
          />
          <p class="text-[11px] text-slate-500 mt-1">Aegis 會將高價值 Email 摘要轉發到 OneStack 指揮中心</p>
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

    <!-- 系統更新 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Download class="w-4 h-4 text-cyan-400" />
          <h2 class="text-sm font-semibold text-slate-200">系統更新</h2>
        </div>
      </div>
      <div class="p-6 space-y-4">
        <!-- 更新頻道選擇 -->
        <div class="flex gap-2">
          <button
            @click="changeChannel('development')"
            :disabled="checkingUpdate"
            class="flex-1 px-4 py-2.5 rounded-lg border text-xs font-medium transition-all"
            :class="updateStatus.update_channel === 'development'
              ? 'bg-cyan-500/20 border-cyan-500 text-cyan-400'
              : 'bg-slate-700/50 border-slate-600 text-slate-400 hover:border-slate-500'"
          >
            <div class="font-bold">開發版</div>
            <div class="text-[10px] opacity-70 mt-0.5">最新功能，可能不穩定</div>
          </button>
          <button
            @click="changeChannel('stable')"
            :disabled="checkingUpdate"
            class="flex-1 px-4 py-2.5 rounded-lg border text-xs font-medium transition-all"
            :class="updateStatus.update_channel === 'stable'
              ? 'bg-emerald-500/20 border-emerald-500 text-emerald-400'
              : 'bg-slate-700/50 border-slate-600 text-slate-400 hover:border-slate-500'"
          >
            <div class="font-bold">穩定版</div>
            <div class="text-[10px] opacity-70 mt-0.5">經過測試，較為穩定</div>
          </button>
        </div>

        <!-- 版本資訊 -->
        <div class="flex items-center justify-between">
          <div>
            <div class="text-xs text-slate-400 mb-1">目前版本</div>
            <div class="text-lg font-mono text-slate-200">v{{ updateStatus.current_version || '---' }}</div>
          </div>
          <div class="text-right">
            <div class="text-xs text-slate-400 mb-1">最新版本</div>
            <div class="text-lg font-mono" :class="updateStatus.has_update ? 'text-cyan-400' : 'text-slate-200'">
              v{{ updateStatus.latest_version || '---' }}
            </div>
          </div>
        </div>

        <!-- 更新狀態訊息 -->
        <div v-if="updateStatus.message" class="text-xs px-3 py-2 rounded-lg" :class="updateStatus.error ? 'bg-red-500/10 text-red-400 border border-red-500/20' : 'bg-slate-700/50 text-slate-400'">
          {{ updateStatus.message }}
          <span v-if="updateStatus.error" class="block mt-1 text-red-300">{{ updateStatus.error }}</span>
        </div>

        <!-- 進度條 -->
        <div v-if="updateStatus.is_updating" class="space-y-2">
          <div class="flex items-center justify-between text-xs text-slate-400">
            <span>{{ updateStageText }}</span>
            <span>{{ updateStatus.progress }}%</span>
          </div>
          <div class="h-2 bg-slate-700 rounded-full overflow-hidden">
            <div
              class="h-full bg-cyan-500 transition-all duration-300"
              :style="{ width: `${updateStatus.progress}%` }"
            />
          </div>
        </div>

        <!-- 操作按鈕 -->
        <div class="flex gap-3">
          <button
            @click="checkForUpdates"
            :disabled="checkingUpdate || updateStatus.is_updating"
            class="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-200 rounded-lg text-xs transition-all"
          >
            <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': checkingUpdate }" />
            檢查更新
          </button>
          <button
            v-if="updateStatus.has_update && updateStatus.is_deployed"
            @click="applyUpdate"
            :disabled="applyingUpdate || updateStatus.is_updating"
            class="flex items-center gap-2 px-4 py-2 bg-cyan-500 hover:bg-cyan-600 disabled:opacity-50 text-white rounded-lg text-xs font-bold transition-all"
          >
            <Download class="w-3.5 h-3.5" :class="{ 'animate-bounce': applyingUpdate }" />
            {{ applyingUpdate ? '更新中...' : '立即更新' }}
          </button>
        </div>

        <!-- 本地開發環境提示 -->
        <div v-if="!updateStatus.is_deployed" class="text-xs text-slate-500 bg-slate-700/30 rounded-lg px-3 py-2">
          本地開發環境請使用 <code class="bg-slate-600 px-1 rounded">git pull</code> 手動更新。
        </div>

        <!-- 自動更新設定（僅部署環境顯示） -->
        <div v-if="updateStatus.is_deployed" class="pt-4 border-t border-slate-700/50 space-y-3">
          <div class="flex items-center justify-between">
            <div>
              <label class="text-xs font-medium text-slate-400">自動更新</label>
              <p class="text-[11px] text-slate-500">啟用後將透過排程自動檢查並套用更新</p>
            </div>
            <button
              @click="updateStatus.auto_update_enabled = !updateStatus.auto_update_enabled; saveAutoUpdateSettings()"
              class="relative w-11 h-6 rounded-full transition-colors"
              :class="updateStatus.auto_update_enabled ? 'bg-cyan-500' : 'bg-slate-600'"
            >
              <span
                class="absolute top-1 w-4 h-4 bg-white rounded-full transition-all"
                :class="updateStatus.auto_update_enabled ? 'left-6' : 'left-1'"
              />
            </button>
          </div>

          <div v-if="updateStatus.auto_update_enabled" class="flex items-center gap-4">
            <div>
              <label class="block text-xs font-medium text-slate-400 mb-1">更新時間</label>
              <div class="flex items-center gap-2">
                <Clock class="w-3.5 h-3.5 text-slate-500" />
                <input
                  v-model="updateStatus.auto_update_time"
                  type="time"
                  @change="saveAutoUpdateSettings"
                  class="bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-slate-200 text-xs font-mono focus:ring-2 focus:ring-cyan-500 outline-none"
                />
              </div>
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-400 mb-1">保留版本數</label>
              <input
                v-model.number="updateStatus.update_keep_versions"
                type="number"
                min="1"
                max="10"
                @change="saveAutoUpdateSettings"
                class="w-16 bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-slate-200 text-xs font-mono focus:ring-2 focus:ring-cyan-500 outline-none"
              />
            </div>
          </div>
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
