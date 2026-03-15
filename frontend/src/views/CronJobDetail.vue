<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Clock, Play, Pause, Pencil, Check, AlertCircle, CheckCircle2, XCircle, Timer, ChevronDown, ChevronRight, Zap } from 'lucide-vue-next'
import { useAegisStore } from '../stores/aegis'
import { useAuthStore } from '../stores/auth'
import { authHeaders } from '../utils/authFetch'

const route = useRoute()
const router = useRouter()
const store = useAegisStore()
const auth = useAuthStore()

const jobId = computed(() => Number(route.params.id))
const job = ref<any>(null)
const logs = ref<any[]>([])
const logsTotal = ref(0)
const loading = ref(true)
const logsLoading = ref(false)
const expandedLogId = ref<number | null>(null)

// 編輯模式
const editing = ref(false)
const editForm = ref<any>(null)

// 目標列表選擇器
const projectStageLists = ref<any[]>([])
const fetchStageLists = async (projectId: number) => {
  try {
    const res = await fetch(`/api/v1/projects/${projectId}/board`)
    if (res.ok) projectStageLists.value = await res.json()
  } catch { projectStageLists.value = [] }
}

const targetListName = computed(() => {
  if (!job.value?.target_list_id) return '預設（Scheduled）'
  const sl = projectStageLists.value.find((s: any) => s.id === job.value.target_list_id)
  return sl ? sl.name : `#${job.value.target_list_id}`
})

const formatTime = (iso: string) => {
  if (!iso) return '-'
  const tz = store.settings.timezone || 'Asia/Taipei'
  return new Date(iso).toLocaleString('zh-TW', { timeZone: tz })
}

const formatDuration = (ms: number) => {
  if (!ms) return '-'
  if (ms < 1000) return `${ms}ms`
  const sec = Math.round(ms / 1000)
  if (sec < 60) return `${sec}s`
  return `${Math.floor(sec / 60)}m ${sec % 60}s`
}

const formatCost = (usd: number) => {
  if (!usd) return '-'
  return `$${usd.toFixed(4)}`
}

