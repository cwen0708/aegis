<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { Clock, Play, Pause, Trash2, AlertCircle, Plus, X, FolderOpen, Pencil, ChevronDown, ChevronRight } from 'lucide-vue-next'
import { useAegisStore } from '../stores/aegis'
import ConfirmDialog from '../components/ConfirmDialog.vue'

const route = useRoute()
const store = useAegisStore()
const cronJobs = ref<any[]>([])
const projects = ref<any[]>([])
const loading = ref(true)
const cronPausedProjects = ref<number[]>([])

// Modal 狀態
const showAddModal = ref(false)
const newJobForm = ref({
  project_id: null as number | null,
  name: '',
  description: '',
  cron_expression: '0 0 * * *',
  prompt_template: ''
})

// 編輯 Modal
const showEditModal = ref(false)
const editJobForm = ref<any>(null)

function openEditModal(job: any) {
  editJobForm.value = { ...job }
  showEditModal.value = true
}

const saveEditJob = async () => {
  if (!editJobForm.value) return
  try {
    const res = await fetch(`/api/v1/cron-jobs/${editJobForm.value.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: editJobForm.value.name,
        description: editJobForm.value.description,
        cron_expression: editJobForm.value.cron_expression,
        prompt_template: editJobForm.value.prompt_template,
      })
    })
    if (!res.ok) throw new Error('更新排程失敗')
    showEditModal.value = false
    store.addToast('排程已更新', 'success')
    await fetchCronJobs()
  } catch (e) {
    store.addToast('更新排程失敗', 'error')
  }
}

// 刪除確認
const confirmDeleteVisible = ref(false)
const deleteTargetId = ref<number | null>(null)

const fetchProjects = async () => {
  const res = await fetch('/api/v1/projects/')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  projects.value = await res.json()
}

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
  if (!newJobForm.value.name || !newJobForm.value.project_id) return
  try {
    const res = await fetch('/api/v1/cron-jobs/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newJobForm.value)
    })
    if (!res.ok) throw new Error('建立排程失敗')
    showAddModal.value = false
    store.addToast('排程已建立', 'success')
    await fetchCronJobs()
    newJobForm.value = { project_id: null, name: '', description: '', cron_expression: '0 0 * * *', prompt_template: '' }
  } catch (e) {
    store.addToast('建立排程失敗', 'error')
  }
}

const toggleJob = async (job: any) => {
  const newStatus = !job.is_enabled
  try {
    const res = await fetch(`/api/v1/cron-jobs/${job.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_enabled: newStatus })
    })
    if (!res.ok) throw new Error('操作失敗')
    job.is_enabled = newStatus
    store.addToast(newStatus ? '排程已啟用' : '排程已停用', 'info')
  } catch (e) {
    store.addToast('操作失敗', 'error')
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

function projectName(projectId: number) {
  return projects.value.find((p: any) => p.id === projectId)?.name ?? `#${projectId}`
}

function isProjectCronPaused(projectId: number) {
  return cronPausedProjects.value.includes(projectId)
}

async function toggleProjectCron(projectId: number) {
  try {
    if (isProjectCronPaused(projectId)) {
      await store.resumeCron(projectId)
    } else {
      await store.pauseCron(projectId)
    }
    await fetchCronPausedProjects()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}

onMounted(async () => {
  await fetchCronJobs()
  await fetchProjects()
  await fetchCronPausedProjects()
  if (route.query.new === 'true') {
    showAddModal.value = true
  }
})

const formatTime = (iso: string) => {
  if (!iso) return '從未執行'
  const tz = store.settings.timezone || 'Asia/Taipei'
  return new Date(iso).toLocaleString('zh-TW', { timeZone: tz })
}

// 整體排程狀態（有任何專案被暫停就算 partial）
const totalEnabledJobs = computed(() => cronJobs.value.filter((j: any) => j.is_enabled).length)
const hasPausedProjects = computed(() => cronPausedProjects.value.length > 0)

// 按專案分組
const jobsByProject = computed(() => {
  const map = new Map<number, { project: any; jobs: any[] }>()
  for (const job of cronJobs.value) {
    if (!map.has(job.project_id)) {
      const proj = projects.value.find((p: any) => p.id === job.project_id)
      map.set(job.project_id, { project: proj ?? { id: job.project_id, name: `#${job.project_id}` }, jobs: [] })
    }
    map.get(job.project_id)!.jobs.push(job)
  }
  return Array.from(map.values())
})

// 折疊狀態：collapsed = 只顯示前 10 則，expanded = 全部顯示
const COLLAPSE_THRESHOLD = 10
const collapsedProjects = ref<Set<number>>(new Set())  // 完全收合（隱藏表格）
const expandedProjects = ref<Set<number>>(new Set())    // 超過 10 則時，展開全部

function toggleCollapse(projectId: number) {
  if (collapsedProjects.value.has(projectId)) {
    collapsedProjects.value.delete(projectId)
  } else {
    collapsedProjects.value.add(projectId)
  }
}

function toggleExpand(projectId: number) {
  if (expandedProjects.value.has(projectId)) {
    expandedProjects.value.delete(projectId)
  } else {
    expandedProjects.value.add(projectId)
  }
}

function visibleJobs(group: { project: any; jobs: any[] }) {
  const pid = group.project.id
  if (group.jobs.length <= COLLAPSE_THRESHOLD || expandedProjects.value.has(pid)) {
    return group.jobs
  }
  return group.jobs.slice(0, COLLAPSE_THRESHOLD)
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header h-16 -->
    <div class="sticky top-0 z-10 h-16 shrink-0 bg-slate-900/50 backdrop-blur-md border-b border-slate-800 px-8 flex items-center justify-between">
      <!-- Left: 排程狀態群組（與 Kanban 同風格） -->
      <div class="flex items-center bg-slate-700/50 rounded-lg border border-slate-600/50 overflow-hidden">
        <div class="flex items-center gap-1.5 px-3 py-1.5">
          <Clock class="w-3.5 h-3.5" :class="hasPausedProjects ? 'text-amber-400' : 'text-emerald-400'" />
          <span class="text-xs font-medium text-slate-200">排程</span>
        </div>
        <div class="w-px h-5 bg-slate-600/50"></div>
        <div class="flex items-center gap-1.5 px-2.5 py-1.5">
          <span class="text-xs font-bold text-blue-400">{{ totalEnabledJobs }}</span>
          <span class="text-[10px] text-slate-500">/{{ cronJobs.length }}</span>
        </div>
        <div class="w-px h-5 bg-slate-600/50"></div>
        <div class="flex items-center px-2.5 py-1.5">
          <span class="text-[10px] text-slate-400 font-mono">{{ store.settings.timezone || 'Asia/Taipei' }}</span>
        </div>
      </div>

      <!-- Right: Actions -->
      <div class="flex items-center gap-3">
        <button @click="showAddModal = true" class="flex items-center gap-1.5 bg-emerald-500 hover:bg-emerald-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium transition-all shadow-lg shadow-emerald-500/20">
          <Plus class="w-3.5 h-3.5" />
          新增排程
        </button>
      </div>
    </div>

    <div class="flex-1 overflow-auto p-8 space-y-6">

    <!-- 無排程 -->
    <div v-if="cronJobs.length === 0 && !loading" class="bg-slate-800/30 rounded-2xl border border-slate-700/50 p-20 text-center">
      <AlertCircle class="w-10 h-10 mx-auto mb-4 text-slate-600 opacity-40" />
      <p class="text-sm text-slate-500">尚無排程任務。</p>
    </div>

    <!-- 按專案分組 -->
    <div v-for="group in jobsByProject" :key="group.project.id" class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden shadow-xl">
      <!-- 專案標題列（可點擊折疊） -->
      <div class="flex items-center justify-between px-6 py-3 bg-slate-800/80 cursor-pointer select-none" :class="collapsedProjects.has(group.project.id) ? '' : 'border-b border-slate-700'" @click="toggleCollapse(group.project.id)">
        <div class="flex items-center gap-2.5">
          <ChevronRight v-if="collapsedProjects.has(group.project.id)" class="w-4 h-4 text-slate-500 transition-transform" />
          <ChevronDown v-else class="w-4 h-4 text-slate-500 transition-transform" />
          <FolderOpen class="w-4 h-4 text-emerald-400" />
          <span class="text-sm font-semibold text-slate-100">{{ group.project.name }}</span>
          <span class="text-[10px] text-slate-500 font-mono">{{ group.jobs.length }} 個排程</span>
        </div>
        <div class="flex items-center gap-2" @click.stop>
          <span
            v-if="isProjectCronPaused(group.project.id)"
            class="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20"
          >排程暫停中</span>
          <button
            @click="toggleProjectCron(group.project.id)"
            class="flex items-center gap-1 text-[10px] px-2 py-1 rounded-lg transition-colors"
            :class="isProjectCronPaused(group.project.id)
              ? 'text-emerald-400 hover:bg-emerald-500/10'
              : 'text-amber-400 hover:bg-amber-500/10'"
            :title="isProjectCronPaused(group.project.id) ? '啟動此專案排程' : '暫停此專案排程'"
          >
            <Play v-if="isProjectCronPaused(group.project.id)" class="w-3 h-3" />
            <Pause v-else class="w-3 h-3" />
            {{ isProjectCronPaused(group.project.id) ? '啟動' : '暫停' }}
          </button>
        </div>
      </div>

      <!-- 排程表格（折疊時隱藏） -->
      <table v-if="!collapsedProjects.has(group.project.id)" class="w-full text-left border-collapse">
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
          <tr v-for="job in visibleJobs(group)" :key="job.id" class="hover:bg-slate-700/20 transition-colors group">
            <td class="px-6 py-3">
              <div class="font-medium text-sm text-slate-100">{{ job.name }}</div>
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
            <td class="px-6 py-3 text-right">
              <div class="flex justify-end gap-1.5">
                <button
                  @click="openEditModal(job)"
                  class="p-1.5 text-slate-500 hover:text-blue-400 hover:bg-blue-400/10 rounded-lg transition-colors"
                  title="編輯排程"
                >
                  <Pencil class="w-3.5 h-3.5" />
                </button>
                <button
                  @click="toggleJob(job)"
                  :class="[
                    'p-1.5 rounded-lg transition-colors',
                    job.is_enabled ? 'text-amber-400 hover:bg-amber-400/10' : 'text-emerald-400 hover:bg-emerald-400/10'
                  ]"
                  :title="job.is_enabled ? '停用此排程' : '啟用此排程'"
                >
                  <Pause v-if="job.is_enabled" class="w-3.5 h-3.5" />
                  <Play v-else class="w-3.5 h-3.5" />
                </button>
                <button
                  v-if="!job.is_system"
                  @click="requestDelete(job.id)"
                  class="p-1.5 text-slate-500 hover:text-red-400 hover:bg-red-400/10 rounded-lg transition-colors"
                  title="刪除排程"
                >
                  <Trash2 class="w-3.5 h-3.5" />
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <!-- 展開更多 / 收合 -->
      <div
        v-if="!collapsedProjects.has(group.project.id) && group.jobs.length > COLLAPSE_THRESHOLD"
        class="px-6 py-2.5 border-t border-slate-700/30 text-center"
      >
        <button
          @click="toggleExpand(group.project.id)"
          class="text-[11px] text-slate-400 hover:text-slate-200 transition-colors"
        >
          <template v-if="expandedProjects.has(group.project.id)">
            收合（顯示前 {{ COLLAPSE_THRESHOLD }} 則）
          </template>
          <template v-else>
            顯示全部 {{ group.jobs.length }} 則（還有 {{ group.jobs.length - COLLAPSE_THRESHOLD }} 則）
          </template>
        </button>
      </div>
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
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-xs font-medium text-slate-400 mb-1">目標專案</label>
              <select v-model="newJobForm.project_id" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none">
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
              <span class="text-[10px] text-slate-500 px-3 border-l border-slate-700">UTC+8</span>
            </div>
          </div>

          <div>
            <label class="block text-xs font-medium text-slate-400 mb-1">描述（選填）</label>
            <textarea v-model="newJobForm.description" rows="2" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none resize-none"></textarea>
          </div>

          <div class="space-y-4">
            <div>
              <label class="block text-xs font-medium text-slate-400 mb-1">提示詞模板</label>
              <textarea v-model="newJobForm.prompt_template" rows="5" placeholder="定義 AI 的任務..." class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 font-mono text-sm focus:ring-2 focus:ring-emerald-500 outline-none"></textarea>
            </div>
          </div>
        </div>

        <div class="p-4 border-t border-slate-700 bg-slate-800/50 flex justify-end gap-3">
          <button @click="showAddModal = false" class="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">取消</button>
          <button @click="createCronJob" :disabled="!newJobForm.name || !newJobForm.project_id" class="px-6 py-2 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg font-bold transition-all shadow-lg shadow-emerald-500/20">
            建立排程
          </button>
        </div>
      </div>
    </div>

    <!-- Edit Job Modal -->
    <div v-if="showEditModal && editJobForm" class="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div class="bg-slate-800 border border-slate-700 rounded-2xl w-full max-w-2xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden">
        <div class="p-6 border-b border-slate-700 flex justify-between items-center bg-slate-800/50">
          <h3 class="text-xl font-bold text-slate-100">編輯排程</h3>
          <button @click="showEditModal = false" class="text-slate-400 hover:text-slate-200"><X class="w-6 h-6" /></button>
        </div>

        <div class="p-6 overflow-y-auto custom-scrollbar space-y-4">
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-xs font-medium text-slate-400 mb-1">所屬專案</label>
              <div class="w-full bg-slate-900/50 border border-slate-700 rounded-lg p-2.5 text-slate-500 text-sm">{{ projectName(editJobForm.project_id) }}</div>
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-400 mb-1">排程名稱</label>
              <input v-model="editJobForm.name" type="text" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none">
            </div>
          </div>

          <div>
            <label class="block text-xs font-medium text-slate-400 mb-1">Cron 表達式</label>
            <div class="flex items-center gap-2 bg-slate-900 border border-slate-700 rounded-lg p-1">
              <Clock class="w-4 h-4 ml-2 text-slate-500" />
              <input v-model="editJobForm.cron_expression" type="text" class="flex-1 bg-transparent border-none p-2 text-blue-400 font-mono focus:ring-0 outline-none">
              <span class="text-[10px] text-slate-500 px-3 border-l border-slate-700">UTC+8</span>
            </div>
          </div>

          <div>
            <label class="block text-xs font-medium text-slate-400 mb-1">描述</label>
            <textarea v-model="editJobForm.description" rows="2" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none resize-none"></textarea>
          </div>

          <div class="space-y-4">
            <div>
              <label class="block text-xs font-medium text-slate-400 mb-1">提示詞模板</label>
              <textarea v-model="editJobForm.prompt_template" rows="5" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 font-mono text-sm focus:ring-2 focus:ring-emerald-500 outline-none"></textarea>
            </div>
          </div>
        </div>

        <div class="p-4 border-t border-slate-700 bg-slate-800/50 flex justify-end gap-3">
          <button @click="showEditModal = false" class="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">取消</button>
          <button @click="saveEditJob" :disabled="!editJobForm.name" class="px-6 py-2 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg font-bold transition-all shadow-lg shadow-emerald-500/20">
            儲存變更
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
