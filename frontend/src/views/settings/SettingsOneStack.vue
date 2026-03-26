<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Link, Wifi, WifiOff, CheckCircle2, AlertCircle, Loader2, Users } from 'lucide-vue-next'
import { config } from '../../config'
import { authHeaders } from '../../utils/authFetch'
import { useAegisStore } from '../../stores/aegis'

const API = config.apiUrl
const store = useAegisStore()

// 狀態
const loading = ref(true)
const pairing = ref(false)
const error = ref('')
const success = ref('')

// 連線狀態
const pairStatus = ref<{
  enabled: boolean
  device_id: string | null
  device_name: string | null
  supabase_url: string | null
  supabase_anon_key: string | null
  connected: boolean
} | null>(null)

// 配對表單（URL 和 key 已寫死在後端，前端只需配對碼）
const form = ref({
  pairing_code: '',
  device_name: '',
})

// 團隊角色對應
const teamRoleDefs = [
  { key: 'marketing', label: '行銷經理', icon: '📣' },
  { key: 'finance', label: '財務主管', icon: '💰' },
  { key: 'pm', label: '專案經理', icon: '📋' },
  { key: 'tech', label: '技術主管', icon: '🔧' },
  { key: 'doc', label: '文管專員', icon: '🧠' },
]
const teamRoles = ref<Record<string, string>>({})
const members = ref<{ id: number; name: string; slug: string; avatar: string }[]>([])
const savingRoles = ref(false)

async function fetchTeamRoles() {
  try {
    const res = await fetch(`${API}/api/v1/node/team-roles`)
    if (res.ok) teamRoles.value = await res.json()
  } catch { /* ignore */ }
}

async function fetchMembers() {
  try {
    const res = await fetch(`${API}/api/v1/members`)
    if (res.ok) {
      const data = await res.json()
      members.value = (data.members || data).map((m: any) => ({
        id: m.id, name: m.name, slug: m.slug, avatar: m.avatar || '',
      }))
    }
  } catch { /* ignore */ }
}

async function saveTeamRoles() {
  savingRoles.value = true
  try {
    const res = await fetch(`${API}/api/v1/node/team-roles`, {
      method: 'PUT',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(teamRoles.value),
    })
    if (res.ok) {
      store.addToast('角色對應已儲存', 'success')
    } else {
      store.addToast('儲存失敗', 'error')
    }
  } catch {
    store.addToast('儲存失敗', 'error')
  } finally {
    savingRoles.value = false
  }
}

onMounted(async () => {
  await fetchStatus()
  if (pairStatus.value?.connected) {
    fetchMembers()
    fetchTeamRoles()
  }
})

async function fetchStatus() {
  loading.value = true
  try {
    const resp = await fetch(`${API}/api/v1/node/pair/status`)
    if (resp.ok) {
      pairStatus.value = await resp.json()
    }
  } catch (e) {
    console.error('Failed to fetch pair status:', e)
  } finally {
    loading.value = false
  }
}

async function handlePair() {
  error.value = ''
  success.value = ''

  const code = form.value.pairing_code.trim()
  if (!code) {
    error.value = '請輸入配對碼'
    return
  }

  pairing.value = true
  try {
    const resp = await fetch(`${API}/api/v1/node/pair`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        pairing_code: code.toUpperCase(),
        device_name: form.value.device_name.trim() || undefined,
      }),
    })

    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}))
      error.value = data.detail || `配對失敗 (${resp.status})`
      return
    }

    const result = await resp.json()
    success.value = `配對成功！裝置名稱：${result.device_name}`
    form.value.pairing_code = ''
    await fetchStatus()
  } catch (e: any) {
    error.value = `連線錯誤：${e.message}`
  } finally {
    pairing.value = false
  }
}
</script>

