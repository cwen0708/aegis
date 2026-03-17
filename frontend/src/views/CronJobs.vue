<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Clock, Play, Pause, Trash2, AlertCircle, Plus, X, Pencil, Zap } from 'lucide-vue-next'
import { useAegisStore } from '../stores/aegis'
import { useAuthStore } from '../stores/auth'
import { authHeaders } from '../utils/authFetch'
import { useEscapeKey } from '../composables/useEscapeKey'
import { useResponsive } from '../composables/useResponsive'
import { useProjectSelector } from '../composables/useProjectSelector'
import PageHeader from '../components/PageHeader.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'

const { isMobile } = useResponsive()

const route = useRoute()
const router = useRouter()
const store = useAegisStore()
const auth = useAuthStore()
const { projects, selectedProjectId } = useProjectSelector()
const cronJobs = ref<any[]>([])
const loading = ref(true)
const cronPausedProjects = ref<number[]>([])

// Modal 狀態
const showAddModal = ref(false)
useEscapeKey(showAddModal, () => { showAddModal.value = false })
const newJobForm = ref({
  project_id: null as number | null,
  name: '',
  description: '',
  cron_expression: '0 0 * * *',
  prompt_template: '',
  target_list_id: null as number | null,
})

// 取得指定專案的列表（供目標列表選擇器用）
const projectStageLists = ref<any[]>([])
const fetchStageLists = async (projectId: number) => {
  try {
    const res = await fetch(`/api/v1/projects/${projectId}/board`)
    if (res.ok) projectStageLists.value = await res.json()
  } catch { projectStageLists.value = [] }
}

function goToEdit(job: any) {
  router.push(`/cron/${job.id}`)
}

// 刪除確認
const confirmDeleteVisible = ref(false)
const deleteTargetId = ref<number | null>(null)

const fetchCronJobs = async () => {
  loading.value = true
  try {
    const res = await fetch('/api/v1/cron-jobs/')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    cronJobs.value = await res.json()
  } catch (e) {
    console.error('Failed to fetch cron jobs', e)
  } finally {
    loading.value = false
  }
}

const createCronJob = async () => {
  const pid = newJobForm.value.project_id || selectedProjectId.value
  if (!newJobForm.value.name || !pid) return
  try {
    const res = await fetch('/api/v1/cron-jobs/', {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ ...newJobForm.value, project_id: pid })
    })
    if (!res.ok) throw new Error('建立排程失敗')
    showAddModal.value = false
    store.addToast('排程已建立', 'success')
    await fetchCronJobs()
    newJobForm.value = { project_id: null, name: '', description: '', cron_expression: '0 0 * * *', prompt_template: '', target_list_id: null }
  } catch (e) {
    store.addToast('建立排程失敗', 'error')
  }
}

const toggleJob = async (job: any) => {
  const newStatus = !job.is_enabled
  try {
    const res = await fetch(`/api/v1/cron-jobs/${job.id}`, {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ is_enabled: newStatus })
    })
    if (!res.ok) throw new Error('操作失敗')
    job.is_enabled = newStatus
    store.addToast(newStatus ? '排程已啟用' : '排程已停用', 'info')
  } catch (e) {
    store.addToast('操作失敗', 'error')
  }
}

const triggerJob = async (job: any) => {
  try {
    const res = await fetch(`/api/v1/cron-jobs/${job.id}/trigger`, {
      method: 'POST',
      headers: authHeaders(),
    })
    const data = await res.json()
    if (!res.ok) {
      store.addToast(data.detail || '觸發失敗', 'error')
      return
    }
    store.addToast(`已手動觸發「${job.name}」`, 'success')
  } catch (e) {
    store.addToast('觸發失敗', 'error')
  }
}

function requestDelete(jobId: number) {
  deleteTargetId.value = jobId
  confirmDeleteVisible.value = true
}

