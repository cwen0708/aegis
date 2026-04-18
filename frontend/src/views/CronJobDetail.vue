<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Play, Pause, Check, AlertCircle, CheckCircle2, XCircle, Timer, ChevronDown, ChevronRight, Zap, CalendarDays, Tag } from 'lucide-vue-next'

const GROUP_OPTIONS = ['派工', '風險分析', '訊息收集', 'Edge 巡檢', '站會 / 會議', '系統', 'ESS']
import ParsedOutput from '../components/ParsedOutput.vue'
import CronCalendar from '../components/CronCalendar.vue'
import { useAegisStore } from '../stores/aegis'
import { useAuthStore } from '../stores/auth'
import { apiClient } from '../services/api/client'

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

// 日曆篩選
const selectedDate = ref<string | null>(null)
const showCalendar = ref(true)

function toDateKey(iso: string): string {
  const d = new Date(iso.includes('Z') || iso.includes('+') ? iso : iso.replace(' ', 'T') + 'Z')
  return d.toISOString().slice(0, 10)
}

const filteredLogs = computed(() => {
  if (!selectedDate.value) return logs.value
  return logs.value.filter(log => toDateKey(log.created_at) === selectedDate.value)
})

const selectedDateStats = computed(() => {
  if (!selectedDate.value) return null
  const dayLogs = filteredLogs.value
  const success = dayLogs.filter(l => l.status === 'success').length
  const error = dayLogs.filter(l => l.status !== 'success').length
  return { success, error, total: dayLogs.length, date: selectedDate.value }
})

function onCalendarSelectDate(date: string | null) {
  selectedDate.value = date
  expandedLogId.value = null
}

// 編輯模式
const editing = ref(false)
const editForm = ref<any>(null)

// 目標列表選擇器
const projectStageLists = ref<any[]>([])
const fetchStageLists = async (projectId: number) => {
  try {
    projectStageLists.value = await apiClient.get(`/api/v1/projects/${projectId}/board`)
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
  const normalized = iso.includes('Z') || iso.includes('+') ? iso : iso.replace(' ', 'T') + 'Z'
  return new Date(normalized).toLocaleString('zh-TW', { timeZone: tz })
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
    job.value = await apiClient.get(`/api/v1/cron-jobs/${jobId.value}`)
  } catch (e) {
    console.error('Failed to fetch cron job', e)
    store.addToast('載入排程失敗', 'error')
  }
}

async function fetchLogs() {
  logsLoading.value = true
  try {
    const data = await apiClient.get(`/api/v1/cron-jobs/${jobId.value}/logs?limit=50`)
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
    await apiClient.post(`/api/v1/cron-jobs/${job.value.id}/trigger`)
    store.addToast(`已手動觸發「${job.value.name}」`, 'success')
  } catch (e: any) {
    store.addToast(e.message || '觸發失敗', 'error')
  }
}

async function toggleEnabled() {
  if (!job.value) return
  const newStatus = !job.value.is_enabled
  try {
    await apiClient.patch(`/api/v1/cron-jobs/${job.value.id}`, { is_enabled: newStatus })
    job.value.is_enabled = newStatus
    store.addToast(newStatus ? '排程已啟用' : '排程已停用', 'info')
  } catch (e) {
    store.addToast('操作失敗', 'error')
  }
}

// 排程統一使用 UTC
const systemTimezone = computed(() => 'UTC')

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
  const parts = cronExpr.trim().split(/\s+/)
  if (parts.length !== 5) return '格式錯誤（需要 5 個欄位）'

  const minStr = parts[0] ?? '*'
  const hourStr = parts[1] ?? '*'
  const min = minStr === '*' ? 0 : parseInt(minStr)
  const hour = hourStr === '*' ? -1 : parseInt(hourStr)
  if (isNaN(min) || (hour !== -1 && isNaN(hour))) return ''

  const tz = systemTimezone.value
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
    const str = local.toLocaleString('zh-TW', { timeZone: tz, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
    if (!results.includes(str)) results.push(str)
  }

  // 計算 UTC offset 顯示
  const offsetStr = new Date().toLocaleString('en', { timeZone: tz, timeZoneName: 'shortOffset' }).split(' ').pop() || ''

  return results.length > 0 ? results.join('、') + ` (${offsetStr})` : '無法計算'
}

