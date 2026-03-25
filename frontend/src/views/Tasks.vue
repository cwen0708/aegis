<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { Zap, History, CheckCircle, XCircle, Clock, Loader2 } from 'lucide-vue-next'
import { useAegisStore } from '../stores/aegis'
import { useProjectSelector } from '../composables/useProjectSelector'
import { useAuthStore } from '../stores/auth'
import { apiClient } from '../services/api/client'
import PageHeader from '../components/PageHeader.vue'
import RunningTaskCard from '../components/RunningTaskCard.vue'
import TerminalViewer from '../components/TerminalViewer.vue'

const store = useAegisStore()
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
  duration_ms: number
  cost_usd: number
  created_at: string
}

const taskLogs = ref<TaskLogItem[]>([])
const logsLoading = ref(false)
const expandedLogId = ref<number | null>(null)
const expandedLogOutput = ref<string>('')
const logDetailLoading = ref(false)

async function toggleLog(logId: number) {
  if (expandedLogId.value === logId) {
    expandedLogId.value = null
    return
  }
  expandedLogId.value = logId
  expandedLogOutput.value = ''
  if (!auth.isAuthenticated) return
  logDetailLoading.value = true
  try {
    const data = await apiClient.get<any>(`/api/v1/task-logs/${logId}`)
    expandedLogOutput.value = data.output || data.error_message || '（無輸出）'
  } catch {
    expandedLogOutput.value = '載入失敗'
  }
  logDetailLoading.value = false
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
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}m`
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
        <span>{{ store.runningTasks.length }} 個即時任務</span>
      </div>
    </PageHeader>

    <div class="flex-1 overflow-auto p-2 sm:p-6 space-y-6">
      <!-- 即時任務 -->
      <section>
        <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2">
          <Zap class="w-3.5 h-3.5 text-amber-400" />
          即時任務
        </h3>
        <div v-if="store.runningTasks.length === 0" class="bg-slate-800/30 rounded-xl border border-slate-700/50 p-8 text-center">
          <p class="text-sm text-slate-500">目前沒有運行中的任務</p>
        </div>
        <div v-else class="space-y-3">
          <div v-for="task in store.runningTasks" :key="task.task_id">
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

        <div v-else class="space-y-1.5">
          <div v-for="log in taskLogs" :key="log.id">
            <div
              @click="auth.isAuthenticated ? toggleLog(log.id) : null"
              :class="[
                'flex items-center gap-3 px-3 py-2 bg-slate-800/40 rounded-lg border transition',
                auth.isAuthenticated ? 'cursor-pointer hover:border-slate-500/50' : '',
                expandedLogId === log.id ? 'border-cyan-500/30' : 'border-slate-700/30 hover:border-slate-600/50',
              ]"
            >
              <!-- 狀態 icon -->
              <CheckCircle v-if="log.status === 'success'" class="w-4 h-4 text-emerald-400 shrink-0" />
              <XCircle v-else-if="log.status === 'error'" class="w-4 h-4 text-red-400 shrink-0" />
              <Clock v-else class="w-4 h-4 text-amber-400 shrink-0" />

              <!-- 標題 + 專案 -->
              <div class="flex-1 min-w-0">
                <div class="text-sm text-slate-200 truncate">{{ log.card_title }}</div>
                <div class="text-[11px] text-slate-500">{{ log.project_name }}</div>
              </div>

              <!-- Provider + Duration -->
              <div class="text-right shrink-0">
                <div class="text-xs text-slate-400">{{ formatDuration(log.duration_ms) }}</div>
                <div class="text-[10px] text-slate-600">{{ log.provider }}{{ log.model ? `/${log.model}` : '' }}</div>
              </div>

              <!-- 時間 -->
              <div class="text-[11px] text-slate-500 shrink-0 w-20 text-right">
                {{ formatTime(log.created_at) }}
              </div>
            </div>

            <!-- 展開：輸出內容 -->
            <div v-if="expandedLogId === log.id && auth.isAuthenticated"
              class="mt-1 bg-slate-900/60 rounded-lg border border-slate-700/30 p-3 max-h-64 overflow-auto">
              <div v-if="logDetailLoading" class="flex items-center gap-2 text-slate-500 text-sm">
                <Loader2 class="w-4 h-4 animate-spin" /> 載入中...
              </div>
              <pre v-else class="text-xs text-slate-300 font-mono whitespace-pre-wrap">{{ expandedLogOutput }}</pre>
            </div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
