<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { Download, RefreshCw, Clock } from 'lucide-vue-next'

import { config } from '../../config'

const API = config.apiUrl

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
  await checkForUpdates()
}

onMounted(async () => {
  await fetchUpdateStatus()

  if (updateStatus.value.is_updating) {
    applyingUpdate.value = true
    startPolling()
  }

  checkForUpdates()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <div class="max-w-2xl space-y-6">
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
  </div>
</template>
