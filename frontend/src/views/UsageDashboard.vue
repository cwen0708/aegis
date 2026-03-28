<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Coins, Zap, Hash, BarChart3 } from 'lucide-vue-next'
import { config } from '../config'

const API = config.apiUrl

const loading = ref(true)
const groupBy = ref<'date' | 'member' | 'provider'>('date')
const days = ref(30)
const data = ref<{ group_by: string; days: number; items: any[] }>({ group_by: 'date', days: 30, items: [] })

const daysOptions = [7, 30, 90]
const groupOptions: { value: 'date' | 'member' | 'provider'; label: string }[] = [
  { value: 'date', label: '依日期' },
  { value: 'member', label: '依成員' },
  { value: 'provider', label: '依供應商' },
]

async function fetchData() {
  loading.value = true
  try {
    const res = await fetch(`${API}/api/v1/usage-dashboard?group_by=${groupBy.value}&days=${days.value}`)
    if (res.ok) data.value = await res.json()
  } catch { /* ignore */ }
  loading.value = false
}

onMounted(fetchData)

function switchGroup(g: 'date' | 'member' | 'provider') {
  groupBy.value = g
  fetchData()
}

function switchDays(d: number) {
  days.value = d
  fetchData()
}

// 摘要統計
const summary = computed(() => {
  const items = data.value.items
  let totalInput = 0, totalOutput = 0, totalCost = 0, totalTasks = 0
  for (const it of items) {
    totalInput += it.input_tokens ?? 0
    totalOutput += it.output_tokens ?? 0
    totalCost += it.cost_usd ?? 0
    totalTasks += it.tasks ?? 0
  }
  return { totalInput, totalOutput, totalCost, totalTasks }
})

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return n.toLocaleString()
}

function fmtCost(n: number): string {
  return '$' + n.toFixed(4)
}

// 表格欄位依 group_by 不同
const labelColumn = computed(() => {
  if (groupBy.value === 'date') return { key: 'date', label: '日期' }
  if (groupBy.value === 'member') return { key: 'member_name', label: '成員' }
  return { key: 'provider', label: '供應商' }
})
</script>

