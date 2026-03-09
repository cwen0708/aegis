<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { MessageSquare, Loader2, RefreshCw } from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'
import ChannelCard from '../../components/ChannelCard.vue'

const store = useAegisStore()
const API = ''

// 頻道設定狀態
interface ChannelConfig {
  enabled: boolean
  [key: string]: any
}
const channelsLoading = ref(true)
const channelConfigs = ref<Record<string, ChannelConfig>>({})
const channelStatuses = ref<Record<string, { connected: boolean; error?: string }>>({})
const channelSaving = ref<string | null>(null)
const channelRestarting = ref(false)

// 頻道定義
const channelDefs = [
  {
    name: 'telegram',
    label: 'Telegram',
    icon: '✈️',
    iconColor: 'bg-sky-500/20',
    fields: [
      { key: 'bot_token', label: 'Bot Token', type: 'password' as const, placeholder: '123456:ABC-DEF...', hint: '從 @BotFather 取得' },
    ],
  },
  {
    name: 'line',
    label: 'LINE',
    icon: '💬',
    iconColor: 'bg-green-500/20',
    fields: [
      { key: 'channel_secret', label: 'Channel Secret', type: 'password' as const, placeholder: '' },
      { key: 'access_token', label: 'Access Token', type: 'password' as const, placeholder: '' },
    ],
  },
  {
    name: 'discord',
    label: 'Discord',
    icon: '🎮',
    iconColor: 'bg-indigo-500/20',
    fields: [
      { key: 'bot_token', label: 'Bot Token', type: 'password' as const, placeholder: '' },
    ],
  },
  {
    name: 'slack',
    label: 'Slack',
    icon: '💼',
    iconColor: 'bg-purple-500/20',
    fields: [
      { key: 'bot_token', label: 'Bot Token (xoxb-)', type: 'password' as const, placeholder: 'xoxb-...' },
      { key: 'app_token', label: 'App Token (xapp-)', type: 'password' as const, placeholder: 'xapp-...' },
    ],
  },
  {
    name: 'wecom',
    label: '企業微信',
    icon: '🏢',
    iconColor: 'bg-blue-500/20',
    fields: [
      { key: 'corp_id', label: '企業 ID', type: 'text' as const, placeholder: '' },
      { key: 'corp_secret', label: '應用 Secret', type: 'password' as const, placeholder: '' },
      { key: 'agent_id', label: 'Agent ID', type: 'text' as const, placeholder: '1000001' },
    ],
  },
  {
    name: 'feishu',
    label: '飛書 / Lark',
    icon: '🐦',
    iconColor: 'bg-cyan-500/20',
    fields: [
      { key: 'app_id', label: 'App ID', type: 'text' as const, placeholder: '' },
      { key: 'app_secret', label: 'App Secret', type: 'password' as const, placeholder: '' },
      { key: 'is_lark', label: '使用 Lark 國際版', type: 'checkbox' as const },
    ],
  },
]

async function fetchChannelConfigs() {
  channelsLoading.value = true
  try {
    const res = await fetch(`${API}/api/v1/channels`)
    channelConfigs.value = await res.json()
  } catch {
    channelConfigs.value = {}
  } finally {
    channelsLoading.value = false
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

async function updateChannelConfig(name: string, config: ChannelConfig) {
  channelSaving.value = name
  try {
    const res = await fetch(`${API}/api/v1/channels/${name}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    })
    if (res.ok) {
      channelConfigs.value[name] = config
      store.addToast('頻道設定已儲存', 'success')
    } else {
      store.addToast('儲存失敗', 'error')
    }
  } catch {
    store.addToast('儲存失敗', 'error')
  } finally {
    channelSaving.value = null
  }
}

async function restartChannels() {
  channelRestarting.value = true
  try {
    const res = await fetch(`${API}/api/v1/channels/restart`, { method: 'POST' })
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

onMounted(() => {
  fetchChannelConfigs()
  fetchChannelStatuses()
})
</script>

<template>
  <div class="max-w-2xl space-y-6">
    <!-- 頻道設定 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <MessageSquare class="w-4 h-4 text-teal-400" />
          <h2 class="text-sm font-semibold text-slate-200">頻道設定</h2>
          <Loader2 v-if="channelsLoading" class="w-4 h-4 text-slate-500 animate-spin ml-auto" />
        </div>
        <p class="text-[11px] text-slate-500 mt-1">連接外部通訊平台，透過 Bot 接收指令和發送通知</p>
      </div>
      <div class="p-4 space-y-2">
        <div v-if="channelsLoading" class="text-sm text-slate-500 px-2">讀取中...</div>
        <template v-else>
          <ChannelCard
            v-for="ch in channelDefs"
            :key="ch.name"
            :name="ch.name"
            :label="ch.label"
            :icon="ch.icon"
            :icon-color="ch.iconColor"
            :config="channelConfigs[ch.name] || { enabled: false }"
            :fields="ch.fields"
            :status="channelStatuses[ch.name]"
            :saving="channelSaving === ch.name"
            @update="(cfg) => updateChannelConfig(ch.name, cfg)"
          />
        </template>
        <!-- 重啟按鈕 + 提示 -->
        <div class="flex items-center justify-between px-2 pt-3">
          <p class="text-[10px] text-slate-500">
            設定變更後需重啟服務才會生效
          </p>
          <button
            @click="restartChannels"
            :disabled="channelRestarting"
            class="flex items-center gap-1.5 px-3 py-1.5 bg-teal-500 hover:bg-teal-600 disabled:opacity-50 text-white rounded-lg text-xs font-medium transition-all"
          >
            <Loader2 v-if="channelRestarting" class="w-3 h-3 animate-spin" />
            <RefreshCw v-else class="w-3 h-3" />
            重啟頻道服務
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
