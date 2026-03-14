<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { Server, Cpu, HardDrive, Activity, Clock, Terminal, Sparkles, Eye, Cog, PlayCircle, PauseCircle, Download, Loader2, ExternalLink } from 'lucide-vue-next'
import { useAegisStore } from '../stores/aegis'
import { config } from '../config'
import { authHeaders } from '../utils/authFetch'

const store = useAegisStore()
const API = config.apiUrl
const metrics = ref<any>(null)
const services = ref<any>(null)
let intervalId: number

// CLI 安裝
const cliInstalling = ref<string | null>(null)
const cliMessage = ref('')
const cliMessageType = ref<'success' | 'error'>('success')

const fetchMetrics = async () => {
  try {
    const res = await fetch(`${API}/api/v1/system/metrics`)
    if (res.ok) metrics.value = await res.json()
  } catch {}
}

const fetchServices = async () => {
  try {
    const res = await fetch(`${API}/api/v1/system/services`)
    if (res.ok) services.value = await res.json()
  } catch {}
}

async function toggleRunner() {
  try {
    if (store.systemInfo.is_paused) {
      await store.resumeRunner()
    } else {
      await store.pauseRunner()
    }
    await fetchServices()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}

async function installCli(type: string) {
  cliInstalling.value = type
  cliMessage.value = ''
  try {
    const res = await fetch(`${API}/api/v1/cli/${type}/install`, { method: 'POST', headers: authHeaders() })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || '安裝失敗')
    cliMessage.value = data.message
    cliMessageType.value = 'success'
    await fetchServices()
  } catch (e: any) {
    cliMessage.value = e.message
    cliMessageType.value = 'error'
  } finally {
    cliInstalling.value = null
  }
}

function statusDot(status: string) {
  if (status === 'running') return 'bg-emerald-400'
  if (status === 'paused') return 'bg-amber-400'
  if (status === 'stopped') return 'bg-red-400'
  return 'bg-slate-500'
}

function statusLabel(status: string) {
  if (status === 'running') return '運行中'
  if (status === 'paused') return '已暫停'
  if (status === 'stopped') return '未啟動'
  if (status === 'unknown') return '未知'
  return status
}

onMounted(() => {
  fetchMetrics()
  fetchServices()
  intervalId = window.setInterval(() => {
    fetchMetrics()
    fetchServices()
  }, 5000)
})

onUnmounted(() => {
  clearInterval(intervalId)
})
</script>