async function confirmDeleteJob() {
  if (!deleteTargetId.value) return
  try {
    await store.deleteCronJob(deleteTargetId.value)
    confirmDeleteVisible.value = false
    deleteTargetId.value = null
    await fetchCronJobs()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}

const fetchCronPausedProjects = async () => {
  try {
    const res = await fetch('/api/v1/system/services')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    cronPausedProjects.value = data?.engines?.cron_poller?.paused_projects ?? []
  } catch (e) {
    console.error('Failed to fetch cron paused projects', e)
  }
}

const isCronPaused = computed(() => {
  if (!selectedProjectId.value) return false
  return cronPausedProjects.value.includes(selectedProjectId.value)
})

async function toggleCron() {
  if (!selectedProjectId.value) return
  try {
    if (isCronPaused.value) {
      await store.resumeCron(selectedProjectId.value)
    } else {
      await store.pauseCron(selectedProjectId.value)
    }
    await fetchCronPausedProjects()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}

// 依選中專案篩選
const filteredJobs = computed(() => {
  if (!selectedProjectId.value) return cronJobs.value
  return cronJobs.value.filter(j => j.project_id === selectedProjectId.value)
})

const enabledCount = computed(() => filteredJobs.value.filter(j => j.is_enabled).length)

onMounted(async () => {
  await fetchCronJobs()
  await fetchCronPausedProjects()
  if (route.query.new === 'true') {
    showAddModal.value = true
  }
})

// 新增排程時預設帶入當前專案並載入列表
watch(showAddModal, (v) => {
  if (v && selectedProjectId.value) {
    newJobForm.value.project_id = selectedProjectId.value
    fetchStageLists(selectedProjectId.value)
  }
})

const formatTime = (iso: string) => {
  if (!iso) return '從未執行'
  const normalized = iso.includes('Z') || iso.includes('+') ? iso : iso.replace(' ', 'T') + 'Z'
  return new Date(normalized).toLocaleString('zh-TW', { timeZone: 'UTC' }) + ' UTC'
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <PageHeader :icon="Clock">
      <!-- 排程狀態 + 暫停控制 -->
      <div v-if="selectedProjectId && auth.isAuthenticated" class="flex items-center bg-slate-700/50 rounded-lg border border-slate-600/50 overflow-hidden">
        <div class="flex items-center gap-1.5 px-2.5 py-1.5">
          <span class="text-xs font-bold text-blue-400">{{ enabledCount }}</span>
          <span class="text-[10px] text-slate-500">/{{ filteredJobs.length }}</span>
        </div>
        <div class="w-px h-5 bg-slate-600/50"></div>
        <button
          @click="toggleCron"
          :title="isCronPaused ? '啟動此專案的排程' : '暫停此專案的排程'"
          class="flex items-center gap-1 px-2.5 py-1.5 transition-colors"
          :class="isCronPaused ? 'text-emerald-400 hover:bg-emerald-500/10' : 'text-amber-400 hover:bg-amber-500/10'"
        >
          <Play v-if="isCronPaused" class="w-3 h-3" />
          <Pause v-else class="w-3 h-3" />
          <span class="text-[10px] font-medium">{{ isCronPaused ? '啟動' : '暫停' }}</span>
        </button>
      </div>

      <button v-if="auth.isAuthenticated" @click="showAddModal = true" class="flex items-center justify-center gap-1.5 bg-emerald-500 hover:bg-emerald-600 text-white p-2 sm:px-3 sm:py-1.5 rounded-lg text-xs font-medium transition-all shadow-lg shadow-emerald-500/20">
        <Plus class="w-4 h-4 sm:w-3.5 sm:h-3.5" />
        <span class="hidden sm:inline">新增排程</span>
      </button>
    </PageHeader>

    <div class="flex-1 overflow-auto p-2 sm:p-8">

      <!-- 未選專案 -->
      <div v-if="!selectedProjectId" class="flex items-center justify-center h-full">
        <div class="text-center">
          <Clock class="w-12 h-12 text-slate-700 mx-auto mb-3" />
          <p class="text-slate-500 text-sm">選擇一個專案以查看排程</p>
        </div>
      </div>

      <!-- 無排程 -->
      <div v-else-if="filteredJobs.length === 0 && !loading" class="flex items-center justify-center h-full">
        <div class="text-center">
          <AlertCircle class="w-10 h-10 mx-auto mb-4 text-slate-600 opacity-40" />
          <p class="text-sm text-slate-500">此專案尚無排程任務</p>
        </div>
      </div>

      <!-- 手機版：卡片列表 -->
      <div v-else-if="isMobile" class="space-y-2">
        <!-- 暫停中提示 -->
        <div v-if="isCronPaused" class="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
          <Pause class="w-3.5 h-3.5 text-amber-400" />
          <span class="text-xs text-amber-400">此專案排程已暫停</span>
        </div>

        <div
          v-for="job in filteredJobs"
          :key="job.id"
          class="bg-slate-800/50 rounded-xl border border-slate-700/50 overflow-hidden"
        >
          <!-- 卡片主體（點擊進詳情） -->
          <div class="p-3" @click="router.push(`/cron/${job.id}`)">
            <div class="flex items-start justify-between gap-2">
              <div class="min-w-0">
                <div class="font-medium text-sm text-slate-100 truncate">{{ job.name }}</div>
                <div v-if="job.description" class="text-xs text-slate-500 mt-0.5 line-clamp-2">{{ job.description }}</div>
              </div>
              <span
                :class="[
                  'px-1.5 py-0.5 rounded text-[10px] font-bold border shrink-0',
                  job.is_enabled ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-slate-700 text-slate-500 border-slate-600'
                ]"
              >
                {{ job.is_enabled ? '啟用' : '停用' }}
              </span>
            </div>
            <div class="flex items-center gap-3 mt-2">
              <div class="flex items-center gap-1 text-blue-400 font-mono text-xs">
                <Clock class="w-3 h-3" />
                {{ job.cron_expression }}
              </div>
              <div class="text-[10px] text-slate-500 truncate">{{ formatTime(job.next_scheduled_at) }}</div>
            </div>
          </div>
          <!-- 操作按鈕已移至詳情頁 -->
        </div>
      </div>

      <!-- 桌面版：表格 -->
      <div v-else class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden shadow-xl">
        <!-- 暫停中提示 -->
        <div v-if="isCronPaused" class="flex items-center gap-2 px-6 py-2.5 bg-amber-500/5 border-b border-amber-500/20">
          <Pause class="w-3.5 h-3.5 text-amber-400" />
          <span class="text-xs text-amber-400">此專案排程已暫停，排程不會自動執行</span>
        </div>

        <table class="w-full text-left border-collapse">
          <thead>
            <tr class="text-slate-500 text-[10px] uppercase tracking-widest border-b border-slate-700/50">
              <th class="px-6 py-2.5 font-semibold">排程名稱</th>
              <th class="px-6 py-2.5 font-semibold">排程週期</th>
              <th class="px-6 py-2.5 font-semibold text-center">狀態</th>
              <th class="px-6 py-2.5 font-semibold">下次執行</th>
              <th class="px-6 py-2.5 font-semibold text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-700/30">
            <tr v-for="job in filteredJobs" :key="job.id" class="hover:bg-slate-700/20 transition-colors">
              <td class="px-6 py-3 cursor-pointer" @click="router.push(`/cron/${job.id}`)">
                <div class="font-medium text-sm text-slate-100 hover:text-emerald-400 transition-colors">{{ job.name }}</div>
                <div v-if="job.description" class="text-xs text-slate-500 mt-0.5 truncate max-w-xs">{{ job.description }}</div>
              </td>
              <td class="px-6 py-3">
                <div class="flex items-center gap-2 text-blue-400 font-mono text-sm">
                  <Clock class="w-3.5 h-3.5" />
                  {{ job.cron_expression }}
                </div>
              </td>
              <td class="px-6 py-3 text-center">
                <span
                  :class="[
                    'px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-tighter border',
                    job.is_enabled ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-slate-700 text-slate-500 border-slate-600'
                  ]"
                >
                  {{ job.is_enabled ? '啟用' : '停用' }}
                </span>
              </td>
              <td class="px-6 py-3 text-xs text-slate-400 font-mono">
                {{ formatTime(job.next_scheduled_at) }}
              </td>
              <td v-if="auth.isAuthenticated" class="px-6 py-3 text-right">
                <div class="flex justify-end gap-0.5 -mr-2">
                  <button
                    @click="triggerJob(job)"
                    class="p-2.5 text-cyan-400 hover:bg-cyan-400/10 rounded-lg transition-colors"
                    title="手動執行"
                  >
                    <Zap class="w-4 h-4" />
                  </button>
                  <button
                    @click="goToEdit(job)"
                    class="p-2.5 text-slate-500 hover:text-blue-400 hover:bg-blue-400/10 rounded-lg transition-colors"
                    title="編輯排程"
                  >
                    <Pencil class="w-4 h-4" />
                  </button>
                  <button
                    @click="toggleJob(job)"
                    :class="[
                      'p-2.5 rounded-lg transition-colors',
                      job.is_enabled ? 'text-amber-400 hover:bg-amber-400/10' : 'text-emerald-400 hover:bg-emerald-400/10'
                    ]"
                    :title="job.is_enabled ? '停用此排程' : '啟用此排程'"
                  >
                    <Pause v-if="job.is_enabled" class="w-4 h-4" />
                    <Play v-else class="w-4 h-4" />
                  </button>
                  <button
                    v-if="!job.is_system"
                    @click="requestDelete(job.id)"
                    class="p-2.5 text-slate-500 hover:text-red-400 hover:bg-red-400/10 rounded-lg transition-colors"
                    title="刪除排程"
                  >
                    <Trash2 class="w-4 h-4" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

    </div>

    <!-- Add Job Modal -->
    <div v-if="showAddModal" class="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div class="bg-slate-800 border border-slate-700 rounded-2xl w-full max-w-2xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden">
        <div class="p-6 border-b border-slate-700 flex justify-between items-center bg-slate-800/50">
          <h3 class="text-xl font-bold text-slate-100">建立新排程</h3>
          <button @click="showAddModal = false" class="text-slate-400 hover:text-slate-200"><X class="w-6 h-6" /></button>
        </div>

        <div class="p-6 overflow-y-auto custom-scrollbar space-y-4">
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label class="block text-xs font-medium text-slate-400 mb-1">目標專案</label>
              <select v-model="newJobForm.project_id" @change="newJobForm.project_id && fetchStageLists(newJobForm.project_id)" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none">
                <option :value="null">選擇專案...</option>
                <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
              </select>
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-400 mb-1">排程名稱</label>
              <input v-model="newJobForm.name" type="text" placeholder="例如：每日風險分析" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none">
            </div>
          </div>

          <div>
            <label class="block text-xs font-medium text-slate-400 mb-1">Cron 表達式</label>
            <div class="flex items-center gap-2 bg-slate-900 border border-slate-700 rounded-lg p-1">
              <Clock class="w-4 h-4 ml-2 text-slate-500" />
              <input v-model="newJobForm.cron_expression" type="text" class="flex-1 bg-transparent border-none p-2 text-blue-400 font-mono focus:ring-0 outline-none">
              <span class="text-[10px] text-blue-400/60 px-3 border-l border-slate-700">UTC+0</span>
            </div>
          </div>

          <div>
            <label class="block text-xs font-medium text-slate-400 mb-1">描述（選填）</label>
            <textarea v-model="newJobForm.description" rows="2" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none resize-none"></textarea>
          </div>

          <div>
            <label class="block text-xs font-medium text-slate-400 mb-1">目標列表</label>
            <select
              v-model="newJobForm.target_list_id"
              class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none text-sm"
            >
              <option :value="null">預設（Scheduled）</option>
              <option v-for="sl in projectStageLists" :key="sl.id" :value="sl.id">{{ sl.name }}</option>
            </select>
            <p class="text-[10px] text-slate-500 mt-1">指定卡片建立後要放入的列表，會依該列表的行為設定執行</p>
          </div>

          <div>
            <label class="block text-xs font-medium text-slate-400 mb-1">提示詞模板</label>
            <textarea v-model="newJobForm.prompt_template" rows="5" placeholder="定義 AI 的任務..." class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 font-mono text-sm focus:ring-2 focus:ring-emerald-500 outline-none"></textarea>
          </div>
        </div>

        <div class="p-4 border-t border-slate-700 bg-slate-800/50 flex justify-end gap-3">
          <button @click="showAddModal = false" class="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">取消</button>
          <button @click="createCronJob" :disabled="!newJobForm.name || !(newJobForm.project_id || selectedProjectId)" class="px-6 py-2 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg font-bold transition-all shadow-lg shadow-emerald-500/20">
            建立排程
          </button>
        </div>
      </div>
    </div>

    <!-- Delete Confirm -->
    <ConfirmDialog
      :show="confirmDeleteVisible"
      title="刪除排程"
      message="確定要刪除這個排程任務？此操作無法復原。"
      confirm-text="刪除"
      @confirm="confirmDeleteJob"
      @cancel="confirmDeleteVisible = false; deleteTargetId = null"
    />
  </div>
</template>
