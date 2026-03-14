<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { Download, RefreshCw, Clock } from 'lucide-vue-next'

import { config } from '../../config'
import { authHeaders } from '../../utils/authFetch'

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

// 各通道版本資訊
const devInfo = ref({ latest: '', has_update: false, checking: false, versions: [] as string[] })
const stableInfo = ref({ latest: '', has_update: false, checking: false, versions: [] as string[] })

const applyingUpdate = ref(false)

// 合併兩個通道的版本並排序（最新在前），限 15 筆
const allVersions = computed(() => {
  const all = [
    ...devInfo.value.versions.map(v => ({ tag: v, channel: 'dev' as const })),
    ...stableInfo.value.versions.map(v => ({ tag: v, channel: 'stable' as const })),
  ]
  // 去重（同一 commit 可能有多個 tag）
  const seen = new Set<string>()
  const unique = all.filter(v => {
    if (seen.has(v.tag)) return false
    seen.add(v.tag)
    return true
  })
  // tag 已經從 API 各自排序好了，合併後用字串比較排序
  unique.sort((a, b) => {
    const pa = parseTag(a.tag)
    const pb = parseTag(b.tag)
    for (let i = 0; i < 5; i++) {
      if (pa[i] !== pb[i]) return (pb[i] ?? 0) - (pa[i] ?? 0)
    }
    return 0
  })
  return unique.slice(0, 15)
})

function parseTag(tag: string): number[] {
  // v0.3.2 → [0,3,2,1,0], v0.3.1-dev.5 → [0,3,1,0,5], v0.3.2-stable → [0,3,2,1,0]
  const clean = tag.replace(/^v/, '').replace('-stable', '')
  const devMatch = clean.match(/^(\d+)\.(\d+)\.(\d+)(?:-dev\.(\d+))?$/)
  if (!devMatch) return [0, 0, 0, 0, 0]
  const maj = devMatch[1], min = devMatch[2], patch = devMatch[3], dev = devMatch[4]
  return [+(maj!), +(min!), +(patch!), dev !== undefined ? 0 : 1, dev !== undefined ? +dev : 0]
}

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
    // 已選中 → 取消
    autoUpdateChannel.value = null
  } else {
    // 選中新通道
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
      info.value.versions = data.available_versions || []
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

onMounted(async () => {
  await fetchUpdateStatus()

  if (updateStatus.value.is_updating) {
    applyingUpdate.value = true
    startPolling()
  }

  checkBothChannels()
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
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <Download class="w-4 h-4 text-cyan-400" />
            <h2 class="text-sm font-semibold text-slate-200">系統更新</h2>
          </div>
          <div class="text-xs text-slate-500 font-mono">v{{ updateStatus.current_version || '---' }}</div>
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
            <!-- 自動更新核選方塊 -->
            <label
              v-if="updateStatus.is_deployed"
              class="flex items-center gap-1.5 cursor-pointer select-none shrink-0"
              title="自動更新至開發版"
            >
              <input
                type="checkbox"
                :checked="autoUpdateChannel === 'development'"
                @change="toggleAutoUpdate('development')"
                class="w-4 h-4 rounded border-slate-600 bg-slate-800 text-cyan-500 focus:ring-cyan-500/50 cursor-pointer"
              />
              <span class="text-[10px] text-slate-500">自動</span>
            </label>
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
            <!-- 自動更新核選方塊 -->
            <label
              v-if="updateStatus.is_deployed"
              class="flex items-center gap-1.5 cursor-pointer select-none shrink-0"
              title="自動更新至穩定版"
            >
              <input
                type="checkbox"
                :checked="autoUpdateChannel === 'stable'"
                @change="toggleAutoUpdate('stable')"
                class="w-4 h-4 rounded border-slate-600 bg-slate-800 text-emerald-500 focus:ring-emerald-500/50 cursor-pointer"
              />
              <span class="text-[10px] text-slate-500">自動</span>
            </label>
          </div>
        </div>

        <!-- 檢查更新 -->
        <button
          @click="checkBothChannels"
          :disabled="devInfo.checking || stableInfo.checking || updateStatus.is_updating"
          class="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-200 rounded-lg text-xs transition-all"
        >
          <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': devInfo.checking || stableInfo.checking }" />
          檢查更新
        </button>

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

        <!-- 本地開發環境提示 -->
        <div v-if="!updateStatus.is_deployed" class="text-xs text-slate-500 bg-slate-700/30 rounded-lg px-3 py-2">
          本地開發環境請使用 <code class="bg-slate-600 px-1 rounded">git pull</code> 手動更新。
        </div>

        <!-- 自動更新時間設定（僅部署環境 + 有開啟自動更新時顯示） -->
        <div v-if="updateStatus.is_deployed && updateStatus.auto_update_enabled" class="pt-4 border-t border-slate-700/50">
          <div class="flex items-center gap-4">
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

    <!-- 版本歷史 -->
    <div v-if="allVersions.length > 0" class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Clock class="w-4 h-4 text-slate-400" />
          <h2 class="text-sm font-semibold text-slate-200">版本歷史</h2>
          <span class="text-[10px] text-slate-500">最近 {{ allVersions.length }} 筆</span>
        </div>
      </div>
      <div class="divide-y divide-slate-700/30">
        <div
          v-for="v in allVersions"
          :key="v.tag"
          class="flex items-center gap-3 px-6 py-2.5 hover:bg-slate-700/20 transition-colors"
        >
          <span class="text-sm font-mono text-slate-200 flex-1">{{ v.tag }}</span>
          <span
            :class="[
              'px-1.5 py-0.5 rounded text-[10px] font-medium border',
              v.channel === 'stable'
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                : 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20'
            ]"
          >
            {{ v.channel === 'stable' ? '穩定' : '開發' }}
          </span>
          <span
            v-if="v.tag.replace(/^v/, '').replace('-stable', '') === updateStatus.current_version"
            class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-700 text-slate-300 border border-slate-600"
          >
            目前
          </span>
        </div>
      </div>
    </div>
  </div>
</template>
