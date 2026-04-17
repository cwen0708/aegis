<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Globe, Cpu, Save, Loader2, Lock, Sparkles, ShieldCheck, Github, CheckCircle2, Unplug, LogOut, Mic } from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'
import { useAuthStore } from '../../stores/auth'
import { useAsyncOp } from '../../composables/useAsyncOperation'

import { config } from '../../config'
import { authHeaders } from '../../utils/authFetch'

const store = useAegisStore()
const auth = useAuthStore()
const API = config.apiUrl

function handleLogout() {
  auth.logout()
  window.location.reload()
}

// Worker 暫停控制
const workerPaused = ref(false)
const workerToggling = ref(false)

function loadWorkerStatus() {
  workerPaused.value = store.settings.worker_paused === 'true'
}

async function toggleWorkerPaused() {
  workerToggling.value = true
  try {
    const endpoint = workerPaused.value ? 'resume' : 'pause'
    const res = await fetch(`${API}/api/v1/runner/${endpoint}`, { method: 'POST', headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      workerPaused.value = data.is_paused
      store.addToast(workerPaused.value ? 'Worker 已暫停' : 'Worker 已恢復', 'success')
    }
  } catch {
    store.addToast('操作失敗', 'error')
  } finally {
    workerToggling.value = false
  }
}

async function toggleTtsEnabled() {
  const newVal = !ttsEnabled.value
  try {
    await store.updateSettings({ tts_enabled: String(newVal) })
    ttsEnabled.value = newVal
    store.addToast(newVal ? '語音已啟用' : '語音已關閉', 'success')
  } catch { store.addToast('操作失敗', 'error') }
}

async function changeTtsProvider(provider: string) {
  try {
    await store.updateSettings({ tts_provider: provider })
    ttsProvider.value = provider
    store.addToast(`TTS 已切換為 ${{ web: '瀏覽器語音', gemini: 'Gemini TTS', ttsmaker: 'TTSMaker' }[provider] || provider}`, 'success')
  } catch { store.addToast('操作失敗', 'error') }
}

async function toggleLoginToView() {
  const newVal = !requireLoginToView.value
  try {
    await store.updateSettings({ require_login_to_view: String(newVal) })
    requireLoginToView.value = newVal
    auth.requireLoginToView = newVal
  } catch {
    store.addToast('設定失敗', 'error')
  }
}

const { loading, saving, run } = useAsyncOp()

const requireLoginToView = ref(false)
const ttsEnabled = ref(false)
const ttsProvider = ref('web')

// Talk Phase 2 — 語音對話設定
const STT_PROVIDERS = ['gemini', 'elevenlabs', 'deepgram'] as const
const TALK_TTS_MODELS = ['eleven_flash_v2_5', 'eleven_multilingual_v2'] as const
type SttProvider = (typeof STT_PROVIDERS)[number]
type TalkTtsModel = (typeof TALK_TTS_MODELS)[number]

const talk = ref<{
  stt_provider: SttProvider
  talk_tts_model: TalkTtsModel
  talk_bgm_enabled: boolean
  /** 已儲存值（後端回傳可能為 masked `***xxxx`） */
  deepgram_api_key_masked: string
  /** 使用者新輸入的值；空字串代表保留原值、不覆寫 */
  deepgram_api_key_new: string
}>({
  stt_provider: 'elevenlabs',
  talk_tts_model: 'eleven_flash_v2_5',
  talk_bgm_enabled: true,
  deepgram_api_key_masked: '',
  deepgram_api_key_new: '',
})

const form = ref({
  timezone: 'Asia/Taipei',
  max_workstations: '3',
  poll_interval: '3',
  memory_short_term_days: '30',
  gemini_api_key: '',
  ttsmaker_api_key: '',
  skill_confidence_threshold: 0.5,
})

// 密碼修改
const passwordForm = ref({
  current: '',
  new: '',
  confirm: '',
})
const passwordSaving = ref(false)
const passwordError = ref('')
const passwordSuccess = ref('')

async function changePassword() {
  passwordError.value = ''
  passwordSuccess.value = ''

  if (!passwordForm.value.current) {
    passwordError.value = '請輸入目前密碼'
    return
  }
  if (!passwordForm.value.new || passwordForm.value.new.length < 6) {
    passwordError.value = '新密碼至少需要 6 個字元'
    return
  }
  if (passwordForm.value.new !== passwordForm.value.confirm) {
    passwordError.value = '新密碼與確認密碼不符'
    return
  }

  passwordSaving.value = true
  try {
    const res = await fetch(`${API}/api/v1/auth/change-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        current_password: passwordForm.value.current,
        new_password: passwordForm.value.new,
      }),
    })
    const data = await res.json()
    if (res.ok) {
      passwordSuccess.value = '密碼已更新'
      passwordForm.value = { current: '', new: '', confirm: '' }
      // 清除登入狀態，下次進入需重新驗證
      localStorage.removeItem('aegis-admin-auth')
    } else {
      passwordError.value = data.detail || '修改失敗'
    }
  } catch {
    passwordError.value = '修改失敗，請稍後再試'
  } finally {
    passwordSaving.value = false
  }
}

// GitHub 連線
const githubStatus = ref<{ connected: boolean; login?: string; name?: string; error?: string }>({ connected: false })
const githubToken = ref('')
const githubVerifying = ref(false)
const githubLoading = ref(true)

async function fetchGithubStatus() {
  githubLoading.value = true
  try {
    const res = await fetch(`${API}/api/v1/github/status`)
    if (res.ok) githubStatus.value = await res.json()
  } catch {}
  githubLoading.value = false
}

async function connectGithub() {
  if (!githubToken.value.trim()) return
  githubVerifying.value = true
  try {
    const res = await fetch(`${API}/api/v1/github/verify`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ token: githubToken.value.trim() }),
    })
    if (!res.ok) {
      const data = await res.json()
      store.addToast(data.detail || 'Token 無效', 'error')
      return
    }
    // 驗證成功，儲存 token
    await store.updateSettings({ github_pat: githubToken.value.trim() })
    githubToken.value = ''
    await fetchGithubStatus()
    store.addToast('GitHub 已連線', 'success')
  } catch {
    store.addToast('連線失敗', 'error')
  } finally {
    githubVerifying.value = false
  }
}

async function disconnectGithub() {
  await store.updateSettings({ github_pat: '' })
  githubStatus.value = { connected: false }
  store.addToast('GitHub 已斷開', 'info')
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
  await Promise.all([store.fetchSettings(), fetchGithubStatus()])
  loadWorkerStatus()
  form.value.timezone = store.settings.timezone || 'Asia/Taipei'
  form.value.max_workstations = store.settings.max_workstations || '3'
  form.value.poll_interval = store.settings.poll_interval || '3'
  form.value.memory_short_term_days = store.settings.memory_short_term_days || '30'
  form.value.gemini_api_key = store.settings.gemini_api_key || ''
  form.value.ttsmaker_api_key = store.settings.ttsmaker_api_key || ''
  form.value.skill_confidence_threshold = parseFloat(store.settings.skill_confidence_threshold || '0.5')
  requireLoginToView.value = store.settings.require_login_to_view === 'true'
  ttsEnabled.value = store.settings.tts_enabled === 'true'
  ttsProvider.value = store.settings.tts_provider || (store.settings.tts_gemini === 'true' ? 'gemini' : 'web')

  // Talk Phase 2 設定讀取（各值有 fallback，對應 seed 的預設）
  const sttSetting = store.settings.stt_provider ?? ''
  talk.value.stt_provider = (STT_PROVIDERS as readonly string[]).includes(sttSetting)
    ? (sttSetting as SttProvider)
    : 'elevenlabs'
  const ttsModelSetting = store.settings.talk_tts_model ?? ''
  talk.value.talk_tts_model = (TALK_TTS_MODELS as readonly string[]).includes(ttsModelSetting)
    ? (ttsModelSetting as TalkTtsModel)
    : 'eleven_flash_v2_5'
  // talk_bgm_enabled 預設 true（未設或非 'false' 都視為開啟）
  talk.value.talk_bgm_enabled = store.settings.talk_bgm_enabled !== 'false'
  talk.value.deepgram_api_key_masked = store.settings.deepgram_api_key || ''
  talk.value.deepgram_api_key_new = ''

  loading.value = false
})

async function saveSettings() {
  // 收集 Talk 設定；deepgram_api_key 僅在使用者填了新值時才送出，避免把 masked 值寫回
  const talkPayload: Record<string, string> = {
    stt_provider: talk.value.stt_provider,
    talk_tts_model: talk.value.talk_tts_model,
    talk_bgm_enabled: String(talk.value.talk_bgm_enabled),
  }
  const newDeepgramKey = talk.value.deepgram_api_key_new.trim()
  if (newDeepgramKey) {
    talkPayload.deepgram_api_key = newDeepgramKey
  }

  await run(() => store.updateSettings({
    timezone: form.value.timezone,
    max_workstations: form.value.max_workstations,
    poll_interval: form.value.poll_interval,
    memory_short_term_days: form.value.memory_short_term_days,
    gemini_api_key: form.value.gemini_api_key,
    ttsmaker_api_key: form.value.ttsmaker_api_key,
    skill_confidence_threshold: String(form.value.skill_confidence_threshold),
    ...talkPayload,
  }))

  // 儲存成功後，若有新 key 已寫入，把 masked 置換掉並清空 new 欄位
  if (newDeepgramKey) {
    talk.value.deepgram_api_key_masked = store.settings.deepgram_api_key || ''
    talk.value.deepgram_api_key_new = ''
  }
}
</script>

<template>
  <div class="max-w-2xl space-y-6">
    <!-- Header Actions (Teleport to layout header) -->
    <Teleport to="#settings-header-actions">
      <button
        @click="saveSettings"
        :disabled="saving || loading"
        class="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-lg font-bold text-xs transition-all"
      >
        <Loader2 v-if="saving" class="w-3.5 h-3.5 animate-spin" />
        <Save v-else class="w-3.5 h-3.5" />
        {{ saving ? '儲存中' : '儲存' }}
      </button>
    </Teleport>

    <!-- 一般設定 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Globe class="w-4 h-4 text-emerald-400" />
          <h2 class="text-sm font-semibold text-slate-200">一般設定</h2>
          <Loader2 v-if="loading" class="w-4 h-4 text-slate-500 animate-spin ml-auto" />
        </div>
      </div>
      <div class="p-6 space-y-4">
        <div v-if="loading" class="text-sm text-slate-500">讀取中...</div>
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
        <!-- Worker 暫停開關 -->
        <div class="flex items-center justify-between">
          <div>
            <label class="block text-xs font-medium text-slate-400">Worker 任務執行</label>
            <p class="text-[11px] text-slate-500 mt-0.5">暫停後 Worker 不會拾取新的 pending 卡片</p>
          </div>
          <button
            @click="toggleWorkerPaused"
            :disabled="workerToggling"
            :class="[
              'relative w-11 h-6 rounded-full transition-colors',
              workerPaused ? 'bg-red-500/60' : 'bg-emerald-500'
            ]"
          >
            <div
              :class="[
                'absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform shadow',
                workerPaused ? 'left-0.5' : 'left-5.5'
              ]"
            ></div>
          </button>
        </div>

        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">工作台數量</label>
          <input
            v-model="form.max_workstations"
            type="number"
            min="1"
            max="10"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none text-sm font-mono"
          />
          <p class="text-[11px] text-slate-500 mt-1">同時間可使用的工作台數量</p>
        </div>
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">輪詢間隔（秒）</label>
          <input
            v-model="form.poll_interval"
            type="number"
            min="1"
            max="60"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none text-sm font-mono"
          />
          <p class="text-[11px] text-slate-500 mt-1">Worker 掃描待執行卡片的頻率（1~60 秒，預設 3）</p>
        </div>
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">短期記憶保留天數</label>
          <input
            v-model="form.memory_short_term_days"
            type="number"
            min="1"
            max="365"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none text-sm font-mono"
          />
          <p class="text-[11px] text-slate-500 mt-1">AEGIS 系統短期記憶的保留天數，超過自動清理</p>
        </div>
        <div>
          <div class="flex items-center justify-between mb-1.5">
            <label class="block text-xs font-medium text-slate-400">Skill 自動生成信心閾值</label>
            <span class="text-xs font-mono text-emerald-400">{{ form.skill_confidence_threshold.toFixed(2) }}</span>
          </div>
          <input
            v-model.number="form.skill_confidence_threshold"
            type="range"
            min="0"
            max="1"
            step="0.05"
            class="w-full accent-emerald-500"
          />
          <div class="flex justify-between text-[10px] text-slate-600 mt-0.5">
            <span>0.0（全部生成）</span>
            <span>1.0（最嚴格）</span>
          </div>
          <p class="text-[11px] text-slate-500 mt-1">自動生成 Skill 時，低於此信心分數的草稿不會被採用（預設 0.5）</p>
        </div>
      </div>
    </div>

    <!-- GitHub 連線 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Github class="w-4 h-4 text-slate-300" />
          <h2 class="text-sm font-semibold text-slate-200">GitHub 連線</h2>
          <Loader2 v-if="githubLoading" class="w-3.5 h-3.5 text-slate-500 animate-spin ml-auto" />
        </div>
      </div>
      <div class="p-6 space-y-4">
        <!-- 已連線 -->
        <div v-if="githubStatus.connected" class="flex items-center justify-between">
          <div class="flex items-center gap-3">
            <CheckCircle2 class="w-5 h-5 text-emerald-400" />
            <div>
              <div class="text-sm text-slate-200 font-medium">{{ githubStatus.login }}</div>
              <div v-if="githubStatus.name" class="text-[11px] text-slate-500">{{ githubStatus.name }}</div>
            </div>
          </div>
          <button @click="disconnectGithub" class="flex items-center gap-1.5 px-3 py-1.5 text-xs text-red-400 hover:bg-red-400/10 rounded-lg transition-colors">
            <Unplug class="w-3.5 h-3.5" />
            斷開連線
          </button>
        </div>
        <!-- 未連線 -->
        <div v-else>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">Personal Access Token</label>
          <div class="flex gap-2">
            <input
              v-model="githubToken"
              type="text"
              autocomplete="off"
              placeholder="ghp_xxxx 或 github_pat_xxxx"
              class="flex-1 bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-slate-500 outline-none text-sm font-mono"
              @keyup.enter="connectGithub"
            />
            <button
              @click="connectGithub"
              :disabled="githubVerifying || !githubToken.trim()"
              class="flex items-center gap-1.5 px-4 py-2 bg-slate-600 hover:bg-slate-500 disabled:opacity-50 text-white rounded-lg text-xs font-medium transition-all"
            >
              <Loader2 v-if="githubVerifying" class="w-3.5 h-3.5 animate-spin" />
              {{ githubVerifying ? '驗證中...' : '連線' }}
            </button>
          </div>
          <p class="text-[11px] text-slate-500 mt-1.5">
            AI 成員執行任務時將使用此 Token 存取私有 Git 倉庫。可在
            <a href="https://github.com/settings/tokens" target="_blank" class="text-slate-400 hover:underline">GitHub Settings → Tokens</a> 建立
          </p>
        </div>
      </div>
    </div>

    <!-- 立繪生成 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Sparkles class="w-4 h-4 text-purple-400" />
          <h2 class="text-sm font-semibold text-slate-200">立繪生成</h2>
        </div>
      </div>
      <div class="p-6 space-y-4">
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">Gemini API Key</label>
          <input
            v-model="form.gemini_api_key"
            type="password"
            placeholder="AIza..."
            class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-purple-500 outline-none text-sm font-mono"
          />
          <p class="text-[11px] text-slate-500 mt-1">
            用於 AI 產生成員立繪。可在
            <a href="https://aistudio.google.com/apikey" target="_blank" class="text-purple-400 hover:underline">Google AI Studio</a> 取得
          </p>
        </div>
      </div>
    </div>

    <!-- 存取控制 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <ShieldCheck class="w-4 h-4 text-cyan-400" />
          <h2 class="text-sm font-semibold text-slate-200">存取控制</h2>
        </div>
      </div>
      <div class="p-6 space-y-4">
        <div class="flex items-center justify-between">
          <div>
            <label class="block text-xs font-medium text-slate-400">強制登入才能瀏覽</label>
            <p class="text-[11px] text-slate-500 mt-0.5">開啟後，未登入的使用者無法瀏覽任何頁面（會被導向登入畫面）</p>
            <p class="text-[11px] text-slate-500">關閉時，未登入可瀏覽但操作按鈕（新增、刪除、拖曳等）會被隱藏</p>
          </div>
          <button
            @click="toggleLoginToView"
            :class="[
              'relative w-11 h-6 rounded-full transition-colors shrink-0 ml-4',
              requireLoginToView ? 'bg-cyan-500' : 'bg-slate-600'
            ]"
          >
            <div
              :class="[
                'absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform shadow',
                requireLoginToView ? 'left-5.5' : 'left-0.5'
              ]"
            ></div>
          </button>
        </div>
      </div>
    </div>

    <!-- 語音播放 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Sparkles class="w-4 h-4 text-violet-400" />
          <h2 class="text-sm font-semibold text-slate-200">語音播放</h2>
        </div>
      </div>
      <div class="p-6 space-y-4">
        <div class="flex items-center justify-between">
          <div>
            <label class="block text-xs font-medium text-slate-400">啟用 AVG 對話語音</label>
            <p class="text-[11px] text-slate-500 mt-0.5">角色對話時自動播放語音。可在對話框用音量按鈕臨時開關。</p>
          </div>
          <button
            @click="toggleTtsEnabled"
            :class="['relative w-11 h-6 rounded-full transition-colors shrink-0 ml-4', ttsEnabled ? 'bg-violet-500' : 'bg-slate-600']"
          >
            <div :class="['absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform shadow', ttsEnabled ? 'left-5.5' : 'left-0.5']"></div>
          </button>
        </div>
        <div v-if="ttsEnabled" class="space-y-3">
          <div>
            <label class="block text-xs font-medium text-slate-400 mb-1">語音引擎</label>
            <select
              :value="ttsProvider"
              @change="changeTtsProvider(($event.target as HTMLSelectElement).value)"
              class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg text-sm focus:outline-none focus:border-violet-500"
            >
              <option value="web">瀏覽器內建語音（免費）</option>
              <option value="gemini">Gemini TTS（需 API Key）</option>
              <option value="ttsmaker">TTSMaker（需 API Key）</option>
            </select>
          </div>
          <div v-if="ttsProvider === 'ttsmaker'">
            <label class="block text-xs font-medium text-slate-400 mb-1">TTSMaker API Key</label>
            <input
              v-model="form.ttsmaker_api_key"
              type="password"
              placeholder="從 pro.ttsmaker.com 取得"
              class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg text-sm focus:outline-none focus:border-violet-500"
            />
            <p class="text-[11px] text-slate-500 mt-0.5">免費額度每月約 5000 字。<a href="https://pro.ttsmaker.com/api-platform/api-key-list" target="_blank" class="text-violet-400 hover:underline">取得 API Key</a></p>
          </div>
        </div>
      </div>
    </div>

    <!-- Talk 語音對話（Phase 2） -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Mic class="w-4 h-4 text-fuchsia-400" />
          <h2 class="text-sm font-semibold text-slate-200">Talk 語音對話</h2>
        </div>
      </div>
      <div class="p-6 space-y-4">
        <!-- STT Provider -->
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">即時語音辨識引擎（STT）</label>
          <select
            v-model="talk.stt_provider"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-fuchsia-500 outline-none text-sm"
          >
            <option value="elevenlabs">ElevenLabs Scribe v2（串流，預設）</option>
            <option value="deepgram">Deepgram Nova-3（zh-TW 備援）</option>
            <option value="gemini">Gemini 2.5 Flash（整段，最穩定）</option>
          </select>
          <p class="text-[11px] text-slate-500 mt-1">
            預設 ElevenLabs 即時串流（~150ms latency），zh-TW 品質不佳時可切 Deepgram；Gemini 為整段轉錄保底。
          </p>
        </div>

        <!-- Deepgram API Key -->
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">Deepgram API Key</label>
          <input
            v-model="talk.deepgram_api_key_new"
            type="password"
            autocomplete="off"
            :placeholder="talk.deepgram_api_key_masked ? `目前：${talk.deepgram_api_key_masked}（留空保留原值）` : '尚未設定'"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-fuchsia-500 outline-none text-sm font-mono"
          />
          <p class="text-[11px] text-slate-500 mt-1">
            備援 STT provider 金鑰。留空代表不變更。可在
            <a href="https://console.deepgram.com/" target="_blank" class="text-fuchsia-400 hover:underline">Deepgram Console</a> 取得。
          </p>
        </div>

        <!-- Talk TTS 模型 -->
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">Talk TTS 模型（ElevenLabs）</label>
          <select
            v-model="talk.talk_tts_model"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-fuchsia-500 outline-none text-sm"
          >
            <option value="eleven_flash_v2_5">Flash v2.5（低延遲 ~75ms，預設）</option>
            <option value="eleven_multilingual_v2">Multilingual v2（音質優先）</option>
          </select>
          <p class="text-[11px] text-slate-500 mt-1">
            語音對話使用的 TTS 模型。Flash 延遲最低、v2 音質較佳。
          </p>
        </div>

        <!-- BGM 開關 -->
        <div class="flex items-center justify-between">
          <div>
            <label class="block text-xs font-medium text-slate-400">長思考時播放背景音樂</label>
            <p class="text-[11px] text-slate-500 mt-0.5">
              AI 工具呼叫或長推理 3 秒以上時淡入 ambient BGM，TTS 一到自動 duck。
            </p>
          </div>
          <button
            type="button"
            @click="talk.talk_bgm_enabled = !talk.talk_bgm_enabled"
            :class="[
              'relative w-11 h-6 rounded-full transition-colors shrink-0 ml-4',
              talk.talk_bgm_enabled ? 'bg-fuchsia-500' : 'bg-slate-600'
            ]"
          >
            <div
              :class="[
                'absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform shadow',
                talk.talk_bgm_enabled ? 'left-5.5' : 'left-0.5'
              ]"
            ></div>
          </button>
        </div>
      </div>
    </div>

    <!-- 管理員密碼 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Lock class="w-4 h-4 text-amber-400" />
          <h2 class="text-sm font-semibold text-slate-200">管理員密碼</h2>
        </div>
      </div>
      <div class="p-6 space-y-4">
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">目前密碼</label>
          <input
            v-model="passwordForm.current"
            type="password"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-amber-500 outline-none text-sm"
          />
        </div>
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">新密碼</label>
          <input
            v-model="passwordForm.new"
            type="password"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-amber-500 outline-none text-sm"
          />
          <p class="text-[11px] text-slate-500 mt-1">至少 6 個字元</p>
        </div>
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">確認新密碼</label>
          <input
            v-model="passwordForm.confirm"
            type="password"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-amber-500 outline-none text-sm"
            @keyup.enter="changePassword"
          />
        </div>

        <div v-if="passwordError" class="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
          {{ passwordError }}
        </div>
        <div v-if="passwordSuccess" class="text-xs text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-3 py-2">
          {{ passwordSuccess }}
        </div>

        <div class="flex justify-end">
          <button
            @click="changePassword"
            :disabled="passwordSaving"
            class="flex items-center gap-2 px-4 py-2 bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-white rounded-lg font-bold text-xs transition-all"
          >
            <Loader2 v-if="passwordSaving" class="w-3.5 h-3.5 animate-spin" />
            {{ passwordSaving ? '更新中...' : '更新密碼' }}
          </button>
        </div>
      </div>
    </div>
    <!-- 登出 -->
    <div class="pt-4 border-t border-slate-700/50">
      <button
        @click="handleLogout"
        class="flex items-center gap-2 px-4 py-2 text-sm text-slate-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
      >
        <LogOut class="w-4 h-4" />
        登出管理員
      </button>
    </div>
  </div>
</template>
