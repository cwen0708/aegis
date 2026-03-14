<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { Server, Cpu, HardDrive, Activity, Clock, Radio, Terminal, Sparkles, Eye, Cog, PlayCircle, PauseCircle } from 'lucide-vue-next'
import { useAegisStore } from '../stores/aegis'

const store = useAegisStore()
const metrics = ref<any>(null)
const services = ref<any>(null)
let intervalId: number

const fetchMetrics = async () => {
  try {
    const res = await fetch('/api/v1/system/metrics')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    metrics.value = await res.json()
  } catch (e) {
    console.error('Failed to fetch metrics', e)
  }
}

const fetchServices = async () => {
  try {
    const res = await fetch('/api/v1/system/services')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    services.value = await res.json()
  } catch (e) {
    console.error('Failed to fetch services', e)
  }
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

    <!-- Hardware Metrics -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-6" v-if="metrics">
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
          <h3 class="text-4xl font-black text-slate-100">{{ metrics.cpu_percent }}</h3>
          <span class="text-lg font-medium text-slate-400">%</span>
        </div>
        <div class="mt-4 w-full bg-slate-900/50 rounded-full h-1.5 overflow-hidden">
          <div class="bg-blue-500 h-1.5 rounded-full transition-all duration-500" :style="{ width: `${metrics.cpu_percent}%` }"></div>
        </div>
      </div>

      <!-- RAM -->
      <div class="bg-gradient-to-br from-slate-800 to-slate-800/80 p-6 rounded-2xl border border-slate-700 shadow-xl relative overflow-hidden group">
        <div class="absolute inset-0 bg-gradient-to-br from-purple-500/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity"></div>
        <div class="flex justify-between items-start mb-4">
          <div class="bg-slate-900/50 p-3 rounded-xl border border-slate-700/50">
            <Server class="w-6 h-6 text-purple-400" />
          </div>
          <span class="text-xs font-medium text-slate-400 bg-slate-900/50 px-2 py-1 rounded-md">{{ metrics.memory_available_gb }} GB 可用</span>
        </div>
        <div class="flex items-baseline gap-2">
          <h3 class="text-4xl font-black text-slate-100">{{ metrics.memory_percent }}</h3>
          <span class="text-lg font-medium text-slate-400">%</span>
        </div>
        <div class="mt-4 w-full bg-slate-900/50 rounded-full h-1.5 overflow-hidden">
          <div class="bg-purple-500 h-1.5 rounded-full transition-all duration-500" :style="{ width: `${metrics.memory_percent}%` }"></div>
        </div>
      </div>

      <!-- Disk -->
      <div class="bg-gradient-to-br from-slate-800 to-slate-800/80 p-6 rounded-2xl border border-slate-700 shadow-xl relative overflow-hidden group">
        <div class="absolute inset-0 bg-gradient-to-br from-emerald-500/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity"></div>
        <div class="flex justify-between items-start mb-4">
          <div class="bg-slate-900/50 p-3 rounded-xl border border-slate-700/50">
            <HardDrive class="w-6 h-6 text-emerald-400" />
          </div>
          <span class="text-xs font-medium text-slate-400 bg-slate-900/50 px-2 py-1 rounded-md">G:\ Drive</span>
        </div>
        <div class="flex items-baseline gap-2">
          <h3 class="text-4xl font-black text-slate-100">{{ metrics.disk_percent }}</h3>
          <span class="text-lg font-medium text-slate-400">%</span>
        </div>
        <div class="mt-4 w-full bg-slate-900/50 rounded-full h-1.5 overflow-hidden">
          <div class="bg-emerald-500 h-1.5 rounded-full transition-all duration-500" :style="{ width: `${metrics.disk_percent}%` }"></div>
        </div>
      </div>
    </div>

    <!-- Services (中型卡片) -->
    <div v-if="services" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">

      <!-- 主服務 (FastAPI) -->
      <div class="bg-slate-800/60 rounded-xl border border-slate-700/50 p-4">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <Cog class="w-4 h-4 text-cyan-400" />
            <span class="text-sm font-semibold text-slate-200">主服務</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
            <span class="text-[10px] text-emerald-400">運行中</span>
          </div>
        </div>
        <div class="space-y-1.5 text-xs text-slate-400">
          <div class="flex justify-between">
            <span>PID</span>
            <span class="font-mono text-slate-300">{{ services.pid }}</span>
          </div>
          <div class="flex justify-between">
            <span>WebSocket</span>
            <span class="font-mono text-slate-300">{{ services.engines?.websocket?.clients ?? 0 }} 連線</span>
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
            <span class="w-2 h-2 rounded-full" :class="[statusDot(services.engines?.task_worker?.status), services.engines?.task_worker?.status === 'running' ? 'animate-pulse' : '']"></span>
            <span class="text-[10px]" :class="services.engines?.task_worker?.status === 'running' ? 'text-emerald-400' : services.engines?.task_worker?.status === 'paused' ? 'text-amber-400' : 'text-red-400'">
              {{ statusLabel(services.engines?.task_worker?.status) }}
            </span>
          </div>
        </div>
        <div class="space-y-1.5 text-xs text-slate-400">
          <div class="flex justify-between">
            <span>PID</span>
            <span class="font-mono" :class="services.engines?.task_worker?.pid ? 'text-slate-300' : 'text-red-400'">
              {{ services.engines?.task_worker?.pid ?? '---' }}
            </span>
          </div>
          <div class="flex justify-between">
            <span>輪詢間隔</span>
            <span class="font-mono text-slate-300">{{ services.engines?.task_worker?.interval_sec }}s</span>
          </div>
        </div>
        <div class="mt-3 pt-3 border-t border-slate-700/30">
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
            <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
            <span class="text-[10px] text-emerald-400">運行中</span>
          </div>
        </div>
        <div class="space-y-1.5 text-xs text-slate-400">
          <div class="flex justify-between">
            <span>檢查間隔</span>
            <span class="font-mono text-slate-300">{{ services.engines?.cron_poller?.interval_sec }}s</span>
          </div>
          <div v-if="services.engines?.cron_poller?.paused_projects?.length" class="flex justify-between">
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

      <!-- Claude CLI -->
      <div class="bg-slate-800/60 rounded-xl border border-slate-700/50 p-4">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <Terminal class="w-4 h-4" :class="services.cli_tools?.claude?.installed ? 'text-violet-400' : 'text-red-400'" />
            <span class="text-sm font-semibold text-slate-200">Claude CLI</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full" :class="services.cli_tools?.claude?.authenticated ? 'bg-emerald-400' : 'bg-red-400'"></span>
            <span class="text-[10px]" :class="services.cli_tools?.claude?.authenticated ? 'text-emerald-400' : 'text-red-400'">
              {{ services.cli_tools?.claude?.authenticated ? '已認證' : '未認證' }}
            </span>
          </div>
        </div>
        <div class="space-y-1.5 text-xs text-slate-400">
          <div class="flex justify-between">
            <span>版本</span>
            <span class="font-mono text-slate-300">{{ services.cli_tools?.claude?.version || '---' }}</span>
          </div>
          <div v-if="services.cli_tools?.claude?.subscription" class="flex justify-between">
            <span>方案</span>
            <span class="font-mono text-orange-400">{{ services.cli_tools.claude.subscription }}</span>
          </div>
        </div>
      </div>

      <!-- Gemini CLI -->
      <div class="bg-slate-800/60 rounded-xl border border-slate-700/50 p-4">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <Sparkles class="w-4 h-4" :class="services.cli_tools?.gemini?.installed ? 'text-blue-400' : 'text-red-400'" />
            <span class="text-sm font-semibold text-slate-200">Gemini CLI</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full" :class="services.cli_tools?.gemini?.authenticated ? 'bg-emerald-400' : 'bg-red-400'"></span>
            <span class="text-[10px]" :class="services.cli_tools?.gemini?.authenticated ? 'text-emerald-400' : 'text-red-400'">
              {{ services.cli_tools?.gemini?.authenticated ? '已認證' : '未認證' }}
            </span>
          </div>
        </div>
        <div class="space-y-1.5 text-xs text-slate-400">
          <div class="flex justify-between">
            <span>版本</span>
            <span class="font-mono text-slate-300">{{ services.cli_tools?.gemini?.version || '---' }}</span>
          </div>
          <div v-if="services.cli_tools?.gemini?.account" class="flex justify-between">
            <span>帳號</span>
            <span class="font-mono text-slate-300 truncate max-w-[120px]">{{ services.cli_tools.gemini.account }}</span>
          </div>
        </div>
      </div>

    </div>

  </div>
</template>
