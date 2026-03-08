<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { X, CheckCircle, XCircle, Clock, Loader2, ListTodo } from 'lucide-vue-next'

const props = defineProps<{
  memberId: number
  name: string
  provider: string
  role?: string
  portrait?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

// Task history
interface TaskLogItem {
  id: number
  card_title: string
  project_name: string
  status: string
  duration_ms: number
  created_at: string
}

const history = ref<TaskLogItem[]>([])
const loading = ref(true)
const showTasks = ref(false)

async function fetchHistory() {
  loading.value = true
  try {
    const res = await fetch(`/api/v1/members/${props.memberId}/history?limit=8`)
    if (res.ok) {
      history.value = await res.json()
    }
  } catch (e) {
    console.error('Failed to fetch history:', e)
  }
  loading.value = false
}

// ESC to close
function handleKeyDown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    emit('close')
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
  fetchHistory()
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
})

watch(() => props.memberId, fetchHistory)

// Provider color
function providerColor(provider: string): string {
  if (provider === 'claude') return 'text-orange-400'
  if (provider === 'gemini') return 'text-blue-400'
  return 'text-slate-400'
}

function providerLabel(provider: string): string {
  if (provider === 'claude') return 'Claude'
  if (provider === 'gemini') return 'Gemini'
  return provider
}
</script>

<template>
  <!-- Backdrop - AVG Style -->
  <div class="fixed inset-0 z-50 pointer-events-auto" @click.self="emit('close')">
    <!-- Dark overlay with frosted glass -->
    <div class="absolute inset-0 bg-black/40 backdrop-blur-sm" @click="emit('close')" />

    <!-- Character portrait - large, left side -->
    <div class="absolute left-0 sm:left-8 bottom-0 w-[280px] sm:w-[500px] h-[60vh] sm:h-[85vh]">
      <template v-if="portrait">
        <img
          :src="portrait.startsWith('http') ? portrait : `${portrait}`"
          class="w-full h-full object-contain object-bottom drop-shadow-2xl"
        />
      </template>
      <template v-else>
        <div class="absolute bottom-0 left-1/2 -translate-x-1/2 w-48 h-72 rounded-t-full"
          :class="provider === 'claude' ? 'bg-orange-500/20' : 'bg-blue-500/20'"
        />
        <div class="absolute bottom-24 left-1/2 -translate-x-1/2 text-7xl">
          {{ provider === 'claude' ? '🟠' : '🔵' }}
        </div>
      </template>
    </div>

    <!-- Quest log - right side panel (toggle) -->
    <Transition name="slide-fade">
      <div v-if="showTasks" class="absolute right-4 sm:right-[50px] top-20 w-64 max-h-[40vh] overflow-hidden">
        <div class="bg-slate-900/40 backdrop-blur-sm rounded-lg border-2 border-slate-400/40 shadow-xl">
          <div class="p-3 max-h-[40vh] overflow-y-auto">
            <div v-if="loading" class="flex items-center justify-center py-4">
              <Loader2 class="w-5 h-5 text-slate-400 animate-spin" />
            </div>

            <div v-else-if="history.length === 0" class="text-center py-4 text-slate-500 text-sm">
              尚無任務記錄
            </div>

            <div v-else class="space-y-1">
              <div
                v-for="task in history"
                :key="task.id"
                class="flex items-center gap-2 py-1"
              >
                <div class="shrink-0">
                  <CheckCircle v-if="task.status === 'success'" class="w-4 h-4 text-emerald-400" />
                  <XCircle v-else-if="task.status === 'error' || task.status === 'timeout'" class="w-4 h-4 text-red-400" />
                  <Clock v-else class="w-4 h-4 text-amber-400" />
                </div>
                <div class="flex-1 min-w-0">
                  <p class="text-xs text-white truncate">{{ task.card_title }}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Dialog box - bottom, full width with frame -->
    <div class="absolute bottom-4 left-2 right-2 sm:left-[50px] sm:right-[50px]">
      <div class="bg-slate-900/40 backdrop-blur-sm rounded-lg border-2 border-slate-400/40 shadow-2xl">
        <!-- Name tag - positioned above the box -->
        <div class="absolute -top-4 left-6">
          <div class="bg-slate-800 rounded px-4 py-1 border border-slate-500/50">
            <span class="text-white font-bold">{{ name }}</span>
            <span class="text-xs text-slate-400 ml-2">{{ role || '開發者' }}</span>
            <span class="mx-1 text-slate-600">|</span>
            <span :class="providerColor(provider)" class="text-xs">{{ providerLabel(provider) }}</span>
          </div>
        </div>

        <!-- Dialog content -->
        <div class="px-6 py-6 pt-8 min-h-[150px] flex flex-col">
          <div class="flex-1">
            <p class="text-white text-lg leading-relaxed font-bold" style="text-shadow: -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000;">
              {{ history.length > 0
                ? `已完成 ${history.filter(t => t.status === 'success').length} 個任務，隨時準備好接受新挑戰！`
                : '準備好開始工作了！'
              }}
            </p>
          </div>

        </div>

        <!-- Action buttons - overlapping bottom border -->
        <div class="absolute -bottom-3 right-6 flex items-center gap-2">
          <button
            @click="showTasks = !showTasks"
            class="flex items-center gap-1 px-3 py-1 bg-slate-700 text-slate-300 hover:text-white hover:bg-slate-600 rounded transition-colors text-xs"
            :class="showTasks ? 'bg-emerald-600 text-white' : ''"
          >
            <ListTodo :size="12" />
            <span class="hidden sm:inline">任務</span>
          </button>
          <button
            @click="emit('close')"
            class="flex items-center gap-1 px-3 py-1 bg-slate-700 text-slate-300 hover:text-white hover:bg-slate-600 rounded transition-colors text-xs"
          >
            <X :size="12" />
            <span>關閉</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.slide-fade-enter-active,
.slide-fade-leave-active {
  transition: all 0.2s ease;
}
.slide-fade-enter-from,
.slide-fade-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
</style>
