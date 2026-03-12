<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Link, Wifi, WifiOff, CheckCircle2, AlertCircle, Loader2 } from 'lucide-vue-next'
import { config } from '../../config'

const API = config.apiUrl

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

// 配對表單
const form = ref({
  supabase_url: '',
  supabase_anon_key: '',
  pairing_code: '',
  device_name: '',
})

onMounted(async () => {
  await fetchStatus()
})

async function fetchStatus() {
  loading.value = true
  try {
    const resp = await fetch(`${API}/api/v1/node/pair/status`)
    if (resp.ok) {
      pairStatus.value = await resp.json()
      // 自動回填已知的 Supabase 連線資訊
      if (pairStatus.value?.supabase_url && !form.value.supabase_url) {
        form.value.supabase_url = pairStatus.value.supabase_url
      }
      if (pairStatus.value?.supabase_anon_key && !form.value.supabase_anon_key) {
        form.value.supabase_anon_key = pairStatus.value.supabase_anon_key
      }
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
  if (!form.value.supabase_url.trim()) {
    error.value = '請輸入 Supabase URL'
    return
  }
  if (!form.value.supabase_anon_key.trim()) {
    error.value = '請輸入 Supabase Anon Key'
    return
  }

  pairing.value = true
  try {
    const resp = await fetch(`${API}/api/v1/node/pair`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        supabase_url: form.value.supabase_url.trim(),
        supabase_anon_key: form.value.supabase_anon_key.trim(),
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
  <div class="space-y-6">
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
          <div class="text-xs text-slate-500 font-mono bg-slate-900 rounded-lg px-3 py-2 truncate">
            {{ pairStatus.supabase_url }}
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

        <!-- Supabase 連線（已有則隱藏） -->
        <template v-if="!form.supabase_url || !form.supabase_anon_key">
          <div>
            <label class="block text-xs font-medium text-slate-400 mb-1.5">Supabase URL</label>
            <input
              v-model="form.supabase_url"
              type="text"
              placeholder="https://xxx.supabase.co"
              class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200
                focus:ring-2 focus:ring-cyan-500 outline-none text-sm font-mono"
            />
          </div>
          <div>
            <label class="block text-xs font-medium text-slate-400 mb-1.5">Supabase Anon Key</label>
            <input
              v-model="form.supabase_anon_key"
              type="password"
              placeholder="eyJ..."
              class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200
                focus:ring-2 focus:ring-cyan-500 outline-none text-sm font-mono"
            />
            <p class="text-[11px] text-slate-500 mt-1">首次配對需輸入，之後會自動記住</p>
          </div>
        </template>

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
