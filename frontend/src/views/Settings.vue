<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Settings, Globe, Cpu, Save, Sparkles, CloudCog, ExternalLink, Copy, Check, Loader2, Terminal, Download, MessageSquare, RefreshCw } from 'lucide-vue-next'
import { useAegisStore } from '../stores/aegis'
import ChannelCard from '../components/ChannelCard.vue'

const store = useAegisStore()
const settingsLoading = ref(true)
const saving = ref(false)

const form = ref({
  timezone: 'Asia/Taipei',
  max_workstations: '3',
  gemini_api_key: '',
  memory_short_term_days: '30',
})

// Gcloud 引導式登入狀態
const gcloudStatus = ref<{ installed: boolean; authenticated: boolean; account: string | null } | null>(null)
const gcloudAuthSession = ref<{ session_id: string; auth_url: string; instructions: string[] } | null>(null)
const gcloudAuthCode = ref('')
const gcloudLoading = ref(false)
const gcloudError = ref('')
const gcloudSuccess = ref('')
const copied = ref(false)

// CLI 安裝狀態
const cliLoading = ref(true)
const cliStatus = ref<{
  claude: { installed: boolean; version: string | null; path: string | null };
  gemini: { installed: boolean; version: string | null; path: string | null };
} | null>(null)
const cliInstalling = ref<'claude' | 'gemini' | null>(null)
const cliError = ref('')
const cliSuccess = ref('')

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

// Gcloud 載入狀態
const gcloudStatusLoading = ref(true)

import { config } from '../config'
const API = config.apiUrl

async function fetchGcloudStatus() {
  gcloudStatusLoading.value = true
  try {
    const res = await fetch(`${API}/api/v1/gcloud/status`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    gcloudStatus.value = await res.json()
  } catch {
    gcloudStatus.value = { installed: false, authenticated: false, account: null }
  } finally {
    gcloudStatusLoading.value = false
  }
}

async function startGcloudAuth() {
  gcloudLoading.value = true
  gcloudError.value = ''
  gcloudSuccess.value = ''
  try {
    const res = await fetch(`${API}/api/v1/gcloud/auth/init`, { method: 'POST' })
    if (!res.ok) {
      const data = await res.json()
      throw new Error(data.detail || '啟動認證失敗')
    }
    gcloudAuthSession.value = await res.json()
  } catch (e: any) {
    gcloudError.value = e.message
  } finally {
    gcloudLoading.value = false
  }
}

async function completeGcloudAuth() {
  if (!gcloudAuthSession.value || !gcloudAuthCode.value.trim()) return
  gcloudLoading.value = true
  gcloudError.value = ''
  try {
    const res = await fetch(`${API}/api/v1/gcloud/auth/complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: gcloudAuthSession.value.session_id,
        auth_code: gcloudAuthCode.value.trim(),
      }),
    })
    const data = await res.json()
    if (!res.ok) {
      throw new Error(data.detail || '認證失敗')
    }
    gcloudSuccess.value = data.message || '登入成功！'
    gcloudAuthSession.value = null
    gcloudAuthCode.value = ''
    await fetchGcloudStatus()
  } catch (e: any) {
    gcloudError.value = e.message
  } finally {
    gcloudLoading.value = false
  }
}

function cancelGcloudAuth() {
  if (gcloudAuthSession.value) {
    fetch(`${API}/api/v1/gcloud/auth/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: gcloudAuthSession.value.session_id }),
    })
  }
  gcloudAuthSession.value = null
  gcloudAuthCode.value = ''
  gcloudError.value = ''
}