<template>
  <div class="max-w-2xl space-y-6">
    <!-- 簡介 -->
    <div class="bg-gradient-to-r from-violet-500/10 to-cyan-500/10 rounded-2xl border border-violet-500/20 p-6">
      <h2 class="text-sm font-bold text-slate-200 mb-1">OneStack — 一人公司的 AI 全棧指揮中心</h2>
      <p class="text-[11px] text-violet-400/80 font-medium mb-3">One Person. One Stack. Infinite Power.</p>
      <p class="text-xs text-slate-400 leading-relaxed">
        OneStack 是為獨立工作者打造的 AI 全棧營運平台，內建虛擬團隊（PM、Tech Lead、財務、行銷），
        從需求捕捉、專案管理、報價開票到客戶經營一站搞定。
        連線 Aegis 後，你可以從 OneStack 遠端派發任務、查看執行結果，讓雲端大腦指揮本地引擎。
      </p>
    </div>

    <!-- 連線狀態 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Link class="w-4 h-4 text-violet-400" />
          <h2 class="text-sm font-semibold text-slate-200">OneStack 連線</h2>
        </div>
      </div>
      <div class="p-6">
        <div v-if="loading" class="flex items-center gap-2 text-slate-400">
          <Loader2 class="w-4 h-4 animate-spin" />
          <span class="text-sm">檢查連線狀態...</span>
        </div>

        <!-- 已連線 -->
        <div v-else-if="pairStatus?.connected" class="space-y-3">
          <div class="flex items-center gap-3">
            <div class="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
              <Wifi class="w-5 h-5 text-emerald-400" />
            </div>
            <div>
              <p class="text-sm font-medium text-emerald-400">已連線到 OneStack</p>
              <p class="text-xs text-slate-500">
                裝置：{{ pairStatus.device_name }} ({{ pairStatus.device_id?.slice(0, 8) }}...)
              </p>
            </div>
          </div>
        </div>

        <!-- 未連線 -->
        <div v-else class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-xl bg-slate-700/50 border border-slate-600 flex items-center justify-center">
            <WifiOff class="w-5 h-5 text-slate-500" />
          </div>
          <div>
            <p class="text-sm font-medium text-slate-300">尚未連線</p>
            <p class="text-xs text-slate-500">在下方輸入配對碼以連線到 OneStack</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 團隊角色對應（已連線時顯示） -->
    <div v-if="pairStatus?.connected" class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Users class="w-4 h-4 text-cyan-400" />
          <h2 class="text-sm font-semibold text-slate-200">團隊角色對應</h2>
        </div>
        <p class="text-xs text-slate-500 mt-1">指定 OneStack 各角色由哪位 Aegis 成員負責，變更會同步到 OneStack。</p>
      </div>
      <div class="p-6 space-y-4">
        <div v-for="role in teamRoleDefs" :key="role.key" class="flex items-center gap-3">
          <span class="text-base w-6 text-center shrink-0">{{ role.icon }}</span>
          <span class="text-sm text-slate-300 w-20 shrink-0">{{ role.label }}</span>
          <select
            v-model="teamRoles[role.key]"
            class="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:ring-2 focus:ring-cyan-500 outline-none"
          >
            <option value="">（未指定）</option>
            <option v-for="m in members" :key="m.slug" :value="m.slug">
              {{ m.avatar }} {{ m.name }} ({{ m.slug }})
            </option>
          </select>
        </div>

        <button
          @click="saveTeamRoles"
          :disabled="savingRoles"
          class="w-full flex items-center justify-center gap-2 px-6 py-2.5
            bg-cyan-500 hover:bg-cyan-600 disabled:opacity-50
            text-white rounded-lg font-bold text-sm transition-all"
        >
          <Loader2 v-if="savingRoles" class="w-4 h-4 animate-spin" />
          儲存角色對應
        </button>
      </div>
    </div>

    <!-- 配對表單 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Link class="w-4 h-4 text-cyan-400" />
          <h2 class="text-sm font-semibold text-slate-200">
            {{ pairStatus?.connected ? '重新配對' : '配對連線' }}
          </h2>
        </div>
      </div>
      <div class="p-6 space-y-4">
        <!-- 配對碼 -->
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">配對碼</label>
          <input
            v-model="form.pairing_code"
            type="text"
            maxlength="6"
            placeholder="輸入 6 位配對碼"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200
              focus:ring-2 focus:ring-cyan-500 outline-none text-lg font-mono tracking-[0.5em]
              text-center uppercase placeholder:text-sm placeholder:tracking-normal"
            @keyup.enter="handlePair"
          />
          <p class="text-[11px] text-slate-500 mt-1">從 OneStack 設定頁取得配對碼</p>
        </div>

        <!-- 錯誤訊息 -->
        <div v-if="error" class="flex items-start gap-2 p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
          <AlertCircle class="w-4 h-4 text-red-400 mt-0.5 shrink-0" />
          <p class="text-sm text-red-400">{{ error }}</p>
        </div>

        <!-- 成功訊息 -->
        <div v-if="success" class="flex items-start gap-2 p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-lg">
          <CheckCircle2 class="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
          <p class="text-sm text-emerald-400">{{ success }}</p>
        </div>

        <!-- 配對按鈕 -->
        <button
          @click="handlePair"
          :disabled="pairing || !form.pairing_code.trim()"
          class="w-full flex items-center justify-center gap-2 px-6 py-2.5
            bg-cyan-500 hover:bg-cyan-600 disabled:opacity-50
            text-white rounded-lg font-bold text-sm transition-all
            shadow-lg shadow-cyan-500/20"
        >
          <Loader2 v-if="pairing" class="w-4 h-4 animate-spin" />
          <Link v-else class="w-4 h-4" />
          {{ pairing ? '配對中...' : '開始配對' }}
        </button>
      </div>
    </div>
  </div>
</template>
