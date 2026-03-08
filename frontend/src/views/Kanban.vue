<script setup lang="ts">
import { ref, inject, onMounted, onUnmounted, watch, computed, type Ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Plus, Play, Pause, Square, Clock, Trash2, Zap, MoreVertical, ChevronDown, FolderOpen, Eye, UserCircle } from 'lucide-vue-next'
import draggable from 'vuedraggable'
import { useAegisStore } from '../stores/aegis'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import TerminalViewer from '../components/TerminalViewer.vue'

const router = useRouter()
const route = useRoute()
const store = useAegisStore()

// 排程狀態（per-project paused set）
const cronPausedProjects = ref<number[]>([])

const fetchCronStatus = async () => {
  try {
    const res = await fetch('/api/v1/system/services')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    cronPausedProjects.value = data?.engines?.cron_poller?.paused_projects ?? []
  } catch (e) {
    console.error('Failed to fetch cron status', e)
  }
}

const isCronPausedForCurrentProject = computed(() => {
  if (!selectedProjectId.value) return false
  return cronPausedProjects.value.includes(selectedProjectId.value)
})

async function toggleCron() {
  if (!selectedProjectId.value) return
  try {
    if (isCronPausedForCurrentProject.value) {
      await store.resumeCron(selectedProjectId.value)
    } else {
      await store.pauseCron(selectedProjectId.value)
    }
    await fetchCronStatus()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}

// 從 App.vue 注入側邊欄模式控制
const sidebarMode = inject<Ref<'menu' | 'projects'>>('sidebarMode')

// 資料狀態
const projects = ref<any[]>([])
const selectedProjectId = ref<number | null>(null)
const boardData = ref<any[]>([])

// Modal 狀態
const showNewTaskModal = ref(false)
const newTaskForm = ref({ title: '', description: '' })

// 卡片選單
const openMenuCardId = ref<number | null>(null)

// 刪除確認
const confirmDelete = ref(false)
const deleteTargetCardId = ref<number | null>(null)

// 即時經過時間計數器
const elapsedTimers = ref<Map<number, string>>(new Map())
let elapsedInterval: ReturnType<typeof setInterval>

function updateElapsedTimers() {
  const now = Date.now() / 1000
  for (const task of store.runningTasks) {
    const diff = Math.floor(now - task.started_at)
    const m = Math.floor(diff / 60).toString().padStart(2, '0')
    const s = (diff % 60).toString().padStart(2, '0')
    elapsedTimers.value.set(task.task_id, `${m}:${s}`)
  }
}

// API
const fetchProjects = async () => {
  const res = await fetch('/api/v1/projects/')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  projects.value = await res.json()
  // 如果 URL 帶有 project query，使用它
  if (route.query.project) {
    selectedProjectId.value = Number(route.query.project)
  } else if (projects.value.length > 0 && !selectedProjectId.value) {
    selectedProjectId.value = projects.value[0].id
  }
}

const fetchBoard = async () => {
  if (!selectedProjectId.value) return
  const res = await fetch(`/api/v1/projects/${selectedProjectId.value}/board`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  boardData.value = await res.json()
}

const createCard = async () => {
  if (!newTaskForm.value.title || boardData.value.length === 0) return
  const firstListId = boardData.value[0].id
  const res = await fetch('/api/v1/cards/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ list_id: firstListId, title: newTaskForm.value.title, description: newTaskForm.value.description })
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  await fetchBoard()
  showNewTaskModal.value = false
  newTaskForm.value = { title: '', description: '' }
}

// 卡片詳情 Modal
const selectedCard = ref<any>(null)
const isEditingContent = ref(false)

const openCardDetail = async (cardId: number) => {
  openMenuCardId.value = null
  const res = await fetch(`/api/v1/cards/${cardId}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  selectedCard.value = await res.json()
  isEditingContent.value = false
}

const closeCardDetail = () => { selectedCard.value = null }

const saveCardDetail = async () => {
  if (!selectedCard.value) return
  const res = await fetch(`/api/v1/cards/${selectedCard.value.id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: selectedCard.value.title,
      description: selectedCard.value.description,
      content: selectedCard.value.content
    })
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  isEditingContent.value = false
  await fetchBoard()
}

// 拖曳
const onDragChange = async (event: any, targetListId: number) => {
  if (event.added) {
    const cardId = event.added.element.id
    try {
      const res = await fetch(`/api/v1/cards/${cardId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ list_id: targetListId })
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
    } catch (e) {
      fetchBoard()
    }
  }
}

const checkMove = (evt: any) => {
  const status = evt.draggedContext.element.status
  return status !== 'running' && status !== 'pending'
}

// 卡片操作
async function handleTrigger(cardId: number) {
  openMenuCardId.value = null
  try {
    await store.triggerCard(cardId)
    await fetchBoard()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}

async function handleAbort(cardId: number) {
  try {
    await store.abortCard(cardId)
    await fetchBoard()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}

function requestDeleteCard(cardId: number) {
  openMenuCardId.value = null
  deleteTargetCardId.value = cardId
  confirmDelete.value = true
}

async function confirmDeleteCard() {
  if (!deleteTargetCardId.value) return
  const targetId = deleteTargetCardId.value
  try {
    await store.deleteCard(targetId)
    confirmDelete.value = false
    deleteTargetCardId.value = null
    if (selectedCard.value?.id === targetId) {
      selectedCard.value = null
    }
    await fetchBoard()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}

// Runner 控制
async function toggleRunner() {
  try {
    if (store.systemInfo.is_paused) {
      await store.resumeRunner()
    } else {
      await store.pauseRunner()
    }
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}

// WebSocket 事件監聽：任務完成時自動重整看板
function onTaskEvent(e: Event) {
  const detail = (e as CustomEvent).detail
  if (detail.type === 'completed' || detail.type === 'failed') {
    fetchBoard()
  }
}

// 點擊外部關閉選單
function onDocumentClick() {
  openMenuCardId.value = null
}

watch(selectedProjectId, () => { fetchBoard() })
watch(() => route.query.project, (val) => {
  if (val) selectedProjectId.value = Number(val)
})

onMounted(() => {
  fetchProjects()
  fetchCronStatus()
  elapsedInterval = setInterval(updateElapsedTimers, 1000)
  window.addEventListener('aegis:task-event', onTaskEvent)
  document.addEventListener('click', onDocumentClick)
})

onUnmounted(() => {
  clearInterval(elapsedInterval)
  window.removeEventListener('aegis:task-event', onTaskEvent)
  document.removeEventListener('click', onDocumentClick)
})

// 判斷某卡片是否運行中
function isCardRunning(cardId: number) {
  return store.runningTasks.some(t => t.task_id === cardId)
}

// 當前專案
const currentProject = computed(() => projects.value.find(p => p.id === selectedProjectId.value))

// 成員指派 Dialog
interface MemberOption {
  id: number
  name: string
  avatar: string
  provider: string
  role?: string
}
const allMembers = ref<MemberOption[]>([])
const showAssignDialog = ref(false)
const assigningListId = ref<number | null>(null)
const assigningListName = ref('')

async function fetchMembers() {
  try {
    const res = await fetch('/api/v1/members')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    allMembers.value = await res.json()
  } catch {}
}

function openAssignDialog(stage: any) {
  assigningListId.value = stage.id
  assigningListName.value = stage.name
  showAssignDialog.value = true
  if (allMembers.value.length === 0) fetchMembers()
}

async function assignMember(memberId: number | null) {
  if (!assigningListId.value) return
  try {
    const res = await fetch(`/api/v1/lists/${assigningListId.value}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ member_id: memberId }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    showAssignDialog.value = false
    await fetchBoard()
  } catch (e: any) {
    store.addToast(e.message || '指派失敗', 'error')
  }
}

// 切換到側邊欄專案模式
function switchToProjectsSidebar() {
  if (sidebarMode) sidebarMode.value = 'projects'
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Sticky Header / Toolbar (h-16 = sidebar logo height) -->
    <div class="sticky top-0 z-10 h-16 shrink-0 bg-slate-900/50 backdrop-blur-md border-b border-slate-800 px-8 flex items-center justify-between gap-4">

      <!-- Left: Project Name + Runner -->
      <div class="flex items-center gap-4 min-w-0">
        <!-- Project Name (click → sidebar projects mode) -->
        <button
          @click="switchToProjectsSidebar"
          class="flex items-center gap-2 min-w-0 group"
        >
          <FolderOpen class="w-5 h-5 text-emerald-400 shrink-0" />
          <span class="text-lg font-bold text-slate-100 truncate group-hover:text-emerald-400 transition-colors">
            {{ currentProject?.name || '選擇專案' }}
          </span>
          <ChevronDown class="w-4 h-4 text-slate-500 shrink-0" />
        </button>

        <!-- Runner Controls -->
        <button
          @click="toggleRunner"
          class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors shrink-0"
          :class="store.systemInfo.is_paused
            ? 'bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20'
            : 'bg-amber-500/10 text-amber-400 hover:bg-amber-500/20'"
        >
          <Play v-if="store.systemInfo.is_paused" class="w-3.5 h-3.5" />
          <Pause v-else class="w-3.5 h-3.5" />
          {{ store.systemInfo.is_paused ? '恢復' : '暫停' }}
        </button>
      </div>

      <!-- Right: Actions -->
      <div class="flex items-center gap-2 shrink-0">
        <!-- 排程狀態群組（per-project） -->
        <div class="flex items-center bg-slate-700/50 rounded-lg border border-slate-600/50 overflow-hidden">
          <div class="flex items-center gap-1.5 px-3 py-1.5">
            <Clock class="w-3.5 h-3.5" :class="isCronPausedForCurrentProject ? 'text-amber-400' : 'text-emerald-400'" />
            <span class="text-xs font-medium text-slate-200">排程</span>
          </div>
          <div class="w-px h-5 bg-slate-600/50"></div>
          <button @click="router.push('/cron')" class="flex items-center gap-1 px-2.5 py-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-600/50 transition-colors">
            <Eye class="w-3 h-3" />
            <span class="text-[10px] font-medium">查看</span>
          </button>
          <div class="w-px h-5 bg-slate-600/50"></div>
          <button @click="toggleCron" :title="isCronPausedForCurrentProject ? '啟動此專案的排程' : '暫停此專案的排程'" class="flex items-center gap-1 px-2.5 py-1.5 transition-colors" :class="isCronPausedForCurrentProject ? 'text-emerald-400 hover:bg-emerald-500/10' : 'text-amber-400 hover:bg-amber-500/10'">
            <Play v-if="isCronPausedForCurrentProject" class="w-3 h-3" />
            <Pause v-else class="w-3 h-3" />
            <span class="text-[10px] font-medium">{{ isCronPausedForCurrentProject ? '啟動' : '暫停' }}</span>
          </button>
        </div>

        <button @click="showNewTaskModal = true" class="flex items-center gap-1.5 bg-emerald-500 hover:bg-emerald-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium transition-colors shadow-lg shadow-emerald-500/20">
          <Plus class="w-3.5 h-3.5" />
          新增任務
        </button>
      </div>
    </div>

    <!-- Kanban Board -->
    <div
      class="flex gap-5 flex-1 items-start overflow-x-auto px-6 py-4 custom-scrollbar transition-opacity duration-300"
      :class="{'opacity-50 grayscale pointer-events-none select-none': currentProject?.is_active === false}"
    >
      <div v-for="stage in boardData" :key="stage.id" class="w-80 shrink-0 bg-slate-800/40 rounded-xl p-4 border border-slate-700/50 flex flex-col max-h-full">
        <div class="flex items-center justify-between mb-4 px-1">
          <h3 class="font-medium text-slate-200 flex items-center gap-2">
            {{ stage.name }}
            <span v-if="stage.cards.some((c: any) => c.status === 'running')" class="relative flex h-2 w-2 ml-1">
              <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
          </h3>
          <div class="flex items-center gap-1.5">
            <button
              @click.stop="openAssignDialog(stage)"
              class="flex items-center justify-center w-6 h-6 rounded-full transition-colors"
              :class="stage.member ? 'bg-slate-700 hover:bg-slate-600' : 'text-slate-600 hover:text-slate-400 hover:bg-slate-700/50'"
              :title="stage.member ? `${stage.member.name} (${stage.member.provider})` : '指派成員'"
            >
              <span v-if="stage.member" class="text-xs">{{ stage.member.avatar || '🤖' }}</span>
              <UserCircle v-else class="w-4 h-4" />
            </button>
            <button v-if="stage.name === 'Backlog'" @click="showNewTaskModal = true" class="text-slate-500 hover:text-slate-300"><Plus class="w-4 h-4"/></button>
            <span class="bg-slate-700/50 text-slate-300 text-xs px-2.5 py-0.5 rounded-full border border-slate-600">{{ stage.cards.length }}</span>
          </div>
        </div>

        <draggable
          v-model="stage.cards"
          group="cards"
          item-key="id"
          class="flex-1 overflow-y-auto space-y-3 pr-2 custom-scrollbar min-h-[100px]"
          @change="onDragChange($event, stage.id)"
          ghost-class="opacity-50"
          :move="checkMove"
        >
          <template #item="{ element: card }">
            <div
              @click="openCardDetail(card.id)"
              class="bg-slate-800 p-4 rounded-xl border border-slate-700 shadow-sm transition-colors group relative"
              :class="[
                card.status === 'running' || card.status === 'pending'
                  ? 'cursor-not-allowed border-emerald-500/50 shadow-[0_0_10px_rgba(16,185,129,0.1)]'
                  : 'cursor-grab hover:border-emerald-500/50'
              ]"
            >
              <!-- Card Menu Button -->
              <div class="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  @click.stop="openMenuCardId = openMenuCardId === card.id ? null : card.id"
                  class="text-slate-500 hover:text-slate-300 p-0.5"
                >
                  <MoreVertical class="w-4 h-4" />
                </button>
                <!-- Dropdown Menu -->
                <div v-if="openMenuCardId === card.id" @click.stop class="absolute right-0 mt-1 w-36 bg-slate-700 rounded-lg border border-slate-600 shadow-xl z-10 py-1">
                  <button
                    @click.stop="handleTrigger(card.id)"
                    class="w-full flex items-center gap-2 px-3 py-2 text-xs text-slate-200 hover:bg-slate-600 transition-colors"
                    :class="{ 'opacity-50 cursor-not-allowed': card.status === 'running' }"
                    :disabled="card.status === 'running'"
                  >
                    <Zap class="w-3.5 h-3.5 text-amber-400" /> 手動觸發
                  </button>
                  <button
                    @click.stop="requestDeleteCard(card.id)"
                    class="w-full flex items-center gap-2 px-3 py-2 text-xs text-red-400 hover:bg-slate-600 transition-colors"
                    :class="{ 'opacity-50 cursor-not-allowed': card.status === 'running' }"
                    :disabled="card.status === 'running'"
                  >
                    <Trash2 class="w-3.5 h-3.5" /> 刪除卡片
                  </button>
                </div>
              </div>

              <div class="flex gap-2 mb-3">
                <span class="bg-blue-500/10 border border-blue-500/20 text-blue-400 text-[10px] font-bold px-2 py-0.5 rounded-md uppercase tracking-wider">C-{{ card.id }}</span>
                <span v-if="card.status !== 'idle'" class="text-[10px] font-bold px-2 py-0.5 rounded-md uppercase tracking-wider border"
                  :class="{
                    'bg-emerald-500/10 border-emerald-500/20 text-emerald-400': card.status === 'running',
                    'bg-amber-500/10 border-amber-500/20 text-amber-400': card.status === 'pending',
                    'bg-green-500/10 border-green-500/20 text-green-400': card.status === 'completed',
                    'bg-red-500/10 border-red-500/20 text-red-400': card.status === 'failed',
                  }"
                >{{ card.status }}</span>
              </div>

              <h4 class="text-sm font-medium text-slate-100 group-hover:text-emerald-400 transition-colors pr-6">{{ card.title }}</h4>

              <!-- AI Execution Indicator -->
              <div v-if="card.status === 'pending' || card.status === 'running'" class="mt-4 bg-slate-900/50 rounded-lg p-2.5 flex items-center justify-between border border-slate-700/50">
                <div class="flex items-center gap-2">
                  <div class="w-5 h-5 rounded-full bg-emerald-500/20 flex items-center justify-center border border-emerald-500/30">
                    <div class="w-1.5 h-1.5 rounded-full bg-emerald-400" :class="{'animate-pulse': card.status === 'running'}"></div>
                  </div>
                  <span class="text-[10px] text-slate-400 font-medium font-mono truncate">
                    {{ card.status === 'running' ? '執行中...' : '等待 AI 執行緒...' }}
                  </span>
                </div>
                <span v-if="card.status === 'running' && elapsedTimers.get(card.id)" class="text-[10px] text-emerald-400 font-mono mr-1">
                  {{ elapsedTimers.get(card.id) }}
                </span>
                <button v-if="card.status === 'running'" @click.stop="handleAbort(card.id)" class="text-red-400 hover:text-red-300" title="中止任務">
                  <Square class="w-3 h-3" />
                </button>
              </div>
            </div>
          </template>
        </draggable>
      </div>
    </div>
  </div>

  <!-- Card Detail Modal -->
  <div v-if="selectedCard" class="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50">
    <div class="bg-slate-800 border border-slate-700 rounded-2xl w-full max-w-5xl h-[80vh] flex flex-col shadow-2xl overflow-hidden">
      <!-- Header -->
      <div class="p-6 border-b border-slate-700 flex justify-between items-start bg-slate-800/80">
        <div class="flex-1 pr-6">
          <div class="flex items-center gap-3 mb-2">
            <span class="bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-bold px-2.5 py-0.5 rounded-md uppercase tracking-wider">Card-{{ selectedCard.id }}</span>
            <span class="bg-slate-700 text-slate-300 text-xs font-bold px-2.5 py-0.5 rounded-md uppercase tracking-wider">{{ selectedCard.status }}</span>
          </div>
          <input v-if="isEditingContent" v-model="selectedCard.title" type="text" class="w-full bg-slate-900 border border-slate-600 rounded-lg p-2 text-xl font-bold text-slate-100 focus:ring-2 focus:ring-emerald-500 outline-none">
          <h2 v-else class="text-xl font-bold text-slate-100 leading-snug">{{ selectedCard.title }}</h2>
        </div>
        <div class="flex items-center gap-2">
          <button
            v-if="selectedCard.status !== 'running'"
            @click="handleTrigger(selectedCard.id); fetchBoard()"
            class="text-xs px-3 py-1.5 bg-emerald-500/10 text-emerald-400 rounded-lg border border-emerald-500/30 hover:bg-emerald-500/20 transition-colors"
          >
            <Zap class="w-3.5 h-3.5 inline mr-1" />觸發執行
          </button>
          <button
            v-else
            @click="handleAbort(selectedCard.id); fetchBoard()"
            class="text-xs px-3 py-1.5 bg-red-500/10 text-red-400 rounded-lg border border-red-500/30 hover:bg-red-500/20 transition-colors"
          >
            <Square class="w-3.5 h-3.5 inline mr-1" />中止
          </button>
          <button @click="closeCardDetail" class="text-slate-400 hover:text-slate-200 transition-colors p-1 rounded-lg hover:bg-slate-700">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
        </div>
      </div>

      <!-- Body -->
      <div class="flex-1 flex overflow-hidden">
        <!-- Left: Content -->
        <div class="flex-1 border-r border-slate-700 p-6 overflow-y-auto custom-scrollbar flex flex-col">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-sm font-semibold text-slate-400 tracking-wider">AI 提示詞</h3>
            <button @click="isEditingContent = !isEditingContent" class="text-xs bg-slate-700 hover:bg-slate-600 text-slate-300 px-3 py-1.5 rounded-md transition-colors font-medium">
              {{ isEditingContent ? '取消編輯' : '編輯提示詞' }}
            </button>
          </div>

          <div v-if="isEditingContent" class="flex-1 flex flex-col gap-4">
            <div>
              <label class="block text-xs font-medium text-slate-400 mb-1">描述</label>
              <textarea v-model="selectedCard.description" rows="2" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-slate-200 text-sm font-mono focus:ring-2 focus:ring-emerald-500 outline-none custom-scrollbar"></textarea>
            </div>
            <div class="flex-1 flex flex-col">
              <label class="block text-xs font-medium text-slate-400 mb-1">Markdown 內容（上下文）</label>
              <textarea v-model="selectedCard.content" class="flex-1 w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-slate-200 text-sm font-mono focus:ring-2 focus:ring-emerald-500 outline-none custom-scrollbar resize-none"></textarea>
            </div>
          </div>
          <div v-else class="flex-1 bg-slate-900/50 border border-slate-700/50 rounded-xl p-5 overflow-y-auto custom-scrollbar prose prose-invert prose-sm max-w-none">
            <pre class="whitespace-pre-wrap font-mono text-slate-300 text-xs">{{ selectedCard.content || '尚未提供提示詞內容。' }}</pre>
          </div>
        </div>

        <!-- Right: Execution Log -->
        <div class="w-96 bg-slate-800/30 p-6 overflow-y-auto custom-scrollbar flex flex-col">
          <h3 class="text-sm font-semibold text-slate-400 tracking-wider mb-4">執行記錄</h3>
          <div v-if="isCardRunning(selectedCard.id)" class="flex-1">
            <TerminalViewer :card-id="selectedCard.id" />
          </div>
          <div v-else-if="store.taskLogs.has(selectedCard.id)" class="flex-1">
            <TerminalViewer :card-id="selectedCard.id" />
          </div>
          <div v-else class="flex-1 flex flex-col items-center justify-center gap-4">
            <div class="text-xs text-slate-500 text-center">尚無執行記錄。</div>
            <button
              v-if="selectedCard.status !== 'running' && selectedCard.status !== 'pending'"
              @click="handleTrigger(selectedCard.id)"
              class="text-xs px-3 py-1.5 bg-emerald-500/10 text-emerald-400 rounded-lg border border-emerald-500/30 hover:bg-emerald-500/20 transition-colors"
            >
              <Zap class="w-3.5 h-3.5 inline mr-1" />觸發執行
            </button>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div v-if="isEditingContent" class="p-4 border-t border-slate-700 bg-slate-800 flex justify-end gap-3">
        <button @click="isEditingContent = false" class="px-4 py-2 text-sm font-medium text-slate-400 hover:text-slate-200">取消</button>
        <button @click="saveCardDetail" class="px-5 py-2 text-sm font-medium bg-emerald-500 hover:bg-emerald-600 text-white rounded-lg transition-colors shadow-lg shadow-emerald-500/20">
          儲存變更
        </button>
      </div>
    </div>
  </div>

  <!-- New Task Modal -->
  <div v-if="showNewTaskModal" class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
    <div class="bg-slate-800 border border-slate-700 rounded-2xl p-6 w-full max-w-lg shadow-2xl">
      <h3 class="text-lg font-bold text-slate-100 mb-4">建立新任務</h3>
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-slate-400 mb-1">目標專案</label>
          <select disabled class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-500 cursor-not-allowed">
            <option>{{ projects.find(p => p.id === selectedProjectId)?.name }}</option>
          </select>
          <p class="text-[10px] text-emerald-500 mt-1">將加入待辦清單。</p>
        </div>
        <div>
          <label class="block text-sm font-medium text-slate-400 mb-1">任務標題 <span class="text-red-400">*</span></label>
          <input v-model="newTaskForm.title" type="text" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 placeholder-slate-600 focus:ring-emerald-500 focus:border-emerald-500 outline-none" placeholder="例如：實作登入 API...">
        </div>
        <div>
          <label class="block text-sm font-medium text-slate-400 mb-1">描述（選填）</label>
          <textarea v-model="newTaskForm.description" rows="3" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 placeholder-slate-600 focus:ring-emerald-500 focus:border-emerald-500 outline-none" placeholder="簡要說明任務內容..."></textarea>
        </div>
        <div class="flex justify-end gap-3 mt-6 pt-4 border-t border-slate-700">
          <button @click="showNewTaskModal = false" class="px-4 py-2 text-sm font-medium text-slate-400 hover:text-slate-200">取消</button>
          <button @click="createCard" :disabled="!newTaskForm.title" class="px-4 py-2 text-sm font-medium bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg transition-colors">
            建立任務
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- Delete Confirm -->
  <ConfirmDialog
    :show="confirmDelete"
    title="刪除卡片"
    message="確定要刪除這張卡片？此操作無法復原。"
    confirm-text="刪除"
    @confirm="confirmDeleteCard"
    @cancel="confirmDelete = false; deleteTargetCardId = null"
  />

  <!-- Assign Member Dialog -->
  <Teleport to="body">
    <div v-if="showAssignDialog" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" @click.self="showAssignDialog = false">
      <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-xs p-5 space-y-3">
        <h3 class="text-sm font-bold text-slate-200">指派成員 — {{ assigningListName }}</h3>
        <p class="text-[11px] text-slate-500">選擇負責此列表的 AI 成員，覆寫預設路由。</p>

        <div class="space-y-1.5 max-h-60 overflow-y-auto">
          <!-- 使用預設 -->
          <button
            @click="assignMember(null)"
            class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors hover:bg-slate-700/50 border border-transparent hover:border-slate-600"
          >
            <UserCircle class="w-5 h-5 text-slate-500" />
            <div>
              <div class="text-sm text-slate-300">使用預設路由</div>
              <div class="text-[10px] text-slate-500">由全域設定決定</div>
            </div>
          </button>

          <!-- 成員列表 -->
          <button
            v-for="m in allMembers"
            :key="m.id"
            @click="assignMember(m.id)"
            class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors hover:bg-slate-700/50 border border-transparent hover:border-slate-600"
          >
            <span class="text-lg w-5 text-center">{{ m.avatar || '🤖' }}</span>
            <div>
              <div class="text-sm text-slate-200">{{ m.name }}</div>
              <div class="text-[10px] text-slate-500">{{ m.role || m.provider }}</div>
            </div>
          </button>
        </div>

        <div v-if="allMembers.length === 0" class="text-center text-xs text-slate-500 py-4">
          尚未建立成員，請先到「團隊管理」建立。
        </div>

        <div class="flex justify-end pt-1">
          <button @click="showAssignDialog = false" class="px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors">取消</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: #334155;
  border-radius: 4px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: #475569;
}
</style>