async function fetchJob() {
  try {
    const res = await fetch(`/api/v1/cron-jobs/${jobId.value}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    job.value = await res.json()
  } catch (e) {
    console.error('Failed to fetch cron job', e)
    store.addToast('載入排程失敗', 'error')
  }
}

async function fetchLogs() {
  logsLoading.value = true
  try {
    const res = await fetch(`/api/v1/cron-jobs/${jobId.value}/logs?limit=50`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    logs.value = data.items
    logsTotal.value = data.total
  } catch (e) {
    console.error('Failed to fetch cron logs', e)
  } finally {
    logsLoading.value = false
  }
}

async function triggerJob() {
  if (!job.value) return
  try {
    const res = await fetch(`/api/v1/cron-jobs/${job.value.id}/trigger`, {
      method: 'POST',
      headers: authHeaders(),
    })
    const data = await res.json()
    if (!res.ok) {
      store.addToast(data.detail || '觸發失敗', 'error')
      return
    }
    store.addToast(`已手動觸發「${job.value.name}」`, 'success')
  } catch (e) {
    store.addToast('觸發失敗', 'error')
  }
}

async function toggleEnabled() {
  if (!job.value) return
  const newStatus = !job.value.is_enabled
  try {
    const res = await fetch(`/api/v1/cron-jobs/${job.value.id}`, {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ is_enabled: newStatus })
    })
    if (!res.ok) throw new Error('操作失敗')
    job.value.is_enabled = newStatus
    store.addToast(newStatus ? '排程已啟用' : '排程已停用', 'info')
  } catch (e) {
    store.addToast('操作失敗', 'error')
  }
}

// 即時計算下次執行時間（從 cron 表達式）
const nextRunPreview = computed(() => {
  if (!editForm.value?.cron_expression) return ''
  try {
    return calcNextRuns(editForm.value.cron_expression, 3)
  } catch {
    return '無效的 Cron 表達式'
  }
})

function calcNextRuns(cronExpr: string, count: number): string {
  // 簡易解析 cron（分 時 日 月 週）→ 計算接下來 N 次的 UTC 時間並轉台北時間
  const parts = cronExpr.trim().split(/\s+/)
  if (parts.length !== 5) return '格式錯誤（需要 5 個欄位）'

  const [minStr, hourStr] = parts
  const min = minStr === '*' ? 0 : parseInt(minStr)
  const hour = hourStr === '*' ? -1 : parseInt(hourStr)
  if (isNaN(min) || (hour !== -1 && isNaN(hour))) return ''

  const now = new Date()
  const results: string[] = []
  const d = new Date(now)

  for (let i = 0; i < count * 48 && results.length < count; i++) {
    d.setTime(now.getTime() + i * 3600000)
    const utcH = d.getUTCHours()
    const utcM = d.getUTCMinutes()

    if (hour !== -1 && utcH !== hour) continue
    if (utcM !== min && minStr !== '*') continue

    const local = new Date(d)
    local.setUTCMinutes(min)
    if (hour !== -1) local.setUTCHours(hour)
    const str = local.toLocaleString('zh-TW', { timeZone: 'Asia/Taipei', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
    if (!results.includes(str)) results.push(str)
  }

  return results.length > 0 ? results.join('、') : '無法計算'
}

function startEdit() {
  editForm.value = {
    name: job.value.name,
    description: job.value.description || '',
    cron_expression: job.value.cron_expression,
    prompt_template: job.value.prompt_template,
    target_list_id: job.value.target_list_id || null,
  }
  editing.value = true
  if (job.value.project_id) fetchStageLists(job.value.project_id)
}

async function saveEdit() {
  try {
    const res = await fetch(`/api/v1/cron-jobs/${job.value.id}`, {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(editForm.value)
    })
    if (!res.ok) throw new Error('更新失敗')
    editing.value = false
    store.addToast('排程已更新', 'success')
    await fetchJob()
  } catch (e) {
    store.addToast('更新失敗', 'error')
  }
}

function toggleLog(logId: number) {
  expandedLogId.value = expandedLogId.value === logId ? null : logId
}

const statusIcon = (status: string) => {
  switch (status) {
    case 'success': return CheckCircle2
    case 'error': return XCircle
    default: return AlertCircle
  }
}

const statusColor = (status: string) => {
  switch (status) {
    case 'success': return 'text-emerald-400'
    case 'error': return 'text-red-400'
    default: return 'text-amber-400'
  }
}

onMounted(async () => {
  await Promise.all([fetchJob(), fetchLogs()])
  // 載入列表名稱（供檢視模式顯示目標列表）
  if (job.value?.project_id) {
    fetchStageLists(job.value.project_id)
  }
  loading.value = false
})

watch(jobId, async () => {
  loading.value = true
  await Promise.all([fetchJob(), fetchLogs()])
  loading.value = false
})
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="sticky top-0 z-10 h-14 sm:h-16 shrink-0 bg-slate-900/50 backdrop-blur-md border-b border-slate-800 px-2 sm:px-8 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <button @click="router.push('/cron')" class="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 rounded-lg transition-colors">
          <ArrowLeft class="w-5 h-5" />
        </button>
        <div v-if="job">
          <h1 class="text-sm sm:text-base font-bold text-slate-100">{{ job.name }}</h1>
          <div class="flex items-center gap-2 text-[10px] text-slate-500">
            <Clock class="w-3 h-3" />
            <span class="font-mono">{{ job.cron_expression }}</span>
            <span
              :class="[
                'px-1.5 py-0.5 rounded text-[10px] font-bold uppercase border',
                job.is_enabled ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-slate-700 text-slate-500 border-slate-600'
              ]"
            >{{ job.is_enabled ? '啟用' : '停用' }}</span>
          </div>
        </div>
      </div>
      <div v-if="job && auth.isAuthenticated" class="flex items-center gap-2">
        <button @click="triggerJob" class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-cyan-400 hover:bg-cyan-400/10 transition-all">
          <Zap class="w-3.5 h-3.5" />
          手動執行
        </button>
        <button @click="toggleEnabled" :class="[
          'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all',
          job.is_enabled ? 'text-amber-400 hover:bg-amber-400/10' : 'text-emerald-400 hover:bg-emerald-400/10'
        ]">
          <Pause v-if="job.is_enabled" class="w-3.5 h-3.5" />
          <Play v-else class="w-3.5 h-3.5" />
          {{ job.is_enabled ? '停用' : '啟用' }}
        </button>
        <button @click="startEdit" class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-all">
          <Pencil class="w-3.5 h-3.5" />
          編輯
        </button>
      </div>
    </div>

    <div v-if="loading" class="flex-1 flex items-center justify-center">
      <div class="text-slate-500 text-sm">載入中...</div>
    </div>

    <div v-else-if="!job" class="flex-1 flex items-center justify-center">
      <div class="text-center">
        <AlertCircle class="w-10 h-10 mx-auto mb-4 text-slate-600" />
        <p class="text-sm text-slate-500">排程不存在</p>
      </div>
    </div>

    <div v-else class="flex-1 overflow-auto p-2 sm:p-8 space-y-6">
      <!-- 排程資訊卡 -->
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-6">
        <!-- 編輯模式 -->
        <template v-if="editing">
          <div class="space-y-4">
            <div class="grid grid-cols-2 gap-4">
              <div>
                <label class="block text-xs font-medium text-slate-400 mb-1">排程名稱</label>
                <input v-model="editForm.name" type="text" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none">
              </div>
              <div>
                <label class="block text-xs font-medium text-slate-400 mb-1">Cron 表達式 <span class="text-slate-600">(UTC)</span></label>
                <input v-model="editForm.cron_expression" type="text" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-blue-400 font-mono focus:ring-2 focus:ring-emerald-500 outline-none">
                <p v-if="nextRunPreview" class="text-[11px] text-sky-400 mt-1">
                  下次執行（台北）：{{ nextRunPreview }}
                </p>
              </div>
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-400 mb-1">描述</label>
              <textarea v-model="editForm.description" rows="2" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none resize-none"></textarea>
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-400 mb-1">目標列表</label>
              <select
                v-model="editForm.target_list_id"
                class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none text-sm"
              >
                <option :value="null">預設（Scheduled）</option>
                <option v-for="sl in projectStageLists" :key="sl.id" :value="sl.id">{{ sl.name }}</option>
              </select>
              <p class="text-[10px] text-slate-500 mt-1">指定卡片建立後要放入的列表，會依該列表的行為設定執行</p>
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-400 mb-1">提示詞模板</label>
              <textarea v-model="editForm.prompt_template" rows="8" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 font-mono text-sm focus:ring-2 focus:ring-emerald-500 outline-none"></textarea>
            </div>
            <div class="flex justify-end gap-2">
              <button @click="editing = false" class="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">取消</button>
              <button @click="saveEdit" class="flex items-center gap-1.5 px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-white rounded-lg text-sm font-medium transition-all">
                <Check class="w-4 h-4" />
                儲存
              </button>
            </div>
          </div>
        </template>

        <!-- 檢視模式 -->
        <template v-else>
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-4">
            <div>
              <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">下次執行</div>
              <div class="text-sm text-slate-200 font-mono">{{ formatTime(job.next_scheduled_at) }}</div>
            </div>
            <div>
              <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">執行次數</div>
              <div class="text-sm text-slate-200">{{ logsTotal }} 次</div>
            </div>
            <div>
              <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">排程週期</div>
              <div class="text-sm text-blue-400 font-mono">{{ job.cron_expression }}</div>
            </div>
            <div>
              <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">目標列表</div>
              <div class="text-sm text-slate-200">{{ targetListName }}</div>
            </div>
          </div>
          <div v-if="job.description" class="text-xs text-slate-400 mb-3">{{ job.description }}</div>
          <details class="group">
            <summary class="text-[10px] text-slate-500 uppercase tracking-wider cursor-pointer hover:text-slate-300 transition-colors">提示詞模板</summary>
            <pre class="mt-2 p-4 bg-slate-900/50 rounded-lg border border-slate-700/50 text-xs text-slate-300 font-mono whitespace-pre-wrap overflow-auto max-h-64">{{ job.prompt_template }}</pre>
          </details>
        </template>
      </div>

      <!-- 執行記錄 -->
      <div>
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-sm font-bold text-slate-200">執行記錄</h2>
          <button @click="fetchLogs" class="text-[10px] text-slate-500 hover:text-slate-300 transition-colors">重新整理</button>
        </div>

        <div v-if="logsLoading" class="text-center py-8 text-slate-500 text-sm">載入中...</div>

        <div v-else-if="logs.length === 0" class="bg-slate-800/30 rounded-xl border border-slate-700/50 p-12 text-center">
          <Timer class="w-8 h-8 mx-auto mb-3 text-slate-600 opacity-40" />
          <p class="text-xs text-slate-500">尚無執行記錄</p>
        </div>

        <div v-else class="space-y-2">
          <div v-for="log in logs" :key="log.id" class="bg-slate-800/50 rounded-xl border border-slate-700/50 overflow-hidden transition-colors hover:border-slate-600/50">
            <!-- Log 標題列 -->
            <div class="flex items-center gap-3 px-4 py-3 cursor-pointer" @click="toggleLog(log.id)">
              <component :is="statusIcon(log.status)" class="w-4 h-4 shrink-0" :class="statusColor(log.status)" />
              <div class="flex-1 min-w-0">
                <div class="text-xs text-slate-300 font-mono">{{ formatTime(log.created_at) }}</div>
              </div>
              <div class="flex items-center gap-3 text-[10px] text-slate-500">
                <span v-if="log.provider" class="px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-400">{{ log.provider }}{{ log.model ? ` / ${log.model}` : '' }}</span>
                <span v-if="log.duration_ms">{{ formatDuration(log.duration_ms) }}</span>
                <span v-if="log.cost_usd">{{ formatCost(log.cost_usd) }}</span>
                <span v-if="log.input_tokens || log.output_tokens" class="font-mono">{{ log.input_tokens + log.output_tokens }} tok</span>
              </div>
              <ChevronDown v-if="expandedLogId === log.id" class="w-4 h-4 text-slate-500 shrink-0" />
              <ChevronRight v-else class="w-4 h-4 text-slate-500 shrink-0" />
            </div>

            <!-- Log 展開內容 -->
            <div v-if="expandedLogId === log.id" class="border-t border-slate-700/50 px-4 py-3 space-y-3">
              <!-- Token 明細 -->
              <div v-if="log.input_tokens || log.output_tokens" class="flex gap-4 text-[10px] text-slate-500">
                <span>Input: {{ log.input_tokens?.toLocaleString() }}</span>
                <span>Output: {{ log.output_tokens?.toLocaleString() }}</span>
                <span v-if="log.cache_read_tokens">Cache Read: {{ log.cache_read_tokens?.toLocaleString() }}</span>
                <span v-if="log.cache_creation_tokens">Cache Create: {{ log.cache_creation_tokens?.toLocaleString() }}</span>
              </div>

              <!-- 錯誤訊息 -->
              <div v-if="log.error_message" class="p-3 bg-red-500/5 border border-red-500/20 rounded-lg">
                <div class="text-[10px] text-red-400 uppercase tracking-wider mb-1">Error</div>
                <pre class="text-xs text-red-300 whitespace-pre-wrap font-mono overflow-auto max-h-48">{{ log.error_message }}</pre>
              </div>

              <!-- AI 輸出 -->
              <div v-if="log.output">
                <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Output</div>
                <pre class="p-3 bg-slate-900/50 rounded-lg border border-slate-700/50 text-xs text-slate-300 font-mono whitespace-pre-wrap overflow-auto max-h-96">{{ log.output }}</pre>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
