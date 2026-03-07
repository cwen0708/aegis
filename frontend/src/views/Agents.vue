<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Bot, User, RefreshCw, Sparkles, Plus, Edit3 } from 'lucide-vue-next'
import { useAegisStore } from '../stores/aegis'

const store = useAegisStore()
const API = import.meta.env.DEV ? '' : 'http://localhost:8899'

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
  credential_file: string
  subscription: string
  email: string
  is_healthy: boolean
}

const accounts = ref<AccountInfo[]>([])
const showAccountDialog = ref(false)
const showEditAccountDialog = ref(false)
const editingAccount = ref<AccountInfo | null>(null)
const accountForm = ref({ provider: 'claude', name: '' })
const editAccountForm = ref({ name: '' })

async function fetchAccounts() {
  try {
    const res = await fetch(`${API}/api/v1/accounts`)
    accounts.value = await res.json()
  } catch { /* silent */ }
}

function openAddAccount(provider: string) {
  accountForm.value = { provider, name: '' }
  showAccountDialog.value = true
}

async function createAccount() {
  try {
    const res = await fetch(`${API}/api/v1/accounts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(accountForm.value),
    })
    if (!res.ok) {
      const err = await res.json()
      throw new Error(err.detail)
    }
    store.addToast('帳號已新增', 'success')
    showAccountDialog.value = false
    await fetchAccounts()
  } catch (e: any) {
    store.addToast(e.message || '新增失敗', 'error')
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
      headers: { 'Content-Type': 'application/json' },
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

async function deleteEditingAccount() {
  if (!editingAccount.value) return
  if (!confirm('確定刪除此帳號？相關的成員綁定也會移除。')) return
  try {
    await fetch(`${API}/api/v1/accounts/${editingAccount.value.id}`, { method: 'DELETE' })
    store.addToast('帳號已刪除', 'success')
    showEditAccountDialog.value = false
    await fetchAccounts()
  } catch {
    store.addToast('刪除失敗', 'error')
  }
}

function providerBadgeClass(provider: string) {
  return provider === 'claude'
    ? 'bg-orange-500/10 text-orange-400 border-orange-500/20'
    : 'bg-blue-500/10 text-blue-400 border-blue-500/20'
}

function getDbAccountsByProvider(provider: string) {
  return accounts.value.filter(a => a.provider === provider)
}


// Claude 用量
const claudeAccounts = ref<any[]>([])
const loadingClaude = ref(false)

const fetchClaudeUsage = async () => {
  loadingClaude.value = true
  try {
    const res = await fetch('/api/v1/claude/usage')
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
  <div class="h-full flex flex-col">
    <!-- Header h-16 -->
    <div class="sticky top-0 z-10 h-16 shrink-0 bg-slate-900/50 backdrop-blur-md border-b border-slate-800 px-8 flex items-center">
      <h1 class="text-lg font-bold text-slate-100">AI 代理</h1>
    </div>

    <div class="flex-1 overflow-auto p-8 space-y-6">

      <!-- Claude 區塊 -->
      <div>
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <Bot class="w-5 h-5 text-purple-400" />
            <h2 class="text-sm font-semibold text-slate-300 tracking-wider">Claude</h2>
          </div>
          <div class="flex items-center gap-1">
            <button
              @click="openAddAccount('claude')"
              class="flex items-center gap-1 px-2 py-1 text-[11px] text-slate-400 hover:text-emerald-400 hover:bg-emerald-500/10 rounded-lg transition-colors"
            >
              <Plus class="w-3 h-3" />
              新增
            </button>
            <button
              @click="fetchClaudeUsage"
              class="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-colors"
              :class="{ 'animate-spin': loadingClaude }"
            >
              <RefreshCw class="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <div v-if="claudeAccounts.length === 0 && !loadingClaude" class="bg-slate-800/30 rounded-xl border border-slate-700/50 p-8 text-center">
          <User class="w-8 h-8 mx-auto mb-2 text-slate-600" />
          <p class="text-xs text-slate-500">無帳號，請先在 CLI 登入後點「新增」</p>
        </div>

        <div v-else class="space-y-3">
          <div
            v-for="account in claudeAccounts"
            :key="account.name"
            class="bg-slate-800/80 rounded-xl border overflow-hidden"
            :class="account.is_active ? 'border-slate-700' : 'border-slate-700/50 opacity-60'"
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
                    <div class="text-sm font-semibold text-slate-100 truncate">
                      {{ getDbAccountsByProvider('claude').find(a => a.credential_file === account.name + '.json')?.name || account.name }}
                    </div>
                    <div class="flex items-center gap-1.5 text-[10px] text-slate-500 font-mono">
                      <span>{{ account.subscriptionType || 'unknown' }}</span>
                      <span v-if="account.is_active" class="flex items-center gap-1 text-emerald-400">
                        <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block"></span>
                        使用中
                      </span>
                    </div>
                  </div>
                  <button
                    v-if="getDbAccountsByProvider('claude').find(a => a.credential_file === account.name + '.json')"
                    @click.stop="openEditAccountDialog(getDbAccountsByProvider('claude').find(a => a.credential_file === account.name + '.json')!)"
                    class="p-1.5 rounded-lg hover:bg-slate-700/50 text-slate-500 hover:text-slate-300 transition-colors shrink-0"
                  >
                    <Edit3 class="w-3.5 h-3.5" />
                  </button>
                </div>

                <!-- 用量 bars -->
                <div v-if="account.usage" class="space-y-2">
                  <div v-if="account.usage.five_hour" class="space-y-0.5">
                    <div class="flex justify-between text-[11px]">
                      <span class="text-slate-400">5h</span>
                      <span :class="utilizationTextColor(account.usage.five_hour.utilization)" class="font-mono font-semibold">
                        {{ account.usage.five_hour.utilization }}%
                      </span>
                    </div>
                    <div class="w-full bg-slate-900/50 rounded-full h-1.5 overflow-hidden">
                      <div
                        :class="utilizationColor(account.usage.five_hour.utilization)"
                        class="h-1.5 rounded-full transition-all duration-500"
                        :style="{ width: `${Math.min(account.usage.five_hour.utilization, 100)}%` }"
                      ></div>
                    </div>
                    <div class="text-[10px] text-slate-600">{{ formatResetTime(account.usage.five_hour.resets_at) }}</div>
                  </div>

                  <div v-if="account.usage.seven_day" class="space-y-0.5">
                    <div class="flex justify-between text-[11px]">
                      <span class="text-slate-400">7d</span>
                      <span :class="utilizationTextColor(account.usage.seven_day.utilization)" class="font-mono font-semibold">
                        {{ account.usage.seven_day.utilization }}%
                      </span>
                    </div>
                    <div class="w-full bg-slate-900/50 rounded-full h-1.5 overflow-hidden">
                      <div
                        :class="utilizationColor(account.usage.seven_day.utilization)"
                        class="h-1.5 rounded-full transition-all duration-500"
                        :style="{ width: `${Math.min(account.usage.seven_day.utilization, 100)}%` }"
                      ></div>
                    </div>
                    <div class="text-[10px] text-slate-600">{{ formatResetTime(account.usage.seven_day.resets_at) }}</div>
                  </div>

                  <div v-if="account.usage.seven_day_sonnet" class="space-y-0.5">
                    <div class="flex justify-between text-[11px]">
                      <span class="text-slate-400">Sonnet 7d</span>
                      <span :class="utilizationTextColor(account.usage.seven_day_sonnet.utilization)" class="font-mono font-semibold">
                        {{ account.usage.seven_day_sonnet.utilization }}%
                      </span>
                    </div>
                    <div class="w-full bg-slate-900/50 rounded-full h-1.5 overflow-hidden">
                      <div
                        :class="utilizationColor(account.usage.seven_day_sonnet.utilization)"
                        class="h-1.5 rounded-full transition-all duration-500"
                        :style="{ width: `${Math.min(account.usage.seven_day_sonnet.utilization, 100)}%` }"
                      ></div>
                    </div>
                    <div class="text-[10px] text-slate-600">{{ formatResetTime(account.usage.seven_day_sonnet.resets_at) }}</div>
                  </div>

                  <div v-if="account.usage.seven_day_opus" class="space-y-0.5">
                    <div class="flex justify-between text-[11px]">
                      <span class="text-slate-400">Opus 7d</span>
                      <span :class="utilizationTextColor(account.usage.seven_day_opus.utilization)" class="font-mono font-semibold">
                        {{ account.usage.seven_day_opus.utilization }}%
                      </span>
                    </div>
                    <div class="w-full bg-slate-900/50 rounded-full h-1.5 overflow-hidden">
                      <div
                        :class="utilizationColor(account.usage.seven_day_opus.utilization)"
                        class="h-1.5 rounded-full transition-all duration-500"
                        :style="{ width: `${Math.min(account.usage.seven_day_opus.utilization, 100)}%` }"
                      ></div>
                    </div>
                    <div class="text-[10px] text-slate-600">{{ formatResetTime(account.usage.seven_day_opus.resets_at) }}</div>
                  </div>

                  <div v-if="account.usage.extra_usage && account.usage.extra_usage.is_enabled" class="pt-2 border-t border-slate-700/50">
                    <div class="flex justify-between text-[11px]">
                      <span class="text-slate-400">超額</span>
                      <span class="text-slate-300 font-mono text-[10px]">
                        ${{ ((account.usage.extra_usage.used_credits ?? 0) / 100).toFixed(2) }} / ${{ ((account.usage.extra_usage.monthly_limit ?? 0) / 100).toFixed(0) }}
                      </span>
                    </div>
                    <div v-if="(account.usage.extra_usage.monthly_limit ?? 0) > 0" class="mt-1 w-full bg-slate-900/50 rounded-full h-1.5 overflow-hidden">
                      <div
                        class="bg-sky-500 h-1.5 rounded-full transition-all duration-500"
                        :style="{ width: `${Math.min(((account.usage.extra_usage.used_credits ?? 0) / account.usage.extra_usage.monthly_limit) * 100, 100)}%` }"
                      ></div>
                    </div>
                  </div>
                </div>

                <div v-else class="text-xs text-slate-500 text-center py-3">無法取得用量</div>
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

      <!-- Gemini 區塊 -->
      <div>
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <Sparkles class="w-5 h-5 text-blue-400" />
            <h2 class="text-sm font-semibold text-slate-300 tracking-wider">Gemini</h2>
          </div>
          <div class="flex items-center gap-1">
            <button
              @click="openAddAccount('gemini')"
              class="flex items-center gap-1 px-2 py-1 text-[11px] text-slate-400 hover:text-emerald-400 hover:bg-emerald-500/10 rounded-lg transition-colors"
            >
              <Plus class="w-3 h-3" />
              新增
            </button>
            <button
              @click="fetchGeminiUsage"
              class="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-colors"
              :class="{ 'animate-spin': loadingGemini }"
            >
              <RefreshCw class="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <div v-if="!geminiUsage && !loadingGemini" class="bg-slate-800/30 rounded-xl border border-slate-700/50 p-8 text-center">
          <Sparkles class="w-8 h-8 mx-auto mb-2 text-slate-600" />
          <p class="text-xs text-slate-500">無法取得 Gemini 用量</p>
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
                    <span class="flex items-center gap-1 text-emerald-400">
                      <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block"></span>
                      使用中
                    </span>
                  </div>
                </div>
                <button
                  v-if="getDbAccountsByProvider('gemini')[0]"
                  @click.stop="openEditAccountDialog(getDbAccountsByProvider('gemini')[0])"
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

    </div>

    <!-- Add Account Dialog -->
    <Teleport to="body">
      <div v-if="showAccountDialog" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" @click.self="showAccountDialog = false">
        <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-sm p-6 space-y-4">
          <h3 class="text-sm font-bold text-slate-200">新增 {{ accountForm.provider === 'claude' ? 'Claude' : 'Gemini' }} 帳號</h3>
          <p class="text-[11px] text-slate-500">請先在 CLI 登入目標帳號，再填寫名稱擷取憑證。</p>
          <div>
            <label class="block text-xs text-slate-400 mb-1">顯示名稱</label>
            <input v-model="accountForm.name" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-slate-200 outline-none" placeholder="例：Max 小良" />
          </div>
          <div class="flex justify-end gap-2 pt-2">
            <button @click="showAccountDialog = false" class="px-4 py-2 text-xs text-slate-400 hover:text-slate-200 transition-colors">取消</button>
            <button @click="createAccount" :disabled="!accountForm.name" class="px-4 py-2 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-lg text-xs font-bold transition-all">確認新增</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Edit Account Dialog -->
    <Teleport to="body">
      <div v-if="showEditAccountDialog && editingAccount" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" @click.self="showEditAccountDialog = false">
        <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-sm p-6 space-y-4">
          <h3 class="text-sm font-bold text-slate-200">編輯帳號</h3>
          <div class="flex items-center gap-2 bg-slate-900/50 rounded-lg px-3 py-2.5">
            <span class="text-[10px] px-1.5 py-0.5 rounded border" :class="providerBadgeClass(editingAccount.provider)">
              {{ editingAccount.provider }}
            </span>
            <span class="text-xs text-slate-500">{{ editingAccount.subscription }}</span>
            <span class="text-xs text-slate-600">{{ editingAccount.email }}</span>
            <span :class="editingAccount.is_healthy ? 'text-emerald-500' : 'text-red-400'" class="text-xs">
              {{ editingAccount.is_healthy ? '健康' : '異常' }}
            </span>
          </div>
          <div>
            <label class="block text-xs text-slate-400 mb-1">顯示名稱</label>
            <input v-model="editAccountForm.name" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-slate-200 outline-none" />
          </div>
          <div class="flex items-center justify-between pt-2">
            <button @click="deleteEditingAccount" class="px-3 py-2 text-xs text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg transition-colors">
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
  </div>
</template>
