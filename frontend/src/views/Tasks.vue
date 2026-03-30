<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { Zap, History, CheckCircle, XCircle, Clock, Loader2, ChevronDown, ChevronRight } from 'lucide-vue-next'
import ParsedOutput from '../components/ParsedOutput.vue'
import { useAegisStore } from '../stores/aegis'
import { useTaskStore } from '../stores/task'
import { useProjectSelector } from '../composables/useProjectSelector'
import { useAuthStore } from '../stores/auth'
import { apiClient } from '../services/api/client'
import PageHeader from '../components/PageHeader.vue'
import RunningTaskCard from '../components/RunningTaskCard.vue'
import TerminalViewer from '../components/TerminalViewer.vue'

const store = useAegisStore()
const taskStore = useTaskStore()
const auth = useAuthStore()
const { selectedProjectId } = useProjectSelector()

const expandedTaskId = ref<number | null>(null)

function toggleTaskLog(taskId: number) {
  expandedTaskId.value = expandedTaskId.value === taskId ? null : taskId
}

async function handleAbort(taskId: number) {
  try {
    await store.abortCard(taskId)
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}

// 任務記錄
interface TaskLogItem {
  id: number
  card_id: number
  card_title: string
  project_name: string
  provider: string
  model: string
  member_id: number | null
  status: string
  output: string
  duration_ms: number
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cache_creation_tokens: number
  cost_usd: number
  created_at: string
}

const taskLogs = ref<TaskLogItem[]>([])
const logsLoading = ref(false)
const expandedLogId = ref<number | null>(null)

function toggleLog(logId: number) {
  expandedLogId.value = expandedLogId.value === logId ? null : logId
}

async function fetchTaskLogs() {
  logsLoading.value = true
  try {
    // 非 admin 只查當前專案
    const projectFilter = auth.isAdmin ? '' : `&project_id=${selectedProjectId.value || ''}`
    const data = await apiClient.get<any>(`/api/v1/task-logs/?limit=20${projectFilter}`)
    taskLogs.value = data.items || data
  } catch {}
  logsLoading.value = false
}

function formatDuration(ms: number): string {
  if (!ms) return '-'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}m`
}

function formatCost(usd: number): string {
  if (!usd) return ''
  return `$${usd.toFixed(4)}`
}

function formatTime(dateStr: string): string {
  const d = new Date(dateStr.endsWith('Z') ? dateStr : dateStr + 'Z')
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分鐘前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小時前`
  return d.toLocaleDateString('zh-TW', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

onMounted(() => {
  fetchTaskLogs()
})

// 切換專案時重新載入 logs
watch(selectedProjectId, () => {
  if (!auth.isAdmin) fetchTaskLogs()
})

// 任務完成/失敗時自動刷新列表
function _onTaskEvent() { fetchTaskLogs() }
onMounted(() => window.addEventListener('aegis:task-event', _onTaskEvent))
onUnmounted(() => window.removeEventListener('aegis:task-event', _onTaskEvent))
</script>

<template>
  <div class="h-full flex flex-col">
    <PageHeader :icon="Zap">
      <div class="flex items-center gap-2 text-xs text-slate-500">
        <Zap class="w-4 h-4" />
        <span>{{ taskStore.runningTasks.length }} 個即時任務</span>
      </div>
    </PageHeader>

    <div class="flex-1 overflow-auto p-2 sm:p-6 space-y-6">
      <!-- 即時任務 -->
      <section>
        <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2">
          <Zap class="w-3.5 h-3.5 text-amber-400" />
          即時任務
        </h3>
        <div v-if="taskStore.runningTasks.length === 0" class="bg-slate-800/30 rounded-xl border border-slate-700/50 p-8 text-center">
          <p class="text-sm text-slate-500">目前沒有運行中的任務</p>
        </div>
        <div v-else class="space-y-3">
          <div v-for="task in taskStore.runningTasks" :key="task.task_id">
            <RunningTaskCard
              :task="task"
              @abort="handleAbort"
              @click="toggleTaskLog"
            />
            <div v-if="expandedTaskId === task.task_id" class="mt-2 h-64 bg-slate-900 rounded-xl border border-slate-700 p-3">
              <TerminalViewer v-if="auth.isAuthenticated" :card-id="task.task_id" />
              <div v-else class="flex items-center justify-center h-full text-sm text-slate-500">
                請先登入以查看任務詳情
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 運行記錄 -->
      <section>
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-2">
            <History class="w-3.5 h-3.5 text-slate-400" />
            最近運行記錄
          </h3>
          <button @click="fetchTaskLogs" class="text-xs text-slate-500 hover:text-slate-300 transition">
            重新整理
          </button>
        </div>

        <div v-if="logsLoading" class="flex justify-center py-8">
          <Loader2 class="w-6 h-6 animate-spin text-slate-500" />
        </div>

        <div v-else-if="taskLogs.length === 0" class="bg-slate-800/30 rounded-xl border border-slate-700/50 p-8 text-center">
          <p class="text-sm text-slate-500">尚無運行記錄</p>
        </div>

        <div v-else class="space-y-2">
          <div v-for="log in taskLogs" :key="log.id"
            class="bg-slate-800/50 rounded-xl border border-slate-700/50 overflow-hidden transition-colors hover:border-slate-600/50">
            <!-- Log 標題列 -->
            <div class="flex items-center gap-3 px-4 py-3"
              :class="auth.isAuthenticated ? 'cursor-pointer' : ''"
              @click="auth.isAuthenticated ? toggleLog(log.id) : null">
              <CheckCircle v-if="log.status === 'success'" class="w-4 h-4 text-emerald-400 shrink-0" />
              <XCircle v-else-if="log.status === 'error'" class="w-4 h-4 text-red-400 shrink-0" />
              <Clock v-else class="w-4 h-4 text-amber-400 shrink-0" />

              <div class="flex-1 min-w-0">
                <div class="text-sm text-slate-200 truncate">{{ log.card_title }}</div>
                <div class="text-[11px] text-slate-500">{{ log.project_name }}</div>
              </div>

              <div class="flex items-center gap-3 text-[10px] text-slate-500">
                <span v-if="log.provider" class="px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-400">
                  {{ log.provider }}{{ log.model ? ` / ${log.model}` : '' }}
                </span>
                <span v-if="log.duration_ms">{{ formatDuration(log.duration_ms) }}</span>
                <span v-if="log.cost_usd">{{ formatCost(log.cost_usd) }}</span>
                <span v-if="log.input_tokens || log.output_tokens" class="font-mono">
                  {{ log.input_tokens + log.output_tokens }} tok
                </span>
              </div>

              <div class="text-[11px] text-slate-500 shrink-0 w-20 text-right">
                {{ formatTime(log.created_at) }}
              </div>

              <ChevronDown v-if="expandedLogId === log.id && auth.isAuthenticated" class="w-4 h-4 text-slate-500 shrink-0" />
              <ChevronRight v-else-if="auth.isAuthenticated" class="w-4 h-4 text-slate-500 shrink-0" />
            </div>

            <!-- 展開內容 -->
            <div v-if="expandedLogId === log.id && auth.isAuthenticated"
              class="border-t border-slate-700/50 px-4 py-3 space-y-3">
              <!-- Token 明細 -->
              <div v-if="log.input_tokens || log.output_tokens" class="flex gap-4 text-[10px] text-slate-500">
                <span>Input: {{ log.input_tokens?.toLocaleString() }}</span>
                <span>Output: {{ log.output_tokens?.toLocaleString() }}</span>
                <span v-if="log.cache_read_tokens">Cache Read: {{ log.cache_read_tokens?.toLocaleString() }}</span>
                <span v-if="log.cache_creation_tokens">Cache Create: {{ log.cache_creation_tokens?.toLocaleString() }}</span>
              </div>

              <!-- AI 輸出 -->
              <div v-if="log.output">
                <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Output</div>
                <div class="p-3 bg-slate-900/50 rounded-lg border border-slate-700/50 overflow-auto max-h-96">
                  <ParsedOutput :output="log.output" />
                </div>
              </div>

              <div v-else class="text-xs text-slate-500">（無輸出）</div>
            </div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
