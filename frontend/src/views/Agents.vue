<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Bot, User, RefreshCw, Sparkles, Plus, Edit3, Zap, Key, Terminal, ExternalLink, Copy, Loader2, CheckCircle } from 'lucide-vue-next'
import { useAegisStore } from '../stores/aegis'
import ConfirmDialog from '../components/ConfirmDialog.vue'

import { config } from '../config'
import { authHeaders } from '../utils/authFetch'

const store = useAegisStore()
const API = config.apiUrl

// Tab 狀態
const activeTab = ref<'claude' | 'gemini' | 'openai'>('claude')

const tabs = [
  { id: 'claude', name: 'Claude', icon: Bot, color: 'orange' },
  { id: 'gemini', name: 'Gemini', icon: Sparkles, color: 'blue' },
  { id: 'openai', name: 'OpenAI', icon: Zap, color: 'green' },
] as const

onMounted(() => {
  fetchClaudeUsage()
  fetchGeminiUsage()
  fetchAccounts()
  fetchTaskStats()
})

// ==========================================
// 任務統計
// ==========================================
const taskStats = ref<any>(null)

async function fetchTaskStats() {
  try {
    const res = await fetch(`${API}/api/v1/task-stats`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    taskStats.value = await res.json()
  } catch { /* silent */ }
}

function formatTokens(n: number) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

function getProviderStats(provider: string) {
  return taskStats.value?.by_provider?.[provider] || { tasks: 0, input_tokens: 0, output_tokens: 0, cost_usd: 0 }
}

// ==========================================
// 帳號管理
// ==========================================
interface AccountInfo {
  id: number
  provider: string
  name: string
  auth_type: 'api_key' | 'cli'
  api_key?: string
  has_api_key?: boolean
  credential_file: string
  subscription: string
  email: string
  is_healthy: boolean
  oauth_token?: string
  has_oauth_token?: boolean
  expires_at?: string | null
  expired?: boolean
  hours_until_expiry?: number | null
}

const accounts = ref<AccountInfo[]>([])
const showAccountDialog = ref(false)
const showEditAccountDialog = ref(false)
const editingAccount = ref<AccountInfo | null>(null)
const accountForm = ref({
  provider: 'claude' as 'claude' | 'gemini' | 'openai',
  name: '',
  auth_type: 'cli' as 'api_key' | 'cli',
  oauth_token: '',
  api_key: '',
})
const editAccountForm = ref({ name: '' })
const accountCreating = ref(false)
const accountError = ref('')

// 依 provider 過濾帳號
const accountsByProvider = computed(() => ({
  claude: accounts.value.filter(a => a.provider === 'claude'),
  gemini: accounts.value.filter(a => a.provider === 'gemini'),
  openai: accounts.value.filter(a => a.provider === 'openai'),
}))

async function fetchAccounts() {
  try {
    const res = await fetch(`${API}/api/v1/accounts`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    accounts.value = await res.json()
  } catch { /* silent */ }
}

// ==========================================
// gcloud Auth（Gemini CLI 用）
// ==========================================
const gcloudStatus = ref<{ installed: boolean; authenticated: boolean; account: string | null } | null>(null)
const gcloudAuthSession = ref<{ session_id: string; auth_url: string; instructions: string[] } | null>(null)
const gcloudAuthCode = ref('')
const gcloudLoading = ref(false)
const gcloudError = ref('')
const gcloudSuccess = ref('')

async function fetchGcloudStatus() {
  try {
    const res = await fetch(`${API}/api/v1/gcloud/status`)
    if (res.ok) gcloudStatus.value = await res.json()
    else gcloudStatus.value = { installed: false, authenticated: false, account: null }
  } catch {
    gcloudStatus.value = { installed: false, authenticated: false, account: null }
  }
}

async function startGcloudAuth() {
  gcloudLoading.value = true
  gcloudError.value = ''
  gcloudSuccess.value = ''
  try {
    const res = await fetch(`${API}/api/v1/gcloud/auth/init`, { method: 'POST', headers: authHeaders() })
    if (!res.ok) {
      const err = await res.json()
      throw new Error(err.detail || '啟動認證失敗')
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
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        session_id: gcloudAuthSession.value.session_id,
        auth_code: gcloudAuthCode.value.trim(),
      }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || '認證失敗')
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
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ session_id: gcloudAuthSession.value.session_id }),
    }).catch(() => {})
  }
  gcloudAuthSession.value = null
  gcloudAuthCode.value = ''
  gcloudError.value = ''
}

async function copyGcloudAuthUrl() {
  if (gcloudAuthSession.value?.auth_url) {
    await navigator.clipboard.writeText(gcloudAuthSession.value.auth_url)
    store.addToast('已複製連結', 'success')
  }
}

function openAddAccount(provider: 'claude' | 'gemini' | 'openai') {
  // Claude/Gemini 預設 CLI，OpenAI 預設 API Key
  const defaultAuthType = provider === 'openai' ? 'api_key' : 'cli'
  accountForm.value = {
    provider,
    name: '',
    auth_type: defaultAuthType,
    oauth_token: '',
    api_key: '',
  }
  accountError.value = ''
  // Gemini CLI 需要檢查 gcloud 狀態
  if (provider === 'gemini') {
    fetchGcloudStatus()
    // 重置 gcloud auth 狀態
    gcloudAuthSession.value = null
    gcloudAuthCode.value = ''
    gcloudError.value = ''
    gcloudSuccess.value = ''
  }
  showAccountDialog.value = true
}

