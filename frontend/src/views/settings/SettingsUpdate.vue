<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { Download, RefreshCw, Clock, Loader2, ArrowDownToLine } from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'

import { config } from '../../config'
import { authHeaders } from '../../utils/authFetch'
import { useAppVersion } from '../../composables/useAppVersion'

const store = useAegisStore()
const API = config.apiUrl

// SSOT 版本資訊（優先 /api/v1/version，失敗 fallback 到 __APP_VERSION__）
const { version: ssotVersion, fetchVersion: refetchVersion } = useAppVersion()

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

// 各通道版本資訊
const devInfo = ref({ latest: '', has_update: false, checking: false })
const stableInfo = ref({ latest: '', has_update: false, checking: false })

const applyingUpdate = ref(false)

// 版本歷史
interface VersionEntry {
  tag: string
  channel: 'dev' | 'stable'
  message: string
  date: string
  is_current: boolean
}
const versionHistory = ref<VersionEntry[]>([])
const versionHistoryLoading = ref(false)
const switchingVersion = ref<string | null>(null)

// 顯示用版本號：優先 SSOT (/api/v1/version)，fallback 到 /update/status
const displayVersion = computed(() =>
  ssotVersion.value || updateStatus.value.current_version || '---'
)

const updateStageText = computed(() => {
  const stages: Record<string, string> = {
    idle: '',
    checking: '檢查中...',
    downloading: '下載中...',
    building: '建構中...',
    waiting: '等待任務完成...',
    applying: '套用中...',
    restarting: '服務重啟中...',
    done: '完成',
    failed: '失敗',
  }
  return stages[updateStatus.value.update_stage] || ''
})

// 自動更新通道：null = 關閉, 'development' | 'stable'
const autoUpdateChannel = computed<'development' | 'stable' | null>({
  get() {
    if (!updateStatus.value.auto_update_enabled) return null
    return updateStatus.value.update_channel
  },
  set(val) {
    if (val === null) {
      updateStatus.value.auto_update_enabled = false
    } else {
      updateStatus.value.auto_update_enabled = true
      updateStatus.value.update_channel = val
    }
  },
})

function toggleAutoUpdate(channel: 'development' | 'stable') {
  if (autoUpdateChannel.value === channel) {
    autoUpdateChannel.value = null
  } else {
    autoUpdateChannel.value = channel
  }
  saveAutoUpdateSettings()
}

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

async function checkChannel(channel: 'development' | 'stable') {
  const info = channel === 'development' ? devInfo : stableInfo
  info.value.checking = true
  try {
    const res = await fetch(`${API}/api/v1/update/check`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ channel }),
    })
    if (res.ok) {
      const data = await res.json()
      info.value.latest = data.latest_version || ''
      info.value.has_update = data.has_update || false
    }
  } catch (e) {
    console.error(`Failed to check ${channel} channel:`, e)
  } finally {
    info.value.checking = false
  }
}

async function checkBothChannels() {
  await Promise.all([checkChannel('development'), checkChannel('stable')])
}

async function fetchVersionHistory() {
  versionHistoryLoading.value = true
  try {
    const res = await fetch(`${API}/api/v1/update/versions`)
    if (res.ok) {
      const data = await res.json()
      const current = data.current || ''
      const versions = data.versions || []
      versionHistory.value = versions.map((v: any) => ({
        tag: v.tag || v,
        channel: (v.tag || v || '').includes('dev') ? 'dev' : 'stable',
        message: v.title || '',
        date: v.date || '',
        is_current: (v.tag || v) === current,
      }))
    }
  } catch (e) {
    console.error('Failed to fetch version history:', e)
  } finally {
    versionHistoryLoading.value = false
  }
}

let pollInterval: ReturnType<typeof setInterval> | null = null

