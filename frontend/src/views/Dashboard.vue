<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { Server, Cpu, HardDrive, Activity, Play, Pause, Clock, Radio, Terminal, Sparkles, Eye } from 'lucide-vue-next'
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

function serviceStatusColor(status: string, isPaused?: boolean) {
  if (isPaused) return 'text-amber-400'
  if (status === 'running') return 'text-emerald-400'
  if (status === 'paused') return 'text-amber-400'
  return 'text-red-400'
}

onMounted(() => {
  fetchMetrics()
  fetchServices()
  intervalId = window.setInterval(fetchMetrics, 5000)
})

onUnmounted(() => {
  clearInterval(intervalId)
})
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header h-16 -->
    <div class="sticky top-0 z-10 h-16 shrink-0 bg-slate-900/50 backdrop-blur-md border-b border-slate-800 px-8 flex items-center justify-between">
      <h1 class="text-lg font-bold text-slate-100">系統監控</h1>
      <div class="flex items-center gap-3">
        <button
          @click="toggleRunner"
          class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors"
          :class="store.systemInfo.is_paused
            ? 'bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20'
            : 'bg-amber-500/10 text-amber-400 hover:bg-amber-500/20'"
        >
          <Play v-if="store.systemInfo.is_paused" class="w-3.5 h-3.5" />
          <Pause v-else class="w-3.5 h-3.5" />
          {{ store.systemInfo.is_paused ? '恢復' : '暫停' }}
        </button>
        <div class="flex items-center gap-2 bg-emerald-500/10 border border-emerald-500/20 px-3 py-1.5 rounded-full">
          <span class="relative flex h-2.5 w-2.5">
            <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span class="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
          </span>
          <span class="text-xs font-semibold text-emerald-400 tracking-wider">引擎運行中</span>
        </div>
      </div>
    </div>

    <div class="flex-1 overflow-auto p-8 space-y-6">

    <!-- Hardware Metrics Grid -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-6" v-if="metrics">

      <!-- CPU Card -->
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

      <!-- RAM Card -->
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

      <!-- Disk Card -->
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

    <!-- 服務狀態 -->
    <div v-if="services?.engines" class="bg-slate-800/50 p-5 rounded-2xl border border-slate-700">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-sm font-semibold text-slate-300 tracking-wider">服務狀態</h3>
        <span v-if="services.pid" class="text-[10px] text-slate-500 font-mono">PID {{ services.pid }}</span>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-0">
        <!-- 左列：內部引擎 -->
        <div class="space-y-0.5">
          <!-- Task Poller -->
          <div class="flex items-center justify-between py-2 border-b border-slate-700/30">
            <div class="flex items-center gap-2">
              <Activity class="w-3.5 h-3.5" :class="serviceStatusColor(services.engines.task_poller?.status, services.engines.task_poller?.is_paused)" />
              <span class="text-xs text-slate-300 font-medium">任務輪詢</span>
              <span class="text-[10px] text-slate-500 font-mono">{{ services.engines.task_poller?.interval_sec }}s</span>
            </div>
            <button
              @click="toggleRunner"
              class="text-[10px] px-2 py-0.5 rounded bg-slate-700/80 hover:bg-slate-600 text-slate-400 hover:text-slate-200 transition-colors"
            >
              {{ services.engines.task_poller?.is_paused ? '啟動' : '暫停' }}
            </button>
          </div>

          <!-- Cron Poller -->
          <div class="flex items-center justify-between py-2 border-b border-slate-700/30">
            <div class="flex items-center gap-2">
              <Clock class="w-3.5 h-3.5 text-emerald-400" />
              <span class="text-xs text-slate-300 font-medium">排程</span>
              <span class="text-[10px] text-slate-500 font-mono">{{ services.engines.cron_poller?.interval_sec }}s</span>
            </div>
            <div class="flex items-center gap-1.5">
              <span v-if="services.engines.cron_poller?.paused_projects?.length" class="text-[10px] text-amber-400 font-mono">
                {{ services.engines.cron_poller.paused_projects.length }} 專案暫停中
              </span>
              <router-link
                to="/cron"
                class="text-[10px] px-2 py-0.5 rounded bg-slate-700/80 hover:bg-slate-600 text-slate-400 hover:text-slate-200 transition-colors flex items-center gap-1"
              >
                <Eye class="w-3 h-3" />
                查看
              </router-link>
            </div>
          </div>

          <!-- WebSocket -->
          <div class="flex items-center justify-between py-2">
            <div class="flex items-center gap-2">
              <Radio class="w-3.5 h-3.5" :class="serviceStatusColor(services.engines.websocket?.status)" />
              <span class="text-xs text-slate-300 font-medium">WebSocket</span>
            </div>
            <span class="text-[10px] text-slate-500 font-mono">{{ services.engines.websocket?.clients ?? 0 }} 連線</span>
          </div>
        </div>

        <!-- 右列：AI 工具 -->
        <div v-if="services.cli_tools" class="space-y-0.5">
          <!-- Claude CLI -->
          <div class="flex items-center justify-between py-2 border-b border-slate-700/30">
            <div class="flex items-center gap-2">
              <Terminal class="w-3.5 h-3.5" :class="services.cli_tools.claude?.installed ? 'text-emerald-400' : 'text-red-400'" />
              <span class="text-xs text-slate-300 font-medium">Claude CLI</span>
              <span v-if="services.cli_tools.claude?.version" class="text-[10px] text-slate-500 font-mono">{{ services.cli_tools.claude.version }}</span>
            </div>
            <div class="flex items-center gap-1.5">
              <span
                v-if="services.cli_tools.claude?.subscription"
                class="text-[10px] px-1.5 py-0.5 rounded bg-orange-500/15 text-orange-400 border border-orange-500/20"
              >{{ services.cli_tools.claude.subscription }}</span>
              <span class="text-[10px] font-bold" :class="services.cli_tools.claude?.authenticated ? 'text-emerald-400' : 'text-red-400'">
                {{ services.cli_tools.claude?.authenticated ? '✓' : '✗' }}
              </span>
            </div>
          </div>

          <!-- Gemini CLI -->
          <div class="flex items-center justify-between py-2 border-b border-slate-700/30">
            <div class="flex items-center gap-2">
              <Sparkles class="w-3.5 h-3.5" :class="services.cli_tools.gemini?.installed ? 'text-emerald-400' : 'text-red-400'" />
              <span class="text-xs text-slate-300 font-medium">Gemini CLI</span>
              <span v-if="services.cli_tools.gemini?.version" class="text-[10px] text-slate-500 font-mono">{{ services.cli_tools.gemini.version }}</span>
            </div>
            <div class="flex items-center gap-1.5">
              <span v-if="services.cli_tools.gemini?.account" class="text-[10px] text-slate-500 font-mono truncate max-w-[140px]">{{ services.cli_tools.gemini.account }}</span>
              <span class="text-[10px] font-bold" :class="services.cli_tools.gemini?.authenticated ? 'text-emerald-400' : 'text-red-400'">
                {{ services.cli_tools.gemini?.authenticated ? '✓' : '✗' }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    </div>
  </div>
</template>
