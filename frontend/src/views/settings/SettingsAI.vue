<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Sparkles, CloudCog, Terminal, Save, Loader2, ExternalLink, Copy, Check, Download } from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'

const store = useAegisStore()
const API = import.meta.env.DEV ? 'http://localhost:8899' : ''

// Gemini API Key
const settingsLoading = ref(true)
const saving = ref(false)
const geminiApiKey = ref('')

// CLI 狀態
const cliLoading = ref(true)
type CliInfo = { installed: boolean; version: string | null; path: string | null }
const cliStatus = ref<{
  claude: CliInfo;
  gemini: CliInfo;
  codex: CliInfo;
  ollama: CliInfo;
} | null>(null)
const cliInstalling = ref<'claude' | 'gemini' | 'codex' | 'ollama' | null>(null)
const cliError = ref('')
const cliSuccess = ref('')

// Gcloud 狀態
const gcloudStatusLoading = ref(true)
const gcloudStatus = ref<{ installed: boolean; authenticated: boolean; account: string | null } | null>(null)
const gcloudAuthSession = ref<{ session_id: string; auth_url: string; instructions: string[] } | null>(null)
const gcloudAuthCode = ref('')
const gcloudLoading = ref(false)
const gcloudError = ref('')
const gcloudSuccess = ref('')
const copied = ref(false)

// API 呼叫
async function fetchCliStatus() {
  cliLoading.value = true
  try {
    const res = await fetch(`${API}/api/v1/cli/status`)
    if (res.ok) cliStatus.value = await res.json()
  } catch { /* ignore */ }
  finally { cliLoading.value = false }
}

async function installCli(type: 'claude' | 'gemini' | 'codex') {
  cliInstalling.value = type
  cliError.value = ''
  cliSuccess.value = ''
  try {
    const res = await fetch(`${API}/api/v1/cli/${type}/install`, { method: 'POST' })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || '安裝失敗')
    cliSuccess.value = data.message
    await fetchCliStatus()
  } catch (e: any) {
    cliError.value = e.message
  } finally {
    cliInstalling.value = null
  }
}

async function fetchGcloudStatus() {
  gcloudStatusLoading.value = true
  try {
    const res = await fetch(`${API}/api/v1/gcloud/status`)
    if (res.ok) gcloudStatus.value = await res.json()
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
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: gcloudAuthSession.value.session_id }),
    })
  }
  gcloudAuthSession.value = null
  gcloudAuthCode.value = ''
  gcloudError.value = ''
}

async function copyUrl() {
  if (gcloudAuthSession.value?.auth_url) {
    await navigator.clipboard.writeText(gcloudAuthSession.value.auth_url)
    copied.value = true
    setTimeout(() => copied.value = false, 2000)
  }
}

async function saveSettings() {
  saving.value = true
  try {
    await store.updateSettings({ gemini_api_key: geminiApiKey.value })
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  // 並行載入
  fetchCliStatus()
  fetchGcloudStatus()

  await store.fetchSettings()
  geminiApiKey.value = store.settings.gemini_api_key || ''
  settingsLoading.value = false
})
</script>

