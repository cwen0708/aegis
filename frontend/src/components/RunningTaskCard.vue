<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { Bot, Square } from 'lucide-vue-next'
import type { RunningTask } from '../stores/aegis'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()

const props = defineProps<{
  task: RunningTask
}>()

const emit = defineEmits<{
  abort: [taskId: number]
  click: [taskId: number]
}>()

// 即時經過時間計數器
const elapsed = ref('00:00')
let timer: ReturnType<typeof setInterval>

function updateElapsed() {
  const diff = Math.floor(Date.now() / 1000 - props.task.started_at)
  const m = Math.floor(diff / 60).toString().padStart(2, '0')
  const s = (diff % 60).toString().padStart(2, '0')
  elapsed.value = `${m}:${s}`
}

onMounted(() => {
  updateElapsed()
  timer = setInterval(updateElapsed, 1000)
})

onUnmounted(() => clearInterval(timer))

const providerColor = computed(() => {
  return props.task.provider === 'claude' ? 'purple' : 'blue'
})
</script>

<template>
  <div
    @click="emit('click', task.task_id)"
    class="bg-slate-800 p-4 rounded-xl border border-emerald-500/30 shadow-[0_0_15px_rgba(16,185,129,0.08)] cursor-pointer hover:border-emerald-500/50 transition-all group"
  >
    <div class="flex items-start justify-between mb-3">
      <div class="flex items-center gap-2">
        <div class="w-8 h-8 rounded-lg flex items-center justify-center relative"
          :class="providerColor === 'purple' ? 'bg-purple-500/20 border border-purple-500/30' : 'bg-blue-500/20 border border-blue-500/30'">
          <Bot class="w-4 h-4" :class="providerColor === 'purple' ? 'text-purple-400' : 'text-blue-400'" />
          <span class="absolute -top-0.5 -right-0.5 flex h-2 w-2">
            <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
          </span>
        </div>
        <div>
          <span class="text-xs font-mono text-slate-500">C-{{ task.task_id }}</span>
          <span class="text-xs text-slate-600 mx-1">·</span>
          <span class="text-xs text-slate-500">{{ task.provider }}</span>
          <template v-if="task.pid">
            <span class="text-xs text-slate-600 mx-1">·</span>
            <span class="text-xs text-slate-600 font-mono">PID {{ task.pid }}</span>
          </template>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-xs font-mono text-emerald-400">{{ elapsed }}</span>
        <button
          v-if="auth.isAuthenticated"
          @click.stop="emit('abort', task.task_id)"
          class="p-2 -m-1 text-slate-500 hover:text-red-400 hover:bg-red-400/10 rounded transition-colors touch-visible touch-target"
          title="中止任務"
        >
          <Square class="w-4 h-4" />
        </button>
      </div>
    </div>
    <h4 class="text-sm font-medium text-slate-100 truncate">{{ task.card_title || `Task #${task.task_id}` }}</h4>
    <p class="text-xs text-slate-500 mt-1 truncate">{{ task.project }}</p>
  </div>
</template>
