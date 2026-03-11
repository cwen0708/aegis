<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Terminal, Loader2, Download } from 'lucide-vue-next'

import { config } from '../../config'

const API = config.apiUrl

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

onMounted(() => {
  fetchCliStatus()
})
</script>

<template>
  <div class="max-w-2xl space-y-6">
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
  </div>
</template>