<template>
  <div class="space-y-6">

    <!-- Hardware Metrics (骨架先出現) -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
      <!-- CPU -->
      <div class="bg-gradient-to-br from-slate-800 to-slate-800/80 p-6 rounded-2xl border border-slate-700 shadow-xl relative overflow-hidden group">
        <div class="absolute inset-0 bg-gradient-to-br from-blue-500/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity"></div>
        <div class="flex justify-between items-start mb-4">
          <div class="bg-slate-900/50 p-3 rounded-xl border border-slate-700/50">
            <Cpu class="w-6 h-6 text-blue-400" />
          </div>
          <span class="text-xs font-medium text-slate-400 bg-slate-900/50 px-2 py-1 rounded-md">負載</span>
        </div>
        <div class="flex items-baseline gap-2">
          <h3 class="text-4xl font-black text-slate-100">{{ metrics?.cpu_percent ?? '--' }}</h3>
          <span class="text-lg font-medium text-slate-400">%</span>
        </div>
        <div class="mt-4 w-full bg-slate-900/50 rounded-full h-1.5 overflow-hidden">
          <div class="bg-blue-500 h-1.5 rounded-full transition-all duration-500" :style="{ width: `${metrics?.cpu_percent ?? 0}%` }"></div>
        </div>
      </div>

      <!-- RAM -->
      <div class="bg-gradient-to-br from-slate-800 to-slate-800/80 p-6 rounded-2xl border border-slate-700 shadow-xl relative overflow-hidden group">
        <div class="absolute inset-0 bg-gradient-to-br from-purple-500/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity"></div>
        <div class="flex justify-between items-start mb-4">
          <div class="bg-slate-900/50 p-3 rounded-xl border border-slate-700/50">
            <Server class="w-6 h-6 text-purple-400" />
          </div>
          <span class="text-xs font-medium text-slate-400 bg-slate-900/50 px-2 py-1 rounded-md">{{ metrics?.memory_available_gb ?? '--' }} GB 可用</span>
        </div>
        <div class="flex items-baseline gap-2">
          <h3 class="text-4xl font-black text-slate-100">{{ metrics?.memory_percent ?? '--' }}</h3>
          <span class="text-lg font-medium text-slate-400">%</span>
        </div>
        <div class="mt-4 w-full bg-slate-900/50 rounded-full h-1.5 overflow-hidden">
          <div class="bg-purple-500 h-1.5 rounded-full transition-all duration-500" :style="{ width: `${metrics?.memory_percent ?? 0}%` }"></div>
        </div>
      </div>

      <!-- Disk -->
      <div class="bg-gradient-to-br from-slate-800 to-slate-800/80 p-6 rounded-2xl border border-slate-700 shadow-xl relative overflow-hidden group">
        <div class="absolute inset-0 bg-gradient-to-br from-emerald-500/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity"></div>
        <div class="flex justify-between items-start mb-4">
          <div class="bg-slate-900/50 p-3 rounded-xl border border-slate-700/50">
            <HardDrive class="w-6 h-6 text-emerald-400" />
          </div>
          <span class="text-xs font-medium text-slate-400 bg-slate-900/50 px-2 py-1 rounded-md">磁碟</span>
        </div>
        <div class="flex items-baseline gap-2">
          <h3 class="text-4xl font-black text-slate-100">{{ metrics?.disk_percent ?? '--' }}</h3>
          <span class="text-lg font-medium text-slate-400">%</span>
        </div>
        <div class="mt-4 w-full bg-slate-900/50 rounded-full h-1.5 overflow-hidden">
          <div class="bg-emerald-500 h-1.5 rounded-full transition-all duration-500" :style="{ width: `${metrics?.disk_percent ?? 0}%` }"></div>
        </div>
      </div>
    </div>

    <!-- CLI 安裝訊息 -->
    <div v-if="cliMessage" :class="[
      'p-3 rounded-lg text-sm border',
      cliMessageType === 'success' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' : 'bg-red-500/10 border-red-500/30 text-red-400'
    ]">
      {{ cliMessage }}
    </div>

    <!-- Services (中型卡片，骨架先出現) -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">

      <!-- 主服務 (FastAPI) -->
      <div class="bg-slate-800/60 rounded-xl border border-slate-700/50 p-4">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <Cog class="w-4 h-4 text-cyan-400" />
            <span class="text-sm font-semibold text-slate-200">主服務</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full" :class="services ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'"></span>
            <span class="text-[10px]" :class="services ? 'text-emerald-400' : 'text-slate-500'">
              {{ services ? '運行中' : '載入中...' }}
            </span>
          </div>
        </div>
        <div class="space-y-1.5 text-xs text-slate-400">
          <div class="flex justify-between">
            <span>PID</span>
            <span class="font-mono text-slate-300">{{ services?.pid ?? '--' }}</span>
          </div>
          <div class="flex justify-between">
            <span>WebSocket</span>
            <span class="font-mono text-slate-300">{{ services?.engines?.websocket?.clients ?? '--' }} 連線</span>
          </div>
        </div>
      </div>

      <!-- Task Worker -->
      <div class="bg-slate-800/60 rounded-xl border border-slate-700/50 p-4">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <Activity class="w-4 h-4 text-orange-400" />
            <span class="text-sm font-semibold text-slate-200">Task Worker</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full" :class="[services ? statusDot(services.engines?.task_worker?.status) : 'bg-slate-500', services?.engines?.task_worker?.status === 'running' ? 'animate-pulse' : '']"></span>
            <span class="text-[10px]" :class="services?.engines?.task_worker?.status === 'running' ? 'text-emerald-400' : services?.engines?.task_worker?.status === 'paused' ? 'text-amber-400' : 'text-slate-500'">
              {{ services ? statusLabel(services.engines?.task_worker?.status) : '載入中...' }}
            </span>
          </div>
        </div>
        <div class="space-y-1.5 text-xs text-slate-400">
          <div class="flex justify-between">
            <span>PID</span>
            <span class="font-mono" :class="services?.engines?.task_worker?.pid ? 'text-slate-300' : 'text-slate-500'">
              {{ services?.engines?.task_worker?.pid ?? '--' }}
            </span>
          </div>
          <div class="flex justify-between">
            <span>輪詢間隔</span>
            <span class="font-mono text-slate-300">{{ services?.engines?.task_worker?.interval_sec ?? '--' }}s</span>
          </div>
        </div>
        <div v-if="services" class="mt-3 pt-3 border-t border-slate-700/30">
          <button
            @click="toggleRunner"
            class="flex items-center gap-1.5 text-[11px] px-3 py-1.5 rounded-lg transition-colors w-full justify-center"
            :class="services.engines?.task_worker?.is_paused
              ? 'bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 border border-emerald-500/20'
              : 'bg-amber-500/15 text-amber-400 hover:bg-amber-500/25 border border-amber-500/20'"
          >
            <PlayCircle v-if="services.engines?.task_worker?.is_paused" class="w-3.5 h-3.5" />
            <PauseCircle v-else class="w-3.5 h-3.5" />
            {{ services.engines?.task_worker?.is_paused ? '啟動 Worker' : '暫停 Worker' }}
          </button>
        </div>
      </div>

      <!-- Cron Poller -->
      <div class="bg-slate-800/60 rounded-xl border border-slate-700/50 p-4">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <Clock class="w-4 h-4 text-emerald-400" />
            <span class="text-sm font-semibold text-slate-200">排程引擎</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full" :class="services ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'"></span>
            <span class="text-[10px]" :class="services ? 'text-emerald-400' : 'text-slate-500'">
              {{ services ? '運行中' : '載入中...' }}
            </span>
          </div>
        </div>
        <div class="space-y-1.5 text-xs text-slate-400">
          <div class="flex justify-between">
            <span>檢查間隔</span>
            <span class="font-mono text-slate-300">{{ services?.engines?.cron_poller?.interval_sec ?? '--' }}s</span>
          </div>
          <div v-if="services?.engines?.cron_poller?.paused_projects?.length" class="flex justify-between">
            <span>暫停專案</span>
            <span class="font-mono text-amber-400">{{ services.engines.cron_poller.paused_projects.length }} 個</span>
          </div>
        </div>
        <div class="mt-3 pt-3 border-t border-slate-700/30">
          <router-link
            to="/cron"
            class="flex items-center gap-1.5 text-[11px] px-3 py-1.5 rounded-lg bg-slate-700/50 text-slate-400 hover:bg-slate-600/50 hover:text-slate-200 transition-colors w-full justify-center border border-slate-700/30"
          >
            <Eye class="w-3.5 h-3.5" />
            查看排程
          </router-link>
        </div>
      </div>

      <!-- Claude CLI (含安裝) -->
      <div class="bg-slate-800/60 rounded-xl border border-slate-700/50 p-4">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <Terminal class="w-4 h-4" :class="services?.cli_tools?.claude?.installed ? 'text-violet-400' : 'text-slate-500'" />
            <span class="text-sm font-semibold text-slate-200">Claude CLI</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full" :class="services?.cli_tools?.claude?.authenticated ? 'bg-emerald-400' : services?.cli_tools?.claude?.installed ? 'bg-amber-400' : 'bg-slate-500'"></span>
            <span class="text-[10px]" :class="services?.cli_tools?.claude?.authenticated ? 'text-emerald-400' : services?.cli_tools?.claude?.installed ? 'text-amber-400' : 'text-slate-500'">
              {{ !services ? '載入中...' : services.cli_tools?.claude?.authenticated ? '已認證' : services.cli_tools?.claude?.installed ? '未認證' : '未安裝' }}
            </span>
          </div>
        </div>
        <div class="space-y-1.5 text-xs text-slate-400">
          <div class="flex justify-between">
            <span>版本</span>
            <span class="font-mono text-slate-300">{{ services?.cli_tools?.claude?.version || '--' }}</span>
          </div>
          <div v-if="services?.cli_tools?.claude?.subscription" class="flex justify-between">
            <span>方案</span>
            <span class="font-mono text-orange-400">{{ services.cli_tools.claude.subscription }}</span>
          </div>
        </div>
        <div v-if="services && !services.cli_tools?.claude?.installed" class="mt-3 pt-3 border-t border-slate-700/30">
          <button
            @click="installCli('claude')"
            :disabled="cliInstalling !== null"
            class="flex items-center gap-1.5 text-[11px] px-3 py-1.5 rounded-lg bg-violet-500/15 text-violet-400 hover:bg-violet-500/25 border border-violet-500/20 transition-colors w-full justify-center disabled:opacity-50"
          >
            <Loader2 v-if="cliInstalling === 'claude'" class="w-3.5 h-3.5 animate-spin" />
            <Download v-else class="w-3.5 h-3.5" />
            安裝 Claude CLI
          </button>
        </div>
      </div>

      <!-- Gemini CLI (含安裝) -->
      <div class="bg-slate-800/60 rounded-xl border border-slate-700/50 p-4">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <Sparkles class="w-4 h-4" :class="services?.cli_tools?.gemini?.installed ? 'text-blue-400' : 'text-slate-500'" />
            <span class="text-sm font-semibold text-slate-200">Gemini CLI</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full" :class="services?.cli_tools?.gemini?.authenticated ? 'bg-emerald-400' : services?.cli_tools?.gemini?.installed ? 'bg-amber-400' : 'bg-slate-500'"></span>
            <span class="text-[10px]" :class="services?.cli_tools?.gemini?.authenticated ? 'text-emerald-400' : services?.cli_tools?.gemini?.installed ? 'text-amber-400' : 'text-slate-500'">
              {{ !services ? '載入中...' : services.cli_tools?.gemini?.authenticated ? '已認證' : services.cli_tools?.gemini?.installed ? '未認證' : '未安裝' }}
            </span>
          </div>
        </div>
        <div class="space-y-1.5 text-xs text-slate-400">
          <div class="flex justify-between">
            <span>版本</span>
            <span class="font-mono text-slate-300">{{ services?.cli_tools?.gemini?.version || '--' }}</span>
          </div>
          <div v-if="services?.cli_tools?.gemini?.account" class="flex justify-between">
            <span>帳號</span>
            <span class="font-mono text-slate-300 truncate max-w-[120px]">{{ services.cli_tools.gemini.account }}</span>
          </div>
        </div>
        <div v-if="services && !services.cli_tools?.gemini?.installed" class="mt-3 pt-3 border-t border-slate-700/30">
          <button
            @click="installCli('gemini')"
            :disabled="cliInstalling !== null"
            class="flex items-center gap-1.5 text-[11px] px-3 py-1.5 rounded-lg bg-blue-500/15 text-blue-400 hover:bg-blue-500/25 border border-blue-500/20 transition-colors w-full justify-center disabled:opacity-50"
          >
            <Loader2 v-if="cliInstalling === 'gemini'" class="w-3.5 h-3.5 animate-spin" />
            <Download v-else class="w-3.5 h-3.5" />
            安裝 Gemini CLI
          </button>
        </div>
      </div>

      <!-- Ollama -->
      <div class="bg-slate-800/60 rounded-xl border border-slate-700/50 p-4">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <Terminal class="w-4 h-4" :class="services?.cli_tools?.ollama?.installed ? 'text-teal-400' : 'text-slate-500'" />
            <span class="text-sm font-semibold text-slate-200">Ollama</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full" :class="services?.cli_tools?.ollama?.installed ? 'bg-emerald-400' : 'bg-slate-500'"></span>
            <span class="text-[10px]" :class="services?.cli_tools?.ollama?.installed ? 'text-emerald-400' : 'text-slate-500'">
              {{ !services ? '載入中...' : services.cli_tools?.ollama?.installed ? '已安裝' : '未安裝' }}
            </span>
          </div>
        </div>
        <div class="space-y-1.5 text-xs text-slate-400">
          <div class="flex justify-between">
            <span>版本</span>
            <span class="font-mono text-slate-300">{{ services?.cli_tools?.ollama?.version || '--' }}</span>
          </div>
          <div class="flex justify-between">
            <span>類型</span>
            <span class="font-mono text-slate-300">本地模型</span>
          </div>
        </div>
        <div v-if="services && !services.cli_tools?.ollama?.installed" class="mt-3 pt-3 border-t border-slate-700/30">
          <a
            href="https://ollama.com/download"
            target="_blank"
            class="flex items-center gap-1.5 text-[11px] px-3 py-1.5 rounded-lg bg-teal-500/15 text-teal-400 hover:bg-teal-500/25 border border-teal-500/20 transition-colors w-full justify-center"
          >
            <ExternalLink class="w-3.5 h-3.5" />
            前往下載
          </a>
        </div>
      </div>

    </div>
  </div>
</template>