async function applyUpdate(channel: 'development' | 'stable') {
  const info = channel === 'development' ? devInfo : stableInfo
  const ver = info.value.latest
  if (!confirm(`確定要更新到 v${ver}（${channel === 'development' ? '開發版' : '穩定版'}）？\n\n執行中的任務會等待完成後再套用更新。`)) {
    return
  }

  applyingUpdate.value = true
  try {
    const res = await fetch(`${API}/api/v1/update/apply`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ version: ver, wait_timeout: 300 }),
    })
    const data = await res.json()
    if (data.ok) {
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

async function switchToVersion(tag: string) {
  if (!confirm(`確定要切換到 ${tag}？`)) return

  switchingVersion.value = tag
  try {
    const res = await fetch(`${API}/api/v1/update/apply`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ version: tag.replace(/^v/, ''), wait_timeout: 300 }),
    })
    const data = await res.json()
    if (data.ok) {
      applyingUpdate.value = true
      startPolling()
    } else {
      store.addToast(`切換失敗：${data.error || data.detail}`, 'error')
    }
  } catch {
    store.addToast('切換失敗，請檢查伺服器狀態', 'error')
  } finally {
    switchingVersion.value = null
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

        if (data.update_stage === 'done') {
          stopPolling()
          applyingUpdate.value = false
          // 等待後端完全啟動後再 reload
          updateStatus.value.message = '更新完成，等待服務啟動...'
          waitForHealthThenReload()
        } else if (data.update_stage === 'failed') {
          stopPolling()
          applyingUpdate.value = false
          store.addToast(`更新失敗：${data.error}`, 'error')
        }
      }
    } catch {
      // 服務重啟中，繼續等
      updateStatus.value.message = '服務重啟中，等待恢復...'
      updateStatus.value.update_stage = 'restarting'
    }
  }, 2000)
}