function startEdit() {
  editForm.value = {
    name: job.value.name,
    description: job.value.description || '',
    cron_expression: job.value.cron_expression,
    prompt_template: job.value.prompt_template,
    target_list_id: job.value.target_list_id || null,
    api_url: job.value.api_url || '',
    group: job.value.group || '',
  }
  editing.value = true
  if (job.value.project_id) fetchStageLists(job.value.project_id)
}

async function saveEdit() {
  try {
    await apiClient.patch(`/api/v1/cron-jobs/${job.value.id}`, editForm.value)
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
  if (job.value?.project_id) {
    fetchStageLists(job.value.project_id)
  }
  // 已登入 → 自動進入編輯模式
  if (auth.isAuthenticated && job.value) {
    startEdit()
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
    <!-- Header: 只放返回鍵 + 標題 -->
    <div class="sticky top-0 z-10 h-14 sm:h-16 shrink-0 bg-slate-900/50 backdrop-blur-md border-b border-slate-800 px-2 sm:px-8 flex items-center">
      <div class="flex items-center gap-3 min-w-0">
        <button @click="router.push('/cron')" class="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 rounded-lg transition-colors shrink-0">
          <ArrowLeft class="w-5 h-5" />
        </button>
        <h1 v-if="job" class="text-sm sm:text-base font-bold text-slate-100 truncate">{{ job.name }}</h1>
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
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-4 sm:p-6">
        <!-- 已登入：直接顯示編輯表單 -->
        <template v-if="auth.isAuthenticated && editing">
          <div class="space-y-4">
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label class="block text-xs font-medium text-slate-400 mb-1">排程名稱</label>
                <input v-model="editForm.name" type="text" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none">
              </div>
              <div>
                <label class="block text-xs font-medium text-slate-400 mb-1">Cron 表達式 <span class="text-blue-400/60">(UTC+0)</span></label>
                <input v-model="editForm.cron_expression" type="text" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-blue-400 font-mono focus:ring-2 focus:ring-emerald-500 outline-none">
                <p v-if="nextRunPreview" class="text-[11px] text-sky-400 mt-1">
                  下次執行：{{ nextRunPreview }}
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
              <label class="block text-xs font-medium text-slate-400 mb-1">API URL（留空 = 建卡片）</label>
              <input v-model="editForm.api_url" type="text" placeholder="/api/v1/agent-chat/meeting"
                class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-blue-400 font-mono text-sm focus:ring-2 focus:ring-emerald-500 outline-none">
              <p class="text-[10px] text-slate-500 mt-1">
                {{ editForm.api_url ? '⚡ API 模式：下方內容為 JSON body，時間到直接 POST' : '🤖 AI 模式：下方內容為 AI 提示詞，時間到建卡片' }}
              </p>
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-400 mb-1">
                <Tag class="w-3 h-3 inline mr-1" />分組（選填）
              </label>
              <input v-model="editForm.group" type="text" placeholder="例如：風險分析、派工" list="group-options-detail"
                class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 text-sm focus:ring-2 focus:ring-violet-500 outline-none">
              <datalist id="group-options-detail">
                <option v-for="g in GROUP_OPTIONS" :key="g" :value="g" />
              </datalist>
              <div class="flex flex-wrap gap-1.5 mt-2">
                <button
                  v-for="g in GROUP_OPTIONS"
                  :key="g"
                  type="button"
                  @click="editForm.group = editForm.group === g ? '' : g"
                  :class="[
                    'px-2 py-0.5 rounded-full text-[10px] border transition-colors',
                    editForm.group === g ? 'bg-violet-600/30 text-violet-300 border-violet-500/50' : 'text-slate-500 border-slate-600 hover:text-slate-300'
                  ]"
                >{{ g }}</button>
              </div>
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-400 mb-1">
                {{ editForm.api_url ? '請求內容（JSON）' : '提示詞模板' }}
              </label>
              <textarea v-model="editForm.prompt_template" rows="8" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 font-mono text-sm focus:ring-2 focus:ring-emerald-500 outline-none"></textarea>
            </div>
          </div>
        </template>

        <!-- 未登入：唯讀檢視 -->
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
            <div v-if="job.group">
              <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">分組</div>
              <span class="px-2 py-0.5 rounded-full text-xs font-medium border bg-violet-600/20 text-violet-300 border-violet-500/30">{{ job.group }}</span>
            </div>
          </div>
          <div v-if="job.description" class="text-xs text-slate-400 mb-3">{{ job.description }}</div>
          <details class="group">
            <summary class="text-[10px] text-slate-500 uppercase tracking-wider cursor-pointer hover:text-slate-300 transition-colors">提示詞模板</summary>
            <pre class="mt-2 p-4 bg-slate-900/50 rounded-lg border border-slate-700/50 text-xs text-slate-300 font-mono whitespace-pre-wrap overflow-auto max-h-64">{{ job.prompt_template }}</pre>
          </details>
        </template>
      </div>

      <!-- 操作按鈕列（卡片下方） -->
      <div v-if="auth.isAuthenticated" class="flex flex-wrap gap-2">
        <button v-if="editing" @click="saveEdit" class="flex items-center gap-1.5 px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-white rounded-lg text-xs font-medium transition-all">
          <Check class="w-3.5 h-3.5" />
          儲存變更
        </button>
        <button @click="triggerJob" class="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium text-cyan-400 bg-cyan-400/5 hover:bg-cyan-400/10 border border-cyan-400/20 transition-all">
          <Zap class="w-3.5 h-3.5" />
          手動執行
        </button>
        <button @click="toggleEnabled" :class="[
          'flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium border transition-all',
          job.is_enabled
            ? 'text-amber-400 bg-amber-400/5 hover:bg-amber-400/10 border-amber-400/20'
            : 'text-emerald-400 bg-emerald-400/5 hover:bg-emerald-400/10 border-emerald-400/20'
        ]">
          <Pause v-if="job.is_enabled" class="w-3.5 h-3.5" />
          <Play v-else class="w-3.5 h-3.5" />
          {{ job.is_enabled ? '停用' : '啟用' }}
        </button>
      </div>

      <!-- 日曆視圖 -->
      <div>
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-sm font-bold text-slate-200 flex items-center gap-2">
            <CalendarDays class="w-4 h-4 text-slate-400" />
            執行日曆
          </h2>
          <button
            @click="showCalendar = !showCalendar"
            class="text-[10px] text-slate-500 hover:text-slate-300 transition-colors"
          >
            {{ showCalendar ? '收起' : '展開' }}
          </button>
        </div>
        <CronCalendar v-if="showCalendar" :logs="logs" @select-date="onCalendarSelectDate" />
      </div>

      <!-- 執行記錄 -->
      <div>
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-3">
            <h2 class="text-sm font-bold text-slate-200">執行記錄</h2>
            <!-- 已選日期統計 -->
            <template v-if="selectedDateStats">
              <span class="text-[10px] text-slate-500">{{ selectedDateStats.date }}</span>
              <span class="px-1.5 py-0.5 rounded text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                成功 {{ selectedDateStats.success }}
              </span>
              <span v-if="selectedDateStats.error > 0" class="px-1.5 py-0.5 rounded text-[10px] bg-red-500/10 text-red-400 border border-red-500/20">
                失敗 {{ selectedDateStats.error }}
              </span>
              <button @click="selectedDate = null; expandedLogId = null" class="text-[10px] text-slate-500 hover:text-slate-300">
                清除篩選
              </button>
            </template>
          </div>
          <button @click="fetchLogs" class="text-[10px] text-slate-500 hover:text-slate-300 transition-colors">重新整理</button>
        </div>

        <div v-if="logsLoading" class="text-center py-8 text-slate-500 text-sm">載入中...</div>

        <div v-else-if="logs.length === 0" class="bg-slate-800/30 rounded-xl border border-slate-700/50 p-12 text-center">
          <Timer class="w-8 h-8 mx-auto mb-3 text-slate-600 opacity-40" />
          <p class="text-xs text-slate-500">尚無執行記錄</p>
        </div>

        <div v-else-if="filteredLogs.length === 0" class="bg-slate-800/30 rounded-xl border border-slate-700/50 p-8 text-center">
          <CalendarDays class="w-8 h-8 mx-auto mb-3 text-slate-600 opacity-40" />
          <p class="text-xs text-slate-500">{{ selectedDate }} 無執行記錄</p>
        </div>

        <div v-else class="space-y-2">
          <div v-for="log in filteredLogs" :key="log.id" class="bg-slate-800/50 rounded-xl border border-slate-700/50 overflow-hidden transition-colors hover:border-slate-600/50">
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
                <div class="p-3 bg-slate-900/50 rounded-lg border border-slate-700/50 overflow-auto max-h-96">
                  <ParsedOutput :output="log.output" />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
