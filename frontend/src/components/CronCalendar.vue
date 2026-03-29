<script setup lang="ts">
import { ref, computed } from 'vue'
import { ChevronLeft, ChevronRight } from 'lucide-vue-next'

const props = defineProps<{
  logs: any[]
}>()

const emit = defineEmits<{
  (e: 'select-date', date: string | null): void
}>()

const today = new Date()
const viewYear = ref(today.getFullYear())
const viewMonth = ref(today.getMonth()) // 0-indexed

const selectedDate = ref<string | null>(null)

// 將 log 的 created_at 轉成 YYYY-MM-DD（UTC）
function toDateKey(iso: string): string {
  const d = new Date(iso.includes('Z') || iso.includes('+') ? iso : iso.replace(' ', 'T') + 'Z')
  return d.toISOString().slice(0, 10)
}

// 按日期彙整：{ '2026-03-01': { success: 2, error: 1, total: 3 } }
const dateMap = computed(() => {
  const map: Record<string, { success: number; error: number; total: number }> = {}
  for (const log of props.logs) {
    const key = toDateKey(log.created_at)
    if (!map[key]) map[key] = { success: 0, error: 0, total: 0 }
    map[key].total++
    if (log.status === 'success') map[key].success++
    else map[key].error++
  }
  return map
})

// 月份標題
const monthLabel = computed(() => {
  return new Date(viewYear.value, viewMonth.value, 1)
    .toLocaleDateString('zh-TW', { year: 'numeric', month: 'long' })
})

// 當月日曆格子（含前後補位）
const calendarDays = computed(() => {
  const year = viewYear.value
  const month = viewMonth.value
  const firstDay = new Date(year, month, 1).getDay() // 0=Sun
  const daysInMonth = new Date(year, month + 1, 0).getDate()

  const cells: Array<{ date: string | null; day: number | null }> = []

  // 補前置空格
  for (let i = 0; i < firstDay; i++) {
    cells.push({ date: null, day: null })
  }

  for (let d = 1; d <= daysInMonth; d++) {
    const mm = String(month + 1).padStart(2, '0')
    const dd = String(d).padStart(2, '0')
    cells.push({ date: `${year}-${mm}-${dd}`, day: d })
  }

  return cells
})

function prevMonth() {
  if (viewMonth.value === 0) {
    viewMonth.value = 11
    viewYear.value--
  } else {
    viewMonth.value--
  }
}

function nextMonth() {
  if (viewMonth.value === 11) {
    viewMonth.value = 0
    viewYear.value++
  } else {
    viewMonth.value++
  }
}

function selectDate(date: string | null) {
  if (!date) return
  if (selectedDate.value === date) {
    selectedDate.value = null
    emit('select-date', null)
  } else {
    selectedDate.value = date
    emit('select-date', date)
  }
}

// 每個日期格的樣式
function dayCellClass(date: string | null): string {
  if (!date) return ''
  const info = dateMap.value[date]
  const isSelected = selectedDate.value === date
  const isToday = date === today.toISOString().slice(0, 10)

  let bg = 'bg-slate-800/40 hover:bg-slate-700/60'
  let border = 'border-slate-700/40'
  let text = 'text-slate-400'

  if (info) {
    if (info.error > 0 && info.success === 0) {
      bg = 'bg-red-500/15 hover:bg-red-500/25'
      border = 'border-red-500/30'
      text = 'text-red-300'
    } else if (info.error > 0) {
      bg = 'bg-amber-500/15 hover:bg-amber-500/25'
      border = 'border-amber-500/30'
      text = 'text-amber-300'
    } else {
      bg = 'bg-emerald-500/15 hover:bg-emerald-500/25'
      border = 'border-emerald-500/30'
      text = 'text-emerald-300'
    }
  }

  if (isSelected) {
    bg = 'bg-blue-500/25 hover:bg-blue-500/35'
    border = 'border-blue-400/60'
    text = 'text-blue-200'
  }

  if (isToday) {
    border = isSelected ? 'border-blue-400/80' : 'border-sky-400/50'
  }

  return `${bg} ${border} ${text} cursor-pointer`
}

// 日期格的點數指示器
function dotColor(date: string): string {
  const info = dateMap.value[date]
  if (!info) return ''
  if (info.error > 0 && info.success === 0) return 'bg-red-400'
  if (info.error > 0) return 'bg-amber-400'
  return 'bg-emerald-400'
}

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']
</script>

<template>
  <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-4">
    <!-- 月份導航 -->
    <div class="flex items-center justify-between mb-4">
      <button
        @click="prevMonth"
        class="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 rounded-lg transition-colors"
      >
        <ChevronLeft class="w-4 h-4" />
      </button>
      <span class="text-sm font-semibold text-slate-200">{{ monthLabel }}</span>
      <button
        @click="nextMonth"
        class="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 rounded-lg transition-colors"
      >
        <ChevronRight class="w-4 h-4" />
      </button>
    </div>

    <!-- 星期標頭 -->
    <div class="grid grid-cols-7 mb-1">
      <div
        v-for="wd in WEEKDAYS"
        :key="wd"
        class="text-center text-[10px] font-medium text-slate-500 uppercase py-1"
      >
        {{ wd }}
      </div>
    </div>

    <!-- 日期格子 -->
    <div class="grid grid-cols-7 gap-1">
      <div
        v-for="(cell, idx) in calendarDays"
        :key="idx"
        class="aspect-square rounded-lg border text-center flex flex-col items-center justify-center relative transition-all"
        :class="cell.date ? dayCellClass(cell.date) : 'border-transparent'"
        @click="selectDate(cell.date)"
      >
        <template v-if="cell.day !== null">
          <span class="text-xs leading-none">{{ cell.day }}</span>
          <!-- 執行次數徽章 -->
          <span
            v-if="cell.date && dateMap[cell.date]"
            class="text-[9px] leading-none mt-0.5 opacity-80"
          >
            {{ dateMap[cell.date!]!.total }}
          </span>
          <!-- 狀態點 -->
          <span
            v-if="cell.date && dateMap[cell.date]"
            class="absolute bottom-1 left-1/2 -translate-x-1/2 w-1 h-1 rounded-full"
            :class="dotColor(cell.date!)"
          />
        </template>
      </div>
    </div>

    <!-- 圖例 -->
    <div class="flex items-center gap-4 mt-3 pt-3 border-t border-slate-700/50">
      <div class="flex items-center gap-1.5">
        <span class="w-2.5 h-2.5 rounded bg-emerald-500/40 border border-emerald-500/50 inline-block" />
        <span class="text-[10px] text-slate-500">成功</span>
      </div>
      <div class="flex items-center gap-1.5">
        <span class="w-2.5 h-2.5 rounded bg-amber-500/40 border border-amber-500/50 inline-block" />
        <span class="text-[10px] text-slate-500">混合</span>
      </div>
      <div class="flex items-center gap-1.5">
        <span class="w-2.5 h-2.5 rounded bg-red-500/40 border border-red-500/50 inline-block" />
        <span class="text-[10px] text-slate-500">失敗</span>
      </div>
      <div class="flex items-center gap-1.5">
        <span class="w-2.5 h-2.5 rounded bg-slate-700/60 border border-slate-700/50 inline-block" />
        <span class="text-[10px] text-slate-500">無執行</span>
      </div>
    </div>
  </div>
</template>