<template>
  <div class="max-w-5xl space-y-6">

    <!-- 摘要卡片 -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
      <div class="bg-gradient-to-br from-slate-800 to-slate-800/80 p-4 rounded-2xl border border-slate-700 shadow-xl">
        <div class="flex items-center gap-2 mb-2">
          <Hash class="w-4 h-4 text-blue-400" />
          <span class="text-xs text-slate-400">任務總數</span>
        </div>
        <div class="text-2xl font-black text-slate-100">{{ fmtNum(summary.totalTasks) }}</div>
      </div>
      <div class="bg-gradient-to-br from-slate-800 to-slate-800/80 p-4 rounded-2xl border border-slate-700 shadow-xl">
        <div class="flex items-center gap-2 mb-2">
          <Zap class="w-4 h-4 text-emerald-400" />
          <span class="text-xs text-slate-400">輸入 Tokens</span>
        </div>
        <div class="text-2xl font-black text-slate-100">{{ fmtNum(summary.totalInput) }}</div>
      </div>
      <div class="bg-gradient-to-br from-slate-800 to-slate-800/80 p-4 rounded-2xl border border-slate-700 shadow-xl">
        <div class="flex items-center gap-2 mb-2">
          <BarChart3 class="w-4 h-4 text-purple-400" />
          <span class="text-xs text-slate-400">輸出 Tokens</span>
        </div>
        <div class="text-2xl font-black text-slate-100">{{ fmtNum(summary.totalOutput) }}</div>
      </div>
      <div class="bg-gradient-to-br from-slate-800 to-slate-800/80 p-4 rounded-2xl border border-slate-700 shadow-xl">
        <div class="flex items-center gap-2 mb-2">
          <Coins class="w-4 h-4 text-amber-400" />
          <span class="text-xs text-slate-400">總費用</span>
        </div>
        <div class="text-2xl font-black text-slate-100">{{ fmtCost(summary.totalCost) }}</div>
      </div>
    </div>

    <!-- 篩選列 -->
    <div class="flex flex-wrap items-center gap-3">
      <!-- group_by 切換 -->
      <div class="flex bg-slate-800/60 rounded-lg border border-slate-700/50 p-0.5">
        <button
          v-for="opt in groupOptions"
          :key="opt.value"
          @click="switchGroup(opt.value)"
          class="px-3 py-1.5 text-xs font-medium rounded-md transition-colors"
          :class="groupBy === opt.value
            ? 'bg-emerald-500/20 text-emerald-400'
            : 'text-slate-400 hover:text-slate-200'"
        >
          {{ opt.label }}
        </button>
      </div>
      <!-- days 切換 -->
      <div class="flex bg-slate-800/60 rounded-lg border border-slate-700/50 p-0.5">
        <button
          v-for="d in daysOptions"
          :key="d"
          @click="switchDays(d)"
          class="px-3 py-1.5 text-xs font-medium rounded-md transition-colors"
          :class="days === d
            ? 'bg-emerald-500/20 text-emerald-400'
            : 'text-slate-400 hover:text-slate-200'"
        >
          {{ d }} 天
        </button>
      </div>
    </div>

    <!-- 載入中 -->
    <div v-if="loading" class="text-sm text-slate-500 text-center py-20">載入中...</div>

    <!-- 空狀態 -->
    <div v-else-if="data.items.length === 0" class="text-center py-16">
      <BarChart3 class="w-10 h-10 text-slate-600 mx-auto mb-3" />
      <p class="text-sm text-slate-500">目前沒有用量資料</p>
      <p class="text-xs text-slate-600 mt-1">任務執行後會自動記錄 Token 用量</p>
    </div>

    <!-- 資料表格 -->
    <div v-else class="bg-slate-800/40 rounded-xl border border-slate-700/50 overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-slate-700/50">
              <th class="text-left px-4 py-3 text-xs font-semibold text-slate-400">{{ labelColumn.label }}</th>
              <th class="text-right px-4 py-3 text-xs font-semibold text-slate-400">任務數</th>
              <th class="text-right px-4 py-3 text-xs font-semibold text-slate-400">輸入 Tokens</th>
              <th class="text-right px-4 py-3 text-xs font-semibold text-slate-400">輸出 Tokens</th>
              <th class="text-right px-4 py-3 text-xs font-semibold text-slate-400 hidden md:table-cell">Cache 讀取</th>
              <th class="text-right px-4 py-3 text-xs font-semibold text-slate-400 hidden md:table-cell">Cache 建立</th>
              <th class="text-right px-4 py-3 text-xs font-semibold text-slate-400">費用 (USD)</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(item, idx) in data.items"
              :key="idx"
              class="border-b border-slate-700/30 hover:bg-slate-700/20 transition-colors"
            >
              <td class="px-4 py-2.5 text-slate-200 font-medium">{{ item[labelColumn.key] }}</td>
              <td class="px-4 py-2.5 text-right text-slate-300 font-mono">{{ item.tasks }}</td>
              <td class="px-4 py-2.5 text-right text-slate-300 font-mono">{{ fmtNum(item.input_tokens) }}</td>
              <td class="px-4 py-2.5 text-right text-slate-300 font-mono">{{ fmtNum(item.output_tokens) }}</td>
              <td class="px-4 py-2.5 text-right text-slate-400 font-mono hidden md:table-cell">{{ fmtNum(item.cache_read_tokens) }}</td>
              <td class="px-4 py-2.5 text-right text-slate-400 font-mono hidden md:table-cell">{{ fmtNum(item.cache_creation_tokens) }}</td>
              <td class="px-4 py-2.5 text-right text-amber-400 font-mono">{{ fmtCost(item.cost_usd) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

  </div>
</template>