async function fetchCliStatus() {
  cliLoading.value = true
  try {
    const res = await fetch(`${API}/api/v1/cli/status`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    cliStatus.value = await res.json()
  } catch {
    cliStatus.value = null
  } finally {
    cliLoading.value = false
  }
}

async function installCli(type: 'claude' | 'gemini') {
  cliInstalling.value = type
  cliError.value = ''
  cliSuccess.value = ''
  try {
    const res = await fetch(`${API}/api/v1/cli/${type}/install`, { method: 'POST' })
    const data = await res.json()
    if (!res.ok) {
      throw new Error(data.detail || '安裝失敗')
    }
    cliSuccess.value = data.message
    await fetchCliStatus()
  } catch (e: any) {
    cliError.value = e.message
  } finally {
    cliInstalling.value = null
  }
}

// 頻道設定 API
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
      // 重新載入狀態
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

async function copyUrl() {
  if (gcloudAuthSession.value?.auth_url) {
    await navigator.clipboard.writeText(gcloudAuthSession.value.auth_url)
    copied.value = true
    setTimeout(() => copied.value = false, 2000)
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
  // 各區塊獨立載入，不阻塞頁面顯示
  fetchGcloudStatus()
  fetchCliStatus()
  fetchChannelConfigs()
  fetchChannelStatuses()

  // 設定值需要等待後填入表單
  await store.fetchSettings()
  form.value.timezone = store.settings.timezone || 'Asia/Taipei'
  form.value.max_workstations = store.settings.max_workstations || '3'
  form.value.gemini_api_key = store.settings.gemini_api_key || ''
  form.value.memory_short_term_days = store.settings.memory_short_term_days || '30'
  settingsLoading.value = false
})

async function saveSettings() {
  saving.value = true
  try {
    await store.updateSettings({
      timezone: form.value.timezone,
      max_workstations: form.value.max_workstations,
      gemini_api_key: form.value.gemini_api_key,
      memory_short_term_days: form.value.memory_short_term_days,
    })
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header h-16 -->
    <div class="sticky top-0 z-10 h-16 shrink-0 bg-slate-900/50 backdrop-blur-md border-b border-slate-800 px-8 flex items-center justify-between">
      <div class="flex items-center gap-2">
        <Settings class="w-5 h-5 text-slate-400" />
        <h1 class="text-lg font-bold text-slate-100">系統設定</h1>
      </div>
    </div>

    <div class="flex-1 overflow-auto p-8">
      <div class="max-w-2xl space-y-6">
        <!-- 一般設定 -->
        <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
          <div class="px-6 py-4 border-b border-slate-700/50">
            <div class="flex items-center gap-2">
              <Globe class="w-4 h-4 text-emerald-400" />
              <h2 class="text-sm font-semibold text-slate-200">一般設定</h2>
              <Loader2 v-if="settingsLoading" class="w-4 h-4 text-slate-500 animate-spin ml-auto" />
            </div>
          </div>
          <div class="p-6 space-y-4">
            <div v-if="settingsLoading" class="text-sm text-slate-500">讀取中...</div>
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

        <!-- AI 設定 -->
        <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
          <div class="px-6 py-4 border-b border-slate-700/50">
            <div class="flex items-center gap-2">
              <Sparkles class="w-4 h-4 text-purple-400" />
              <h2 class="text-sm font-semibold text-slate-200">AI 設定</h2>
            </div>
          </div>
          <div class="p-6 space-y-4">
            <div>
              <label class="block text-xs font-medium text-slate-400 mb-1.5">Gemini API Key</label>
              <input
                v-model="form.gemini_api_key"
                type="password"
                placeholder="AIza..."
                class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none text-sm font-mono"
              />
              <p class="text-[11px] text-slate-500 mt-1">用於 AI 產生成員立繪。可在 <a href="https://aistudio.google.com/apikey" target="_blank" class="text-purple-400 hover:underline">Google AI Studio</a> 取得</p>
            </div>
          </div>
        </div>

        <!-- Google Cloud 認證 -->
        <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
          <div class="px-6 py-4 border-b border-slate-700/50">
            <div class="flex items-center gap-2">
              <CloudCog class="w-4 h-4 text-sky-400" />
              <h2 class="text-sm font-semibold text-slate-200">Google Cloud 認證</h2>
              <Loader2 v-if="gcloudStatusLoading" class="w-4 h-4 text-slate-500 animate-spin ml-auto" />
            </div>
          </div>
          <div class="p-6 space-y-4">
            <!-- 載入中 -->
            <div v-if="gcloudStatusLoading" class="text-sm text-slate-500">讀取中...</div>
            <template v-else>
            <!-- 狀態顯示 -->
            <div class="flex items-center gap-3">
              <div :class="[
                'w-2.5 h-2.5 rounded-full',
                gcloudStatus?.authenticated ? 'bg-emerald-400' : 'bg-slate-500'
              ]"></div>
              <div>
                <div class="text-sm text-slate-200">
                  {{ gcloudStatus?.authenticated ? '已認證' : '未認證' }}
                </div>
                <div v-if="gcloudStatus?.account" class="text-xs text-slate-400">
                  {{ gcloudStatus.account }}
                </div>
                <div v-else-if="!gcloudStatus?.installed" class="text-xs text-amber-400">
                  未安裝 gcloud CLI
                </div>
              </div>
            </div>

            <!-- 成功訊息 -->
            <div v-if="gcloudSuccess" class="p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-sm text-emerald-400">
              {{ gcloudSuccess }}
            </div>

            <!-- 錯誤訊息 -->
            <div v-if="gcloudError" class="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-sm text-red-400">
              {{ gcloudError }}
            </div>

            <!-- 引導式登入流程 -->
            <div v-if="gcloudAuthSession" class="space-y-4">
              <div class="p-4 bg-slate-900 rounded-lg space-y-3">
                <div class="text-xs font-medium text-slate-300">請完成以下步驟：</div>
                <ol class="text-xs text-slate-400 space-y-1.5 list-decimal list-inside">
                  <li v-for="(step, i) in gcloudAuthSession.instructions" :key="i">{{ step }}</li>
                </ol>
              </div>

              <!-- 授權網址 -->
              <div>
                <label class="block text-xs font-medium text-slate-400 mb-1.5">授權網址</label>
                <div class="flex gap-2">
                  <input
                    :value="gcloudAuthSession.auth_url"
                    readonly
                    class="flex-1 bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 text-xs font-mono truncate"
                  />
                  <button
                    @click="copyUrl"
                    class="px-3 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg transition-colors"
                    title="複製網址"
                  >
                    <Check v-if="copied" class="w-4 h-4 text-emerald-400" />
                    <Copy v-else class="w-4 h-4 text-slate-300" />
                  </button>
                  <a
                    :href="gcloudAuthSession.auth_url"
                    target="_blank"
                    class="px-3 py-2 bg-sky-500 hover:bg-sky-600 rounded-lg transition-colors"
                    title="在新分頁開啟"
                  >
                    <ExternalLink class="w-4 h-4 text-white" />
                  </a>
                </div>
              </div>

              <!-- 授權碼輸入 -->
              <div>
                <label class="block text-xs font-medium text-slate-400 mb-1.5">授權碼</label>
                <input
                  v-model="gcloudAuthCode"
                  type="text"
                  placeholder="貼上 Google 給您的授權碼..."
                  class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-sky-500 outline-none text-sm font-mono"
                  @keyup.enter="completeGcloudAuth"
                />
              </div>

              <!-- 按鈕 -->
              <div class="flex gap-2">
                <button
                  @click="completeGcloudAuth"
                  :disabled="gcloudLoading || !gcloudAuthCode.trim()"
                  class="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-sky-500 hover:bg-sky-600 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg font-bold text-sm transition-all"
                >
                  <Loader2 v-if="gcloudLoading" class="w-4 h-4 animate-spin" />
                  完成登入
                </button>
                <button
                  @click="cancelGcloudAuth"
                  class="px-4 py-2.5 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg font-bold text-sm transition-all"
                >
                  取消
                </button>
              </div>
            </div>

            <!-- 開始登入按鈕 -->
            <div v-else-if="gcloudStatus?.installed">
              <button
                @click="startGcloudAuth"
                :disabled="gcloudLoading"
                class="flex items-center gap-2 px-4 py-2.5 bg-sky-500 hover:bg-sky-600 disabled:opacity-50 text-white rounded-lg font-bold text-sm transition-all"
              >
                <Loader2 v-if="gcloudLoading" class="w-4 h-4 animate-spin" />
                <CloudCog v-else class="w-4 h-4" />
                {{ gcloudStatus?.authenticated ? '重新登入' : '引導式登入' }}
              </button>
              <p class="text-[11px] text-slate-500 mt-2">
                在此伺服器上登入 Google 帳號，用於 Gemini CLI 等 Google Cloud 服務。
              </p>
            </div>

            <!-- 未安裝提示 -->
            <div v-else class="text-xs text-slate-500">
              請先在伺服器上安裝 <a href="https://cloud.google.com/sdk/docs/install" target="_blank" class="text-sky-400 hover:underline">Google Cloud SDK</a>。
            </div>
            </template>
          </div>
        </div>

        <!-- CLI 安裝 -->
        <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
          <div class="px-6 py-4 border-b border-slate-700/50">
            <div class="flex items-center gap-2">
              <Terminal class="w-4 h-4 text-amber-400" />
              <h2 class="text-sm font-semibold text-slate-200">CLI 工具</h2>
              <Loader2 v-if="cliLoading" class="w-4 h-4 text-slate-500 animate-spin ml-auto" />
            </div>
          </div>
          <div class="p-6 space-y-4">
            <!-- 載入中 -->
            <div v-if="cliLoading" class="text-sm text-slate-500">讀取中...</div>
            <template v-else>
            <!-- 成功訊息 -->
            <div v-if="cliSuccess" class="p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-sm text-emerald-400">
              {{ cliSuccess }}
            </div>

            <!-- 錯誤訊息 -->
            <div v-if="cliError" class="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-sm text-red-400">
              {{ cliError }}
            </div>

            <!-- Claude CLI -->
            <div class="flex items-center justify-between p-4 bg-slate-900 rounded-lg">
              <div class="flex items-center gap-3">
                <div :class="[
                  'w-2.5 h-2.5 rounded-full',
                  cliStatus?.claude?.installed ? 'bg-emerald-400' : 'bg-slate-500'
                ]"></div>
                <div>
                  <div class="text-sm font-medium text-slate-200">Claude CLI</div>
                  <div class="text-xs text-slate-400">
                    <template v-if="cliStatus?.claude?.installed">
                      {{ cliStatus.claude.version || '已安裝' }}
                    </template>
                    <template v-else>未安裝</template>
                  </div>
                </div>
              </div>
              <button
                v-if="!cliStatus?.claude?.installed"
                @click="installCli('claude')"
                :disabled="cliInstalling !== null"
                class="flex items-center gap-2 px-3 py-1.5 bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-white rounded-lg text-xs font-medium transition-all"
              >
                <Loader2 v-if="cliInstalling === 'claude'" class="w-3 h-3 animate-spin" />
                <Download v-else class="w-3 h-3" />
                安裝
              </button>
              <span v-else class="text-xs text-emerald-400">✓ 已安裝</span>
            </div>

            <!-- Gemini CLI -->
            <div class="flex items-center justify-between p-4 bg-slate-900 rounded-lg">
              <div class="flex items-center gap-3">
                <div :class="[
                  'w-2.5 h-2.5 rounded-full',
                  cliStatus?.gemini?.installed ? 'bg-emerald-400' : 'bg-slate-500'
                ]"></div>
                <div>
                  <div class="text-sm font-medium text-slate-200">Gemini CLI</div>
                  <div class="text-xs text-slate-400">
                    <template v-if="cliStatus?.gemini?.installed">
                      {{ cliStatus.gemini.version || '已安裝' }}
                    </template>
                    <template v-else>未安裝</template>
                  </div>
                </div>
              </div>
              <button
                v-if="!cliStatus?.gemini?.installed"
                @click="installCli('gemini')"
                :disabled="cliInstalling !== null"
                class="flex items-center gap-2 px-3 py-1.5 bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-white rounded-lg text-xs font-medium transition-all"
              >
                <Loader2 v-if="cliInstalling === 'gemini'" class="w-3 h-3 animate-spin" />
                <Download v-else class="w-3 h-3" />
                安裝
              </button>
              <span v-else class="text-xs text-emerald-400">✓ 已安裝</span>
            </div>

            <p class="text-[11px] text-slate-500">
              CLI 工具用於執行 AI 任務。安裝需要幾分鐘時間。
            </p>
            </template>
          </div>
        </div>

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

        <!-- 儲存按鈕 -->
        <div class="flex justify-end">
          <button
            @click="saveSettings"
            :disabled="saving"
            class="flex items-center gap-2 px-6 py-2.5 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-lg font-bold text-sm transition-all shadow-lg shadow-emerald-500/20"
          >
            <Save class="w-4 h-4" />
            {{ saving ? '儲存中...' : '儲存設定' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