async function waitForHealthThenReload(maxRetries = 30) {
  for (let i = 0; i < maxRetries; i++) {
    await new Promise(r => setTimeout(r, 2000))
    try {
      const res = await fetch(`${API}/api/v1/update/status`, { signal: AbortSignal.timeout(3000) })
      if (res.ok) {
        // 更新後重新抓 SSOT 版本
        void refetchVersion()
        store.addToast('更新成功！頁面重新載入中...', 'success')
        setTimeout(() => window.location.reload(), 500)
        return
      }
    } catch {
      updateStatus.value.message = `等待服務啟動...（${i + 1}/${maxRetries}）`
    }
  }
  store.addToast('服務似乎未正常啟動，請手動重新整理頁面', 'error')
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
      headers: authHeaders({ 'Content-Type': 'application/json' }),
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

function formatDate(iso: string) {
  if (!iso) return ''
  const tz = 'Asia/Taipei'
  return new Date(iso).toLocaleString('zh-TW', { timeZone: tz, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

onMounted(async () => {
  await fetchUpdateStatus()

  if (updateStatus.value.is_updating) {
    applyingUpdate.value = true
    startPolling()
  }

  checkBothChannels()
  fetchVersionHistory()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <div class="max-w-2xl space-y-6">
    <!-- Header Actions (Teleport to layout header) -->
    <Teleport to="#settings-header-actions">
      <button
        @click="checkBothChannels"
        :disabled="devInfo.checking || stableInfo.checking || updateStatus.is_updating"
        class="flex items-center gap-1.5 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-200 rounded-lg text-xs font-medium transition"
      >
        <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': devInfo.checking || stableInfo.checking }" />
        檢查更新
      </button>
    </Teleport>

    <!-- 系統更新 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <Download class="w-4 h-4 text-cyan-400" />
            <h2 class="text-sm font-semibold text-slate-200">系統更新</h2>
          </div>
          <div class="text-xs text-slate-500 font-mono">v{{ displayVersion }}</div>
        </div>
      </div>

      <div class="p-6 space-y-4">
        <!-- 通道列表 -->
        <div class="space-y-2">
          <!-- 開發版 -->
          <div class="flex items-center gap-3 bg-slate-900/50 rounded-xl border border-slate-700/50 px-4 py-3">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="text-sm font-medium text-cyan-400">開發版</span>
                <span class="text-[10px] text-slate-500">最新功能，可能不穩定</span>
              </div>
              <div class="text-xs font-mono text-slate-400 mt-0.5">
                <template v-if="devInfo.checking">檢查中...</template>
                <template v-else-if="devInfo.latest">
                  v{{ devInfo.latest }}
                  <span v-if="devInfo.has_update" class="text-cyan-400 ml-1">可更新</span>
                  <span v-else class="text-slate-600 ml-1">已是最新</span>
                </template>
                <template v-else>尚未檢查</template>
              </div>
            </div>
            <!-- 更新按鈕 -->
            <button
              v-if="devInfo.has_update && updateStatus.is_deployed"
              @click="applyUpdate('development')"
              :disabled="applyingUpdate || updateStatus.is_updating"
              class="px-3 py-1.5 bg-cyan-500 hover:bg-cyan-600 disabled:opacity-50 text-white rounded-lg text-xs font-medium transition"
            >
              更新
            </button>
            <!-- 自動更新 toggle -->
            <button
              v-if="updateStatus.is_deployed"
              @click="toggleAutoUpdate('development')"
              :class="[
                'relative w-11 h-6 rounded-full transition-colors shrink-0',
                autoUpdateChannel === 'development' ? 'bg-cyan-500' : 'bg-slate-600'
              ]"
              title="自動更新至開發版"
            >
              <div
                :class="[
                  'absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform shadow',
                  autoUpdateChannel === 'development' ? 'left-5.5' : 'left-0.5'
                ]"
              ></div>
            </button>
          </div>

          <!-- 穩定版 -->
          <div class="flex items-center gap-3 bg-slate-900/50 rounded-xl border border-slate-700/50 px-4 py-3">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="text-sm font-medium text-emerald-400">穩定版</span>
                <span class="text-[10px] text-slate-500">經過測試，較為穩定</span>
              </div>
              <div class="text-xs font-mono text-slate-400 mt-0.5">
                <template v-if="stableInfo.checking">檢查中...</template>
                <template v-else-if="stableInfo.latest">
                  v{{ stableInfo.latest }}
                  <span v-if="stableInfo.has_update" class="text-emerald-400 ml-1">可更新</span>
                  <span v-else class="text-slate-600 ml-1">已是最新</span>
                </template>
                <template v-else>
                  <span class="text-slate-600">無可用版本</span>
                </template>
              </div>
            </div>
            <!-- 更新按鈕 -->
            <button
              v-if="stableInfo.has_update && updateStatus.is_deployed"
              @click="applyUpdate('stable')"
              :disabled="applyingUpdate || updateStatus.is_updating"
              class="px-3 py-1.5 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-lg text-xs font-medium transition"
            >
              更新
            </button>
            <!-- 自動更新 toggle -->
            <button
              v-if="updateStatus.is_deployed"
              @click="toggleAutoUpdate('stable')"
              :class="[
                'relative w-11 h-6 rounded-full transition-colors shrink-0',
                autoUpdateChannel === 'stable' ? 'bg-emerald-500' : 'bg-slate-600'
              ]"
              title="自動更新至穩定版"
            >
              <div
                :class="[
                  'absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform shadow',
                  autoUpdateChannel === 'stable' ? 'left-5.5' : 'left-0.5'
                ]"
              ></div>
            </button>
          </div>
        </div>

        <!-- 更新狀態訊息 -->
        <div v-if="updateStatus.message" class="text-xs px-3 py-2 rounded-lg" :class="updateStatus.error ? 'bg-red-500/10 text-red-400 border border-red-500/20' : 'bg-slate-700/50 text-slate-400'">
          {{ updateStatus.message }}
          <span v-if="updateStatus.error" class="block mt-1 text-red-300">{{ updateStatus.error }}</span>
        </div>

        <!-- 進度條 -->
        <div v-if="updateStatus.is_updating || updateStatus.update_stage === 'restarting'" class="space-y-2">
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

        <!-- 本地開發環境提示 -->
        <div v-if="!updateStatus.is_deployed" class="text-xs text-slate-500 bg-slate-700/30 rounded-lg px-3 py-2">
          本地開發環境請使用 <code class="bg-slate-600 px-1 rounded">git pull</code> 手動更新。
        </div>

        <!-- 自動更新設定（僅部署環境 + 有開啟自動更新時顯示） -->
        <div v-if="updateStatus.is_deployed && updateStatus.auto_update_enabled" class="pt-4 border-t border-slate-700/50">
          <div class="flex items-center justify-between gap-4">
            <div class="flex-1 min-w-0">
              <label class="text-xs font-medium text-slate-300">自動更新</label>
              <p class="text-[11px] text-slate-500 mt-0.5">
                每天定時檢查{{ autoUpdateChannel === 'stable' ? '穩定版' : '開發版' }}通道，有新版本時自動套用。更新前會等待執行中的任務完成。
              </p>
            </div>
            <div class="flex items-center gap-2 shrink-0">
              <Clock class="w-3.5 h-3.5 text-slate-500" />
              <input
                v-model="updateStatus.auto_update_time"
                type="time"
                @change="saveAutoUpdateSettings"
                class="bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-slate-200 text-xs font-mono focus:ring-2 focus:ring-cyan-500 outline-none [color-scheme:dark]"
              />
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 版本歷史 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Clock class="w-4 h-4 text-slate-400" />
          <h2 class="text-sm font-semibold text-slate-200">版本歷史</h2>
        </div>
      </div>

      <div v-if="versionHistoryLoading" class="flex justify-center py-8">
        <Loader2 class="w-5 h-5 animate-spin text-slate-400" />
      </div>

      <div v-else-if="versionHistory.length === 0" class="px-6 py-8 text-center text-xs text-slate-500">
        尚無版本資訊
      </div>

      <div v-else class="divide-y divide-slate-700/30">
        <div
          v-for="v in versionHistory"
          :key="v.tag"
          class="px-6 py-3 hover:bg-slate-700/20 transition-colors"
        >
          <div class="flex items-center gap-3">
            <span class="text-sm font-mono text-slate-200 shrink-0">{{ v.tag }}</span>
            <span
              :class="[
                'px-1.5 py-0.5 rounded text-[10px] font-medium border shrink-0',
                v.channel === 'stable'
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                  : 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20'
              ]"
            >
              {{ v.channel === 'stable' ? '穩定' : '開發' }}
            </span>
            <span
              v-if="v.is_current"
              class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-700 text-slate-300 border border-slate-600 shrink-0"
            >
              目前
            </span>
            <span class="text-[10px] text-slate-500 ml-auto shrink-0">{{ formatDate(v.date) }}</span>
            <!-- 切換版本按鈕 -->
            <button
              v-if="!v.is_current && updateStatus.is_deployed"
              @click="switchToVersion(v.tag)"
              :disabled="applyingUpdate || updateStatus.is_updating || switchingVersion === v.tag"
              class="flex items-center gap-1 px-2 py-1 text-[10px] text-slate-400 hover:text-slate-200 hover:bg-slate-700 disabled:opacity-50 rounded transition shrink-0"
              title="切換至此版本"
            >
              <Loader2 v-if="switchingVersion === v.tag" class="w-3 h-3 animate-spin" />
              <ArrowDownToLine v-else class="w-3 h-3" />
              切換
            </button>
          </div>
          <div v-if="v.message" class="text-xs text-slate-500 mt-1 truncate">{{ v.message }}</div>
        </div>
      </div>
    </div>
  </div>
</template>
