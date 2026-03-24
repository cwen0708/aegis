<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Loader2, ChevronRight, RefreshCw, Layers } from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'
import { config } from '../../config'
import { authHeaders } from '../../utils/authFetch'

const router = useRouter()
const store = useAegisStore()
const API = config.apiUrl

const loading = ref(true)
const channelConfigs = ref<Record<string, any>>({})
const channelStatuses = ref<Record<string, { connected: boolean; error?: string }>>({})
const channelRestarting = ref(false)
const onestackConnected = ref(false)

// 頻道定義
const channelDefs = [
  { name: 'telegram', label: 'Telegram', icon: '✈️', iconColor: 'bg-sky-500/20' },
  { name: 'line', label: 'LINE', icon: '💬', iconColor: 'bg-green-500/20' },
  { name: 'discord', label: 'Discord', icon: '🎮', iconColor: 'bg-indigo-500/20' },
  { name: 'slack', label: 'Slack', icon: '💼', iconColor: 'bg-purple-500/20' },
  { name: 'wecom', label: '企業微信', icon: '🏢', iconColor: 'bg-blue-500/20' },
  { name: 'feishu', label: '飛書 / Lark', icon: '🐦', iconColor: 'bg-cyan-500/20' },
  { name: 'email', label: 'Email (IMAP/SMTP)', icon: '📧', iconColor: 'bg-amber-500/20' },
]

function getStatusRing(name: string) {
  const cfg = channelConfigs.value[name]
  const st = channelStatuses.value[name]
  if (!cfg || !cfg.enabled) return 'ring-slate-600'
  if (st?.connected) return 'ring-emerald-500'
  if (st?.error) return 'ring-red-500'
  return 'ring-amber-500'
}

function getModeText(name: string) {
  const cfg = channelConfigs.value[name]
  if (!cfg) return ''
  if (name === 'line' && cfg.mode === 'passive') return '收集模式'
  if (name === 'email' && cfg.auto_reply_enabled) return '自動回覆'
  return ''
}

async function fetchChannelConfigs() {
  loading.value = true
  try {
    const res = await fetch(`${API}/api/v1/channels`)
    channelConfigs.value = await res.json()
  } catch {
    channelConfigs.value = {}
  } finally {
    loading.value = false
  }
}

async function fetchChannelStatuses() {
  try {
    const res = await fetch(`${API}/api/v1/channels/status`)
    const data = await res.json()
    const statuses: Record<string, { connected: boolean; error?: string }> = {}
    for (const ch of data.channels || []) {
      statuses[ch.platform] = { connected: ch.connected, error: ch.error }
    }
    channelStatuses.value = statuses
  } catch {
    channelStatuses.value = {}
  }
}

async function restartChannels() {
  channelRestarting.value = true
  try {
    const res = await fetch(`${API}/api/v1/channels/restart`, { method: 'POST', headers: authHeaders() })
    const data = await res.json()
    if (res.ok) {
      store.addToast(data.message || '頻道已重啟', 'success')
      await fetchChannelStatuses()
    } else {
      store.addToast(data.detail || '重啟失敗', 'error')
    }
  } catch {
    store.addToast('重啟失敗', 'error')
  } finally {
    channelRestarting.value = false
  }
}

async function fetchOnestackStatus() {
  try {
    const res = await fetch(`${API}/api/v1/node/pair/status`)
    if (res.ok) {
      const data = await res.json()
      onestackConnected.value = !!data.connected
    }
  } catch {
    onestackConnected.value = false
  }
}

onMounted(() => {
  fetchChannelConfigs()
  fetchChannelStatuses()
  fetchOnestackStatus()
})
</script>

<template>
  <div class="space-y-6">
    <!-- Hint -->
    <div class="bg-slate-800/30 rounded-xl border border-slate-700/30 p-4 text-sm text-slate-400 flex items-center justify-between">
      <span>連接外部通訊平台，透過 Bot 接收指令和發送通知。設定變更後需重啟服務。</span>
      <button
        @click="restartChannels"
        :disabled="channelRestarting"
        class="flex items-center gap-1.5 px-3 py-1.5 bg-teal-500/20 hover:bg-teal-500/30 disabled:opacity-50 text-teal-400 rounded-lg text-xs font-medium transition-all shrink-0 ml-4"
      >
        <Loader2 v-if="channelRestarting" class="w-3 h-3 animate-spin" />
        <RefreshCw v-else class="w-3 h-3" />
        重啟服務
      </button>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex justify-center py-12">
      <Loader2 class="w-8 h-8 animate-spin text-slate-400" />
    </div>

    <!-- Channel List -->
    <div v-else class="space-y-3">
      <!-- OneStack（置頂） -->
      <div
        class="bg-slate-900/50 rounded-xl border border-slate-700/50 p-4 cursor-pointer hover:border-slate-600 hover:bg-slate-800/50 transition-all"
        @click="router.push('/settings/onestack')"
      >
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-3 flex-1 min-w-0">
            <div :class="['w-9 h-9 rounded-lg flex items-center justify-center bg-violet-500/20 shrink-0 ring-[3px]', onestackConnected ? 'ring-emerald-500' : 'ring-slate-600']">
              <Layers class="w-4 h-4 text-violet-400" />
            </div>
            <div class="flex items-center gap-2">
              <span class="font-medium text-slate-200">OneStack</span>
              <span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">平台連接</span>
            </div>
          </div>
          <ChevronRight class="w-5 h-5 text-slate-600 ml-4 shrink-0" />
        </div>
      </div>

      <!-- 通訊頻道 -->
      <div
        v-for="ch in channelDefs"
        :key="ch.name"
        class="bg-slate-900/50 rounded-xl border border-slate-700/50 p-4 cursor-pointer hover:border-slate-600 hover:bg-slate-800/50 transition-all"
        @click="router.push(`/settings/channels/${ch.name}`)"
      >
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-3 flex-1 min-w-0">
            <div :class="['w-9 h-9 rounded-lg flex items-center justify-center text-base shrink-0 ring-[3px]', ch.iconColor, getStatusRing(ch.name)]">
              {{ ch.icon }}
            </div>
            <div class="flex items-center gap-2">
              <span class="font-medium text-slate-200">{{ ch.label }}</span>
              <span v-if="getModeText(ch.name)" class="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
                {{ getModeText(ch.name) }}
              </span>
            </div>
          </div>
          <ChevronRight class="w-5 h-5 text-slate-600 ml-4 shrink-0" />
        </div>
      </div>
    </div>
  </div>
</template>