async function createAccount() {
  accountCreating.value = true
  accountError.value = ''
  try {
    const payload: any = {
      provider: accountForm.value.provider,
      name: accountForm.value.name,
      auth_type: accountForm.value.auth_type,
    }
    // 根據認證類型設定對應欄位
    if (accountForm.value.auth_type === 'cli' && accountForm.value.oauth_token.trim()) {
      payload.oauth_token = accountForm.value.oauth_token.trim()
    }
    if (accountForm.value.auth_type === 'api_key' && accountForm.value.api_key.trim()) {
      payload.api_key = accountForm.value.api_key.trim()
    }
    const res = await fetch(`${API}/api/v1/accounts`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      const err = await res.json()
      throw new Error(err.detail)
    }
    store.addToast('帳號已新增', 'success')
    showAccountDialog.value = false
    await fetchAccounts()
    // 重新載入用量（新帳號可能影響顯示）
    if (accountForm.value.provider === 'claude') fetchClaudeUsage()
    if (accountForm.value.provider === 'gemini') fetchGeminiUsage()
  } catch (e: any) {
    accountError.value = e.message || '新增失敗'
  } finally {
    accountCreating.value = false
  }
}

function openEditAccountDialog(acc: AccountInfo) {
  editingAccount.value = acc
  editAccountForm.value = { name: acc.name }
  showEditAccountDialog.value = true
}

async function saveEditAccount() {
  if (!editingAccount.value) return
  try {
    const res = await fetch(`${API}/api/v1/accounts/${editingAccount.value.id}`, {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(editAccountForm.value),
    })
    if (!res.ok) throw new Error('儲存失敗')
    store.addToast('帳號已更新', 'success')
    showEditAccountDialog.value = false
    await fetchAccounts()
  } catch (e: any) {
    store.addToast(e.message || '更新失敗', 'error')
  }
}

// 刪除帳號確認
const confirmDeleteAccount = ref(false)

function requestDeleteAccount() {
  confirmDeleteAccount.value = true
}

async function doDeleteAccount() {
  if (!editingAccount.value) return
  try {
    const res = await fetch(`${API}/api/v1/accounts/${editingAccount.value.id}`, { method: 'DELETE', headers: authHeaders() })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    store.addToast('帳號已刪除', 'success')
    confirmDeleteAccount.value = false
    showEditAccountDialog.value = false
    await fetchAccounts()
  } catch {
    store.addToast('刪除失敗', 'error')
  }
}

function providerBadgeClass(provider: string) {
  if (provider === 'claude') return 'bg-orange-500/10 text-orange-400 border-orange-500/20'
  if (provider === 'gemini') return 'bg-blue-500/10 text-blue-400 border-blue-500/20'
  return 'bg-green-500/10 text-green-400 border-green-500/20'
}

function authTypeBadgeClass(authType: string) {
  return authType === 'cli'
    ? 'bg-purple-500/10 text-purple-400 border-purple-500/20'
    : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
}

function getDbAccountsByProvider(provider: string) {
  return accounts.value.filter(a => a.provider === provider)
}

// 根據 DB 帳號找對應的 claude usage 資料
function getClaudeUsage(dbAccount: any) {
  // credential_file: "default" → usage name: "default"
  // credential_file: "" → 沒有 usage
  if (!dbAccount.credential_file) return null
  return claudeAccounts.value.find(u => u.name === dbAccount.credential_file || u.name + '.json' === dbAccount.credential_file)
}

// Tab 顏色樣式
function getTabClasses(tabId: 'claude' | 'gemini' | 'openai', isActive: boolean) {
  const colors = {
    claude: {
      active: 'border-orange-500 text-orange-400 bg-orange-500/10',
      inactive: 'border-transparent text-slate-400 hover:text-orange-400 hover:border-orange-500/50',
    },
    gemini: {
      active: 'border-blue-500 text-blue-400 bg-blue-500/10',
      inactive: 'border-transparent text-slate-400 hover:text-blue-400 hover:border-blue-500/50',
    },
    openai: {
      active: 'border-green-500 text-green-400 bg-green-500/10',
      inactive: 'border-transparent text-slate-400 hover:text-green-400 hover:border-green-500/50',
    },
  } as const
  return isActive ? colors[tabId].active : colors[tabId].inactive
}


// Claude 用量
const claudeAccounts = ref<any[]>([])
const loadingClaude = ref(false)

const fetchClaudeUsage = async () => {
  loadingClaude.value = true
  try {
    const res = await fetch('/api/v1/claude/usage')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    claudeAccounts.value = data.accounts || data
  } catch (e) {
    console.error('Failed to fetch claude usage', e)
  } finally {
    loadingClaude.value = false
  }
}

// Gemini 用量
const geminiUsage = ref<any>(null)
const loadingGemini = ref(false)

const fetchGeminiUsage = async () => {
  loadingGemini.value = true
  try {
    const res = await fetch('/api/v1/gemini/usage')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    geminiUsage.value = await res.json()
  } catch (e) {
    console.error('Failed to fetch gemini usage', e)
  } finally {
    loadingGemini.value = false
  }
}

function utilizationColor(val: number) {
  if (val >= 90) return 'bg-red-500'
  if (val >= 70) return 'bg-amber-500'
  return 'bg-emerald-500'
}

function utilizationTextColor(val: number) {
  if (val >= 90) return 'text-red-400'
  if (val >= 70) return 'text-amber-400'
  return 'text-emerald-400'
}

function quotaUsed(remaining: number) {
  return Math.round((100 - remaining) * 10) / 10
}

function quotaBarColor(remaining: number) {
  const used = 100 - remaining
  if (used >= 90) return 'bg-red-500'
  if (used >= 70) return 'bg-amber-500'
  return 'bg-emerald-500'
}

function quotaTextColor(remaining: number) {
  const used = 100 - remaining
  if (used >= 90) return 'text-red-400'
  if (used >= 70) return 'text-amber-400'
  return 'text-emerald-400'
}