<template>
  <div class="max-w-2xl space-y-6">
    <!-- AI 設定 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Sparkles class="w-4 h-4 text-purple-400" />
          <h2 class="text-sm font-semibold text-slate-200">AI 設定</h2>
          <Loader2 v-if="settingsLoading" class="w-4 h-4 text-slate-500 animate-spin ml-auto" />
        </div>
      </div>
      <div class="p-6 space-y-4">
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">Gemini API Key</label>
          <input
            v-model="geminiApiKey"
            type="password"
            placeholder="AIza..."
            class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none text-sm font-mono"
          />
          <p class="text-[11px] text-slate-500 mt-1">
            用於 AI 產生成員立繪。可在
            <a href="https://aistudio.google.com/apikey" target="_blank" class="text-purple-400 hover:underline">Google AI Studio</a> 取得
          </p>
        </div>
      </div>
    </div>

    <!-- CLI 工具 -->
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Terminal class="w-4 h-4 text-amber-400" />
          <h2 class="text-sm font-semibold text-slate-200">CLI 工具</h2>
          <Loader2 v-if="cliLoading" class="w-4 h-4 text-slate-500 animate-spin ml-auto" />
        </div>
      </div>
      <div class="p-6 space-y-4">
        <div v-if="cliLoading" class="text-sm text-slate-500">讀取中...</div>
        <template v-else>
          <!-- 訊息 -->
          <div v-if="cliSuccess" class="p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-sm text-emerald-400">
            {{ cliSuccess }}
          </div>
          <div v-if="cliError" class="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-sm text-red-400">
            {{ cliError }}
          </div>

          <!-- Claude CLI -->
          <div class="flex items-center justify-between p-4 bg-slate-900 rounded-lg">
            <div class="flex items-center gap-3">
              <div :class="['w-2.5 h-2.5 rounded-full', cliStatus?.claude?.installed ? 'bg-emerald-400' : 'bg-slate-500']"></div>
              <div>
                <div class="text-sm font-medium text-slate-200">Claude CLI</div>
                <div class="text-xs text-slate-400">
                  {{ cliStatus?.claude?.installed ? (cliStatus.claude.version || '已安裝') : '未安裝' }}
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
              <div :class="['w-2.5 h-2.5 rounded-full', cliStatus?.gemini?.installed ? 'bg-emerald-400' : 'bg-slate-500']"></div>
              <div>
                <div class="text-sm font-medium text-slate-200">Gemini CLI</div>
                <div class="text-xs text-slate-400">
                  {{ cliStatus?.gemini?.installed ? (cliStatus.gemini.version || '已安裝') : '未安裝' }}
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

          <!-- Codex CLI (OpenAI) -->
          <div class="flex items-center justify-between p-4 bg-slate-900 rounded-lg">
            <div class="flex items-center gap-3">
              <div :class="['w-2.5 h-2.5 rounded-full', cliStatus?.codex?.installed ? 'bg-emerald-400' : 'bg-slate-500']"></div>
              <div>
                <div class="text-sm font-medium text-slate-200">Codex CLI <span class="text-slate-500 text-xs">(OpenAI)</span></div>
                <div class="text-xs text-slate-400">
                  {{ cliStatus?.codex?.installed ? (cliStatus.codex.version || '已安裝') : '未安裝' }}
                </div>
              </div>
            </div>
            <button
              v-if="!cliStatus?.codex?.installed"
              @click="installCli('codex')"
              :disabled="cliInstalling !== null"
              class="flex items-center gap-2 px-3 py-1.5 bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-white rounded-lg text-xs font-medium transition-all"
            >
              <Loader2 v-if="cliInstalling === 'codex'" class="w-3 h-3 animate-spin" />
              <Download v-else class="w-3 h-3" />
              安裝
            </button>
            <span v-else class="text-xs text-emerald-400">✓ 已安裝</span>
          </div>

          <!-- Ollama -->
          <div class="flex items-center justify-between p-4 bg-slate-900 rounded-lg">
            <div class="flex items-center gap-3">
              <div :class="['w-2.5 h-2.5 rounded-full', cliStatus?.ollama?.installed ? 'bg-emerald-400' : 'bg-slate-500']"></div>
              <div>
                <div class="text-sm font-medium text-slate-200">Ollama <span class="text-slate-500 text-xs">(本地模型)</span></div>
                <div class="text-xs text-slate-400">
                  {{ cliStatus?.ollama?.installed ? (cliStatus.ollama.version || '已安裝') : '未安裝' }}
                </div>
              </div>
            </div>
            <a
              v-if="!cliStatus?.ollama?.installed"
              href="https://ollama.com/download"
              target="_blank"
              class="flex items-center gap-2 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg text-xs font-medium transition-all"
            >
              <Download class="w-3 h-3" />
              下載
            </a>
            <span v-else class="text-xs text-emerald-400">✓ 已安裝</span>
          </div>

          <p class="text-[11px] text-slate-500">CLI 工具用於執行 AI 任務。Claude/Gemini/Codex 可透過 npm 安裝，Ollama 需從官網下載。</p>
        </template>
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
        <div v-if="gcloudStatusLoading" class="text-sm text-slate-500">讀取中...</div>
        <template v-else>
          <!-- 狀態 -->
          <div class="flex items-center gap-3">
            <div :class="['w-2.5 h-2.5 rounded-full', gcloudStatus?.authenticated ? 'bg-emerald-400' : 'bg-slate-500']"></div>
            <div>
              <div class="text-sm text-slate-200">{{ gcloudStatus?.authenticated ? '已認證' : '未認證' }}</div>
              <div v-if="gcloudStatus?.account" class="text-xs text-slate-400">{{ gcloudStatus.account }}</div>
              <div v-else-if="!gcloudStatus?.installed" class="text-xs text-amber-400">未安裝 gcloud CLI</div>
            </div>
          </div>

          <!-- 訊息 -->
          <div v-if="gcloudSuccess" class="p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-sm text-emerald-400">
            {{ gcloudSuccess }}
          </div>
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

            <div>
              <label class="block text-xs font-medium text-slate-400 mb-1.5">授權網址</label>
              <div class="flex gap-2">
                <input :value="gcloudAuthSession.auth_url" readonly class="flex-1 bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 text-xs font-mono truncate" />
                <button @click="copyUrl" class="px-3 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg transition-colors">
                  <Check v-if="copied" class="w-4 h-4 text-emerald-400" />
                  <Copy v-else class="w-4 h-4 text-slate-300" />
                </button>
                <a :href="gcloudAuthSession.auth_url" target="_blank" class="px-3 py-2 bg-sky-500 hover:bg-sky-600 rounded-lg transition-colors">
                  <ExternalLink class="w-4 h-4 text-white" />
                </a>
              </div>
            </div>

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

            <div class="flex gap-2">
              <button
                @click="completeGcloudAuth"
                :disabled="gcloudLoading || !gcloudAuthCode.trim()"
                class="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-sky-500 hover:bg-sky-600 disabled:opacity-50 text-white rounded-lg font-bold text-sm transition-all"
              >
                <Loader2 v-if="gcloudLoading" class="w-4 h-4 animate-spin" />
                完成登入
              </button>
              <button @click="cancelGcloudAuth" class="px-4 py-2.5 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg font-bold text-sm transition-all">
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
            <p class="text-[11px] text-slate-500 mt-2">在此伺服器上登入 Google 帳號，用於 Gemini CLI 等服務。</p>
          </div>

          <div v-else class="text-xs text-slate-500">
            請先在伺服器上安裝 <a href="https://cloud.google.com/sdk/docs/install" target="_blank" class="text-sky-400 hover:underline">Google Cloud SDK</a>。
          </div>
        </template>
      </div>
    </div>

    <!-- 儲存按鈕 -->
    <div class="flex justify-end">
      <button
        @click="saveSettings"
        :disabled="saving || settingsLoading"
        class="flex items-center gap-2 px-6 py-2.5 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-lg font-bold text-sm transition-all shadow-lg shadow-emerald-500/20"
      >
        <Save class="w-4 h-4" />
        {{ saving ? '儲存中...' : '儲存設定' }}
      </button>
    </div>
  </div>
</template>