function formatResetTime(isoStr: string) {
  if (!isoStr) return ''
  try {
    const d = new Date(isoStr)
    const nowDate = new Date()
    const diffMs = d.getTime() - nowDate.getTime()
    if (diffMs <= 0) return '已重置'
    const hours = Math.floor(diffMs / 3600000)
    const mins = Math.floor((diffMs % 3600000) / 60000)
    if (hours > 24) {
      const days = Math.floor(hours / 24)
      return `${days}天${hours % 24}時後重置`
    }
    return `${hours}時${mins}分後重置`
  } catch {
    return ''
  }
}
</script>

<template>
  <div class="max-w-4xl space-y-6">

    <!-- Tab 導航 -->
    <div class="border-b border-slate-700/50">
      <nav class="flex gap-1 -mb-px">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          @click="activeTab = tab.id"
          class="flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-all rounded-t-lg"
          :class="getTabClasses(tab.id, activeTab === tab.id)"
        >
          <component :is="tab.icon" class="w-4 h-4" />
          {{ tab.name }}
          <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-700/50 text-slate-400 font-mono">
            {{ accountsByProvider[tab.id].length }}
          </span>
        </button>
      </nav>
    </div>

    <!-- Tab 內容區：工具列 -->
    <div class="flex items-center justify-between">
      <div class="text-xs text-slate-500">
        共 {{ accountsByProvider[activeTab].length }} 個帳號
      </div>
      <div class="flex items-center gap-1">
        <button
          @click="openAddAccount(activeTab)"
          class="flex items-center gap-1 px-3 py-1.5 text-xs text-slate-300 hover:text-emerald-400 hover:bg-emerald-500/10 rounded-lg transition-colors border border-slate-700/50"
        >
          <Plus class="w-3.5 h-3.5" />
          新增帳號
        </button>
        <button
          @click="activeTab === 'claude' ? fetchClaudeUsage() : fetchGeminiUsage()"
          class="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-colors"
          :class="{ 'animate-spin': activeTab === 'claude' ? loadingClaude : loadingGemini }"
        >
          <RefreshCw class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>

    <!-- Claude Tab -->
    <div v-if="activeTab === 'claude'">
      <div v-if="accountsByProvider.claude.length === 0 && !loadingClaude" class="bg-slate-800/30 rounded-xl border border-slate-700/50 p-8 text-center">
        <Bot class="w-10 h-10 mx-auto mb-3 text-slate-600" />
        <p class="text-sm text-slate-400 mb-1">尚無 Claude 帳號</p>
        <p class="text-xs text-slate-500">點擊「新增帳號」以 OAuth Token 或 API Key 方式新增</p>
      </div>

      <div v-else class="space-y-3">
        <div
          v-for="acc in accountsByProvider.claude"
          :key="acc.id"
          class="bg-slate-800/80 rounded-xl border overflow-hidden border-slate-700"
        >
          <div class="flex">
            <!-- 左：帳號 + 用量 -->
            <div class="flex-1 p-5 min-w-0">
              <!-- 帳號標題 -->
              <div class="flex items-center gap-2 mb-3">
                <div class="w-7 h-7 rounded-lg bg-orange-500/20 border border-orange-500/30 flex items-center justify-center shrink-0">
                  <User class="w-3.5 h-3.5 text-orange-400" />
                </div>
                <div class="min-w-0 flex-1">
                  <div class="text-sm font-semibold text-slate-100 truncate">{{ acc.name }}</div>
                  <div class="flex items-center gap-1.5 text-[10px] text-slate-500 font-mono flex-wrap">
                    <span>{{ acc.subscription || 'unknown' }}</span>
                    <span
                      class="px-1 py-0.5 rounded border text-[9px]"
                      :class="authTypeBadgeClass(acc.auth_type || 'cli')"
                    >
                      {{ acc.auth_type === 'api_key' ? 'API' : 'CLI' }}
                    </span>
                    <span v-if="acc.has_oauth_token && !acc.expired" class="flex items-center gap-1 text-emerald-400">
                      <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block"></span>
                      OAuth 有效
                    </span>
                    <span v-else-if="acc.has_oauth_token && acc.expired" class="text-red-400">Token 已過期</span>
                    <span v-else-if="acc.credential_file" class="flex items-center gap-1 text-sky-400">
                      <span class="w-1.5 h-1.5 rounded-full bg-sky-400 inline-block"></span>
                      CLI 認證
                    </span>
                    <span v-else class="text-yellow-500">未設定認證</span>
                    <span v-if="acc.expires_at && !acc.expired" class="text-emerald-500">
                      有效至 {{ new Date(acc.expires_at).toLocaleDateString('zh-TW') }}
                    </span>
                  </div>
                </div>
                <button
                  @click.stop="openEditAccountDialog(acc)"
                  class="p-1.5 rounded-lg hover:bg-slate-700/50 text-slate-500 hover:text-slate-300 transition-colors shrink-0"
                >
                  <Edit3 class="w-3.5 h-3.5" />
                </button>
              </div>

              <!-- 用量 bars（從 usage API 取得） -->
              <template v-if="getClaudeUsage(acc)?.usage">
                <div class="space-y-2">
                  <div v-if="getClaudeUsage(acc)!.usage.five_hour" class="space-y-0.5">
                    <div class="flex justify-between text-[11px]">
                      <span class="text-slate-400">5h</span>
                      <span :class="utilizationTextColor(getClaudeUsage(acc)!.usage.five_hour.utilization)" class="font-mono font-semibold">
                        {{ getClaudeUsage(acc)!.usage.five_hour.utilization }}%
                      </span>
                    </div>
                    <div class="w-full bg-slate-900/50 rounded-full h-1.5 overflow-hidden">
                      <div
                        :class="utilizationColor(getClaudeUsage(acc)!.usage.five_hour.utilization)"
                        class="h-1.5 rounded-full transition-all duration-500"
                        :style="{ width: `${Math.min(getClaudeUsage(acc)!.usage.five_hour.utilization, 100)}%` }"
                      ></div>
                    </div>
                    <div class="text-[10px] text-slate-600">{{ formatResetTime(getClaudeUsage(acc)!.usage.five_hour.resets_at) }}</div>
                  </div>

                  <div v-if="getClaudeUsage(acc)!.usage.seven_day" class="space-y-0.5">
                    <div class="flex justify-between text-[11px]">
                      <span class="text-slate-400">7d</span>
                      <span :class="utilizationTextColor(getClaudeUsage(acc)!.usage.seven_day.utilization)" class="font-mono font-semibold">
                        {{ getClaudeUsage(acc)!.usage.seven_day.utilization }}%
                      </span>
                    </div>
                    <div class="w-full bg-slate-900/50 rounded-full h-1.5 overflow-hidden">
                      <div
                        :class="utilizationColor(getClaudeUsage(acc)!.usage.seven_day.utilization)"
                        class="h-1.5 rounded-full transition-all duration-500"
                        :style="{ width: `${Math.min(getClaudeUsage(acc)!.usage.seven_day.utilization, 100)}%` }"
                      ></div>
                    </div>
                    <div class="text-[10px] text-slate-600">{{ formatResetTime(getClaudeUsage(acc)!.usage.seven_day.resets_at) }}</div>
                  </div>

                  <div v-if="getClaudeUsage(acc)!.usage.seven_day_sonnet" class="space-y-0.5">
                    <div class="flex justify-between text-[11px]">
                      <span class="text-slate-400">Sonnet 7d</span>
                      <span :class="utilizationTextColor(getClaudeUsage(acc)!.usage.seven_day_sonnet.utilization)" class="font-mono font-semibold">
                        {{ getClaudeUsage(acc)!.usage.seven_day_sonnet.utilization }}%
                      </span>
                    </div>
                    <div class="w-full bg-slate-900/50 rounded-full h-1.5 overflow-hidden">
                      <div
                        :class="utilizationColor(getClaudeUsage(acc)!.usage.seven_day_sonnet.utilization)"
                        class="h-1.5 rounded-full transition-all duration-500"
                        :style="{ width: `${Math.min(getClaudeUsage(acc)!.usage.seven_day_sonnet.utilization, 100)}%` }"
                      ></div>
                    </div>
                    <div class="text-[10px] text-slate-600">{{ formatResetTime(getClaudeUsage(acc)!.usage.seven_day_sonnet.resets_at) }}</div>
                  </div>

                  <div v-if="getClaudeUsage(acc)!.usage.seven_day_opus" class="space-y-0.5">
                    <div class="flex justify-between text-[11px]">
                      <span class="text-slate-400">Opus 7d</span>
                      <span :class="utilizationTextColor(getClaudeUsage(acc)!.usage.seven_day_opus.utilization)" class="font-mono font-semibold">
                        {{ getClaudeUsage(acc)!.usage.seven_day_opus.utilization }}%
                      </span>
                    </div>
                    <div class="w-full bg-slate-900/50 rounded-full h-1.5 overflow-hidden">
                      <div
                        :class="utilizationColor(getClaudeUsage(acc)!.usage.seven_day_opus.utilization)"
                        class="h-1.5 rounded-full transition-all duration-500"
                        :style="{ width: `${Math.min(getClaudeUsage(acc)!.usage.seven_day_opus.utilization, 100)}%` }"
                      ></div>
                    </div>
                    <div class="text-[10px] text-slate-600">{{ formatResetTime(getClaudeUsage(acc)!.usage.seven_day_opus.resets_at) }}</div>
                  </div>

                  <div v-if="getClaudeUsage(acc)!.usage.extra_usage?.is_enabled" class="pt-2 border-t border-slate-700/50">
                    <div class="flex justify-between text-[11px]">
                      <span class="text-slate-400">超額</span>
                      <span class="text-slate-300 font-mono text-[10px]">
                        ${{ ((getClaudeUsage(acc)!.usage.extra_usage.used_credits ?? 0) / 100).toFixed(2) }} / ${{ ((getClaudeUsage(acc)!.usage.extra_usage.monthly_limit ?? 0) / 100).toFixed(0) }}
                      </span>
                    </div>
                    <div v-if="(getClaudeUsage(acc)!.usage.extra_usage.monthly_limit ?? 0) > 0" class="mt-1 w-full bg-slate-900/50 rounded-full h-1.5 overflow-hidden">
                      <div
                        class="bg-sky-500 h-1.5 rounded-full transition-all duration-500"
                        :style="{ width: `${Math.min(((getClaudeUsage(acc)!.usage.extra_usage.used_credits ?? 0) / getClaudeUsage(acc)!.usage.extra_usage.monthly_limit) * 100, 100)}%` }"
                      ></div>
                    </div>
                  </div>
                </div>
              </template>
              <div v-else class="text-xs text-slate-500 text-center py-3">
                {{ acc.credential_file ? '無法取得用量' : '純 OAuth Token 帳號（無 CLI 認證檔）' }}
              </div>
            </div>

            <!-- 右：統計 -->
            <div class="w-64 shrink-0 p-5 border-l border-slate-700/30">
              <div v-if="taskStats" class="space-y-3">
                <div>
                  <div class="text-[10px] text-slate-500 uppercase tracking-wider">任務</div>
                  <div class="text-lg font-bold text-slate-100 font-mono">{{ getProviderStats('claude').tasks }}</div>
                </div>
                <div>
                  <div class="text-[10px] text-slate-500 uppercase tracking-wider">Tokens</div>
                  <div class="flex items-baseline gap-1">
                    <span class="text-sm font-bold text-slate-200 font-mono">{{ formatTokens(getProviderStats('claude').input_tokens) }}</span>
                    <span class="text-[10px] text-slate-500">in</span>
                    <span class="text-sm font-bold text-slate-200 font-mono">{{ formatTokens(getProviderStats('claude').output_tokens) }}</span>
                    <span class="text-[10px] text-slate-500">out</span>
                  </div>
                </div>
                <div>
                  <div class="text-[10px] text-slate-500 uppercase tracking-wider">費用</div>
                  <div class="text-sm font-bold text-emerald-400 font-mono">${{ getProviderStats('claude').cost_usd.toFixed(2) }}</div>
                </div>
              </div>
              <div v-else class="text-[10px] text-slate-600 text-center py-4">無統計資料</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Gemini Tab -->
    <div v-if="activeTab === 'gemini'">
      <div v-if="!geminiUsage && !loadingGemini && accountsByProvider.gemini.length === 0" class="bg-slate-800/30 rounded-xl border border-slate-700/50 p-8 text-center">
        <Sparkles class="w-10 h-10 mx-auto mb-3 text-slate-600" />
        <p class="text-sm text-slate-400 mb-1">尚無 Gemini 帳號</p>
        <p class="text-xs text-slate-500">點擊「新增帳號」以 API Key 方式新增</p>
      </div>

      <div
        v-else-if="geminiUsage"
        class="bg-slate-800/80 rounded-xl border border-slate-700 overflow-hidden"
      >
        <div class="flex">
          <!-- 左：帳號 + 用量 -->
          <div class="flex-1 p-5 min-w-0">
            <!-- 帳號標題 -->
            <div class="flex items-center gap-2 mb-3">
              <div class="w-7 h-7 rounded-lg bg-blue-500/20 border border-blue-500/30 flex items-center justify-center shrink-0">
                <Sparkles class="w-3.5 h-3.5 text-blue-400" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="text-sm font-semibold text-slate-100">
                  {{ getDbAccountsByProvider('gemini')[0]?.name || geminiUsage.account || 'Gemini CLI' }}
                </div>
                <div class="flex items-center gap-1.5 text-[10px] text-slate-500 font-mono">
                  <span>{{ getDbAccountsByProvider('gemini')[0]?.email || 'Google One AI Pro' }}</span>
                  <!-- 認證類型 Badge -->
                  <span
                    v-if="getDbAccountsByProvider('gemini')[0]?.auth_type"
                    class="px-1 py-0.5 rounded border text-[9px]"
                    :class="authTypeBadgeClass(getDbAccountsByProvider('gemini')[0]?.auth_type || 'api_key')"
                  >
                    {{ getDbAccountsByProvider('gemini')[0]?.auth_type === 'api_key' ? 'API' : 'CLI' }}
                  </span>
                  <span class="flex items-center gap-1 text-emerald-400">
                    <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block"></span>
                    使用中
                  </span>
                </div>
              </div>
              <button
                v-if="getDbAccountsByProvider('gemini')[0]"
                @click.stop="openEditAccountDialog(getDbAccountsByProvider('gemini')[0]!)"
                class="p-1.5 rounded-lg hover:bg-slate-700/50 text-slate-500 hover:text-slate-300 transition-colors shrink-0"
              >
                <Edit3 class="w-3.5 h-3.5" />
              </button>
            </div>

            <!-- 配額 (Google API) -->
            <div v-if="geminiUsage.quota && Object.keys(geminiUsage.quota).length" class="space-y-2">
              <div
                v-for="(q, model) in geminiUsage.quota"
                :key="model"
                class="space-y-0.5"
              >
                <div class="flex justify-between text-[11px]">
                  <span class="text-slate-400 font-mono">{{ model }}</span>
                  <span :class="quotaTextColor(q.remaining)" class="font-mono font-semibold">{{ quotaUsed(q.remaining) }}%</span>
                </div>
                <div class="w-full bg-slate-900/50 rounded-full h-1.5 overflow-hidden">
                  <div
                    :class="quotaBarColor(q.remaining)"
                    class="h-1.5 rounded-full transition-all duration-500"
                    :style="{ width: `${quotaUsed(q.remaining)}%` }"
                  ></div>
                </div>
                <div v-if="q.remaining <= 0" class="text-[10px] text-slate-600">{{ formatResetTime(q.reset_time) }}</div>
              </div>
            </div>
          </div>

          <!-- 右：統計 -->
          <div class="w-64 shrink-0 p-5 border-l border-slate-700/30">
            <div v-if="taskStats" class="space-y-3">
              <div>
                <div class="text-[10px] text-slate-500 uppercase tracking-wider">任務</div>
                <div class="text-lg font-bold text-slate-100 font-mono">{{ getProviderStats('gemini').tasks }}</div>
              </div>
              <div>
                <div class="text-[10px] text-slate-500 uppercase tracking-wider">Tokens</div>
                <div class="flex items-baseline gap-1">
                  <span class="text-sm font-bold text-slate-200 font-mono">{{ formatTokens(getProviderStats('gemini').input_tokens) }}</span>
                  <span class="text-[10px] text-slate-500">in</span>
                  <span class="text-sm font-bold text-slate-200 font-mono">{{ formatTokens(getProviderStats('gemini').output_tokens) }}</span>
                  <span class="text-[10px] text-slate-500">out</span>
                </div>
              </div>
              <div>
                <div class="text-[10px] text-slate-500 uppercase tracking-wider">費用</div>
                <div class="text-sm font-bold text-emerald-400 font-mono">${{ getProviderStats('gemini').cost_usd.toFixed(2) }}</div>
              </div>
            </div>
            <div v-else class="text-[10px] text-slate-600 text-center py-4">無統計資料</div>
          </div>
        </div>
      </div>
    </div>

    <!-- OpenAI Tab -->
    <div v-if="activeTab === 'openai'">
      <div v-if="accountsByProvider.openai.length === 0" class="bg-slate-800/30 rounded-xl border border-slate-700/50 p-8 text-center">
        <Zap class="w-10 h-10 mx-auto mb-3 text-slate-600" />
        <p class="text-sm text-slate-400 mb-1">尚無 OpenAI 帳號</p>
        <p class="text-xs text-slate-500">點擊「新增帳號」以 API Key 方式新增</p>
      </div>

      <div v-else class="space-y-3">
        <div
          v-for="acc in accountsByProvider.openai"
          :key="acc.id"
          class="bg-slate-800/80 rounded-xl border border-slate-700 overflow-hidden"
        >
          <div class="flex">
            <div class="flex-1 p-5 min-w-0">
              <div class="flex items-center gap-2 mb-3">
                <div class="w-7 h-7 rounded-lg bg-green-500/20 border border-green-500/30 flex items-center justify-center shrink-0">
                  <Zap class="w-3.5 h-3.5 text-green-400" />
                </div>
                <div class="min-w-0 flex-1">
                  <div class="text-sm font-semibold text-slate-100 truncate">{{ acc.name }}</div>
                  <div class="flex items-center gap-1.5 text-[10px] text-slate-500 font-mono">
                    <span class="px-1 py-0.5 rounded border text-[9px]" :class="authTypeBadgeClass(acc.auth_type)">
                      {{ acc.auth_type === 'api_key' ? 'API' : 'CLI' }}
                    </span>
                    <span v-if="acc.has_api_key" class="text-emerald-500">已設定 API Key</span>
                    <span v-if="acc.is_healthy" class="flex items-center gap-1 text-emerald-400">
                      <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block"></span>
                      正常
                    </span>
                  </div>
                </div>
                <button
                  @click.stop="openEditAccountDialog(acc)"
                  class="p-1.5 rounded-lg hover:bg-slate-700/50 text-slate-500 hover:text-slate-300 transition-colors shrink-0"
                >
                  <Edit3 class="w-3.5 h-3.5" />
                </button>
              </div>
              <div class="text-xs text-slate-500 text-center py-3">用量統計開發中</div>
            </div>

            <!-- 右：統計 -->
            <div class="w-64 shrink-0 p-5 border-l border-slate-700/30">
              <div v-if="taskStats" class="space-y-3">
                <div>
                  <div class="text-[10px] text-slate-500 uppercase tracking-wider">任務</div>
                  <div class="text-lg font-bold text-slate-100 font-mono">{{ getProviderStats('openai').tasks }}</div>
                </div>
                <div>
                  <div class="text-[10px] text-slate-500 uppercase tracking-wider">Tokens</div>
                  <div class="flex items-baseline gap-1">
                    <span class="text-sm font-bold text-slate-200 font-mono">{{ formatTokens(getProviderStats('openai').input_tokens) }}</span>
                    <span class="text-[10px] text-slate-500">in</span>
                    <span class="text-sm font-bold text-slate-200 font-mono">{{ formatTokens(getProviderStats('openai').output_tokens) }}</span>
                    <span class="text-[10px] text-slate-500">out</span>
                  </div>
                </div>
                <div>
                  <div class="text-[10px] text-slate-500 uppercase tracking-wider">費用</div>
                  <div class="text-sm font-bold text-emerald-400 font-mono">${{ getProviderStats('openai').cost_usd.toFixed(2) }}</div>
                </div>
              </div>
              <div v-else class="text-[10px] text-slate-600 text-center py-4">無統計資料</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Add Account Dialog -->
    <Teleport to="body">
      <div v-if="showAccountDialog" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" @click.self="showAccountDialog = false">
        <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-md p-6 space-y-4">
          <h3 class="text-sm font-bold text-slate-200">
            新增 {{ accountForm.provider === 'claude' ? 'Claude' : accountForm.provider === 'gemini' ? 'Gemini' : 'OpenAI' }} 帳號
          </h3>

          <!-- 錯誤訊息 -->
          <div v-if="accountError" class="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-xs text-red-400">
            {{ accountError }}
          </div>

          <!-- Claude 認證類型選擇 -->
          <div v-if="accountForm.provider === 'claude'" class="space-y-2">
            <label class="block text-xs text-slate-400">認證方式</label>
            <div class="flex gap-2">
              <button
                @click="accountForm.auth_type = 'cli'"
                class="flex-1 flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg border text-xs font-medium transition-all"
                :class="accountForm.auth_type === 'cli'
                  ? 'bg-purple-500/20 border-purple-500/50 text-purple-300'
                  : 'bg-slate-900 border-slate-700 text-slate-400 hover:border-slate-600'"
              >
                <Terminal class="w-4 h-4" />
                CLI Token
                <span class="text-[9px] px-1 py-0.5 bg-emerald-500/20 text-emerald-400 rounded">推薦</span>
              </button>
              <button
                @click="accountForm.auth_type = 'api_key'"
                class="flex-1 flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg border text-xs font-medium transition-all"
                :class="accountForm.auth_type === 'api_key'
                  ? 'bg-amber-500/20 border-amber-500/50 text-amber-300'
                  : 'bg-slate-900 border-slate-700 text-slate-400 hover:border-slate-600'"
              >
                <Key class="w-4 h-4" />
                API Key
              </button>
            </div>
          </div>

          <!-- Gemini 認證類型選擇 -->
          <div v-if="accountForm.provider === 'gemini'" class="space-y-2">
            <label class="block text-xs text-slate-400">認證方式</label>
            <div class="flex gap-2">
              <button
                @click="accountForm.auth_type = 'cli'"
                class="flex-1 flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg border text-xs font-medium transition-all"
                :class="accountForm.auth_type === 'cli'
                  ? 'bg-blue-500/20 border-blue-500/50 text-blue-300'
                  : 'bg-slate-900 border-slate-700 text-slate-400 hover:border-slate-600'"
              >
                <Terminal class="w-4 h-4" />
                gcloud 認證
                <span class="text-[9px] px-1 py-0.5 bg-emerald-500/20 text-emerald-400 rounded">推薦</span>
              </button>
              <button
                @click="accountForm.auth_type = 'api_key'"
                class="flex-1 flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg border text-xs font-medium transition-all"
                :class="accountForm.auth_type === 'api_key'
                  ? 'bg-amber-500/20 border-amber-500/50 text-amber-300'
                  : 'bg-slate-900 border-slate-700 text-slate-400 hover:border-slate-600'"
              >
                <Key class="w-4 h-4" />
                API Key
              </button>
            </div>
          </div>

          <!-- Claude CLI Token 說明與輸入 -->
          <template v-if="accountForm.provider === 'claude' && accountForm.auth_type === 'cli'">
            <div class="p-3 bg-slate-900/80 rounded-lg space-y-1.5 border border-slate-700/50">
              <div class="text-[11px] text-slate-400">
                <span class="text-purple-400 font-medium">步驟 1</span>：在<span class="text-purple-300">本地電腦</span>的終端機執行：
              </div>
              <code class="block bg-slate-800 px-2 py-1.5 rounded text-purple-300 text-xs font-mono">claude setup-token</code>
              <div class="text-[11px] text-slate-400">
                <span class="text-purple-400 font-medium">步驟 2</span>：依指示在瀏覽器完成 Claude 登入
              </div>
              <div class="text-[11px] text-slate-400">
                <span class="text-purple-400 font-medium">步驟 3</span>：複製產生的 Token（<code class="text-[10px]">sk-ant-oat01-...</code>）貼到下方
              </div>
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">OAuth Token <span class="text-emerald-400">（1 年有效）</span></label>
              <input
                v-model="accountForm.oauth_token"
                type="password"
                class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-sm text-slate-200 font-mono outline-none focus:ring-2 focus:ring-purple-500/50"
                placeholder="sk-ant-oat01-..."
              />
            </div>
          </template>

          <!-- Gemini CLI（gcloud 引導式登入） -->
          <template v-if="accountForm.provider === 'gemini' && accountForm.auth_type === 'cli'">
            <!-- 成功訊息 -->
            <div v-if="gcloudSuccess" class="p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-lg flex items-center gap-2">
              <CheckCircle class="w-4 h-4 text-emerald-400 shrink-0" />
              <span class="text-sm text-emerald-400">{{ gcloudSuccess }}</span>
            </div>

            <!-- 錯誤訊息 -->
            <div v-if="gcloudError" class="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-xs text-red-400">
              {{ gcloudError }}
            </div>

            <!-- gcloud 狀態顯示 -->
            <div v-if="gcloudStatus" class="p-3 bg-slate-900/80 rounded-lg border border-slate-700/50">
              <div class="flex items-center gap-2 mb-2">
                <div :class="['w-2.5 h-2.5 rounded-full', gcloudStatus.authenticated ? 'bg-emerald-400' : 'bg-slate-500']"></div>
                <span class="text-sm text-slate-200">{{ gcloudStatus.authenticated ? '已認證' : '未認證' }}</span>
                <span v-if="gcloudStatus.account" class="text-xs text-slate-400">{{ gcloudStatus.account }}</span>
              </div>
              <p v-if="!gcloudStatus.installed" class="text-[11px] text-amber-400">
                伺服器未安裝 gcloud CLI。請先安裝 <a href="https://cloud.google.com/sdk/docs/install" target="_blank" class="text-sky-400 hover:underline">Google Cloud SDK</a>。
              </p>
              <p v-else-if="gcloudStatus.authenticated" class="text-[11px] text-slate-500">
                已登入 Google 帳號，可直接使用 Gemini CLI。
              </p>
            </div>

            <!-- 引導式登入流程 -->
            <div v-if="gcloudStatus?.installed && !gcloudAuthSession" class="space-y-3">
              <button
                @click="startGcloudAuth"
                :disabled="gcloudLoading"
                class="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all"
                :class="gcloudStatus?.authenticated
                  ? 'bg-slate-700 hover:bg-slate-600 text-slate-300'
                  : 'bg-blue-500 hover:bg-blue-600 text-white'"
              >
                <Loader2 v-if="gcloudLoading" class="w-4 h-4 animate-spin" />
                <Terminal v-else class="w-4 h-4" />
                {{ gcloudStatus?.authenticated ? '重新認證' : '開始認證' }}
              </button>
              <p class="text-[10px] text-slate-500 text-center">
                認證資訊儲存在伺服器上，不會過期。
              </p>
            </div>

            <!-- 認證中：顯示 URL 和授權碼輸入 -->
            <div v-if="gcloudAuthSession" class="space-y-3">
              <div class="p-3 bg-blue-500/10 border border-blue-500/30 rounded-lg space-y-2">
                <p class="text-[11px] text-blue-400 font-medium">步驟 1：在瀏覽器中開啟以下連結</p>
                <div class="flex gap-2">
                  <input
                    :value="gcloudAuthSession.auth_url"
                    readonly
                    class="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-2 text-slate-200 text-xs font-mono truncate"
                  />
                  <button
                    @click="copyGcloudAuthUrl"
                    class="px-2.5 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg transition-colors"
                    title="複製連結"
                  >
                    <Copy class="w-3.5 h-3.5 text-slate-300" />
                  </button>
                  <a
                    :href="gcloudAuthSession.auth_url"
                    target="_blank"
                    class="px-2.5 py-2 bg-sky-500 hover:bg-sky-600 rounded-lg transition-colors"
                    title="開啟連結"
                  >
                    <ExternalLink class="w-3.5 h-3.5 text-white" />
                  </a>
                </div>
              </div>

              <div class="p-3 bg-slate-900/80 border border-slate-700/50 rounded-lg space-y-2">
                <p class="text-[11px] text-slate-400">步驟 2：完成 Google 登入後，將授權碼貼到下方</p>
                <input
                  v-model="gcloudAuthCode"
                  class="w-full bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-2 text-slate-200 text-sm font-mono outline-none focus:ring-2 focus:ring-blue-500/50"
                  placeholder="貼上授權碼..."
                />
              </div>

              <div class="flex gap-2">
                <button
                  @click="cancelGcloudAuth"
                  class="flex-1 px-4 py-2 text-xs text-slate-400 hover:text-slate-200 border border-slate-700 rounded-lg transition-colors"
                >
                  取消
                </button>
                <button
                  @click="completeGcloudAuth"
                  :disabled="gcloudLoading || !gcloudAuthCode.trim()"
                  class="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-blue-500 hover:bg-blue-600 disabled:opacity-50 text-white rounded-lg text-xs font-medium transition-all"
                >
                  <Loader2 v-if="gcloudLoading" class="w-3.5 h-3.5 animate-spin" />
                  完成認證
                </button>
              </div>
            </div>
          </template>

          <!-- API Key 輸入（Claude API / Gemini / OpenAI） -->
          <template v-if="accountForm.auth_type === 'api_key' || accountForm.provider === 'openai'">
            <div class="p-3 bg-slate-900/80 rounded-lg space-y-1.5 border border-slate-700/50">
              <div class="text-[11px] text-slate-400">
                <template v-if="accountForm.provider === 'claude'">
                  前往 <a href="https://console.anthropic.com/settings/keys" target="_blank" class="text-amber-400 hover:underline">Anthropic Console</a> 取得 API Key
                </template>
                <template v-else-if="accountForm.provider === 'gemini'">
                  前往 <a href="https://aistudio.google.com/apikey" target="_blank" class="text-blue-400 hover:underline">Google AI Studio</a> 取得 API Key
                </template>
                <template v-else>
                  前往 <a href="https://platform.openai.com/api-keys" target="_blank" class="text-green-400 hover:underline">OpenAI Platform</a> 取得 API Key
                </template>
              </div>
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">API Key</label>
              <input
                v-model="accountForm.api_key"
                type="password"
                class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-sm text-slate-200 font-mono outline-none focus:ring-2 focus:ring-amber-500/50"
                :placeholder="accountForm.provider === 'claude' ? 'sk-ant-api03-...' : accountForm.provider === 'gemini' ? 'AIza...' : 'sk-proj-...'"
              />
            </div>
          </template>

          <!-- 帳號名稱 -->
          <div>
            <label class="block text-xs text-slate-400 mb-1">顯示名稱</label>
            <input
              v-model="accountForm.name"
              class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-sm text-slate-200 outline-none focus:ring-2 focus:ring-emerald-500/50"
              placeholder="例：Max 帳號A"
            />
          </div>

          <div class="flex justify-end gap-2 pt-2">
            <button @click="showAccountDialog = false" class="px-4 py-2 text-xs text-slate-400 hover:text-slate-200 transition-colors">取消</button>
            <button
              @click="createAccount"
              :disabled="!accountForm.name || accountCreating"
              class="px-4 py-2 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-lg text-xs font-bold transition-all flex items-center gap-2"
            >
              <RefreshCw v-if="accountCreating" class="w-3 h-3 animate-spin" />
              確認新增
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Edit Account Dialog -->
    <Teleport to="body">
      <div v-if="showEditAccountDialog && editingAccount" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" @click.self="showEditAccountDialog = false">
        <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-sm p-6 space-y-4">
          <h3 class="text-sm font-bold text-slate-200">編輯帳號</h3>
          <div class="flex flex-wrap items-center gap-2 bg-slate-900/50 rounded-lg px-3 py-2.5">
            <span class="text-[10px] px-1.5 py-0.5 rounded border" :class="providerBadgeClass(editingAccount.provider)">
              {{ editingAccount.provider }}
            </span>
            <span class="text-[10px] px-1.5 py-0.5 rounded border" :class="authTypeBadgeClass(editingAccount.auth_type)">
              {{ editingAccount.auth_type === 'api_key' ? 'API Key' : 'CLI Token' }}
            </span>
            <span v-if="editingAccount.subscription" class="text-xs text-slate-500">{{ editingAccount.subscription }}</span>
            <span v-if="editingAccount.email" class="text-xs text-slate-600">{{ editingAccount.email }}</span>
            <span :class="editingAccount.is_healthy ? 'text-emerald-500' : 'text-red-400'" class="text-xs">
              {{ editingAccount.is_healthy ? '健康' : '異常' }}
            </span>
          </div>
          <div>
            <label class="block text-xs text-slate-400 mb-1">顯示名稱</label>
            <input v-model="editAccountForm.name" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-slate-200 outline-none" />
          </div>
          <div class="flex items-center justify-between pt-2">
            <button @click="requestDeleteAccount" class="px-3 py-2 text-xs text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg transition-colors">
              刪除帳號
            </button>
            <div class="flex gap-2">
              <button @click="showEditAccountDialog = false" class="px-4 py-2 text-xs text-slate-400 hover:text-slate-200 transition-colors">取消</button>
              <button @click="saveEditAccount" :disabled="!editAccountForm.name" class="px-4 py-2 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-lg text-xs font-bold transition-all">儲存</button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Delete Account Confirm -->
    <ConfirmDialog
      :show="confirmDeleteAccount"
      title="刪除帳號"
      message="確定刪除此帳號？相關的成員綁定也會移除。"
      confirm-text="刪除"
      @confirm="doDeleteAccount"
      @cancel="confirmDeleteAccount = false"
    />
  </div>
</template>
