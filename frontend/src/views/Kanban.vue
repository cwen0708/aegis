<script setup lang="ts">
import { ref, inject, onMounted, onUnmounted, watch, computed, type Ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Plus, Play, Pause, Square, Clock, Trash2, Zap, MoreVertical, ChevronDown, ChevronLeft, ChevronRight, FolderOpen, Eye, UserCircle, Settings2, Bot, Hand, CheckCircle, XCircle, Archive, RotateCcw, Loader2 } from 'lucide-vue-next'
import draggable from 'vuedraggable'
import { useAegisStore } from '../stores/aegis'
import { useEscapeKey } from '../composables/useEscapeKey'
import { useResponsive } from '../composables/useResponsive'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import TerminalViewer from '../components/TerminalViewer.vue'

const { isMobile } = useResponsive()

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
useEscapeKey(showNewTaskModal, () => { showNewTaskModal.value = false })

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

async function archiveCard(cardId: number) {
  openMenuCardId.value = null
  try {
    const res = await fetch(`/api/v1/cards/${cardId}/archive`, { method: 'POST' })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    store.addToast('卡片已封存', 'success')
    await fetchBoard()
  } catch (e: any) {
    store.addToast(e.message || '封存失敗', 'error')
  }
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

// WebSocket 事件監聽：任務狀態變化時自動重整看板
function onTaskEvent(e: Event) {
  const detail = (e as CustomEvent).detail
  if (detail.type === 'started' || detail.type === 'completed' || detail.type === 'failed') {
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
useEscapeKey(showAssignDialog, () => { showAssignDialog.value = false })

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

// 切換到側邊欄專案模式（桌面版）或顯示專案下拉選單（手機版）
const showProjectDropdown = ref(false)
useEscapeKey(showProjectDropdown, () => { showProjectDropdown.value = false })

function switchToProjectsSidebar() {
  if (isMobile) {
    showProjectDropdown.value = !showProjectDropdown.value
  } else if (sidebarMode) {
    sidebarMode.value = 'projects'
  }
}

function selectProject(projectId: number) {
  selectedProjectId.value = projectId
  showProjectDropdown.value = false
  fetchBoard()
}

// 階段配置 Dialog
const showStageConfigDialog = ref(false)
const configuringStage = ref<any>(null)
const stageConfigForm = ref({
  name: '',
  stage_type: 'auto_process',
  is_ai_stage: true,
})
useEscapeKey(showStageConfigDialog, () => { showStageConfigDialog.value = false })

const stageTypeOptions = [
  { value: 'manual', label: '手動', icon: Hand, desc: '不自動執行，需手動觸發' },
  { value: 'auto_process', label: '自動執行', icon: Bot, desc: '卡片進入後自動執行 AI 任務' },
  { value: 'auto_review', label: '自動審核', icon: CheckCircle, desc: '自動執行 AI 審核/驗證' },
  { value: 'terminal', label: '終止階段', icon: XCircle, desc: '流程結束，不執行任何操作' },
]

function openStageConfigDialog(stage: any) {
  configuringStage.value = stage
  stageConfigForm.value = {
    name: stage.name || '',
    stage_type: stage.stage_type || 'auto_process',
    is_ai_stage: stage.is_ai_stage ?? true,
  }
  showStageConfigDialog.value = true
}

async function saveStageConfig() {
  if (!configuringStage.value) return
  try {
    const res = await fetch(`/api/v1/lists/${configuringStage.value.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(stageConfigForm.value),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    showStageConfigDialog.value = false
    await fetchBoard()
    store.addToast('階段配置已更新', 'success')
  } catch (e: any) {
    store.addToast(e.message || '儲存失敗', 'error')
  }
}

function getStageTypeIcon(stageType: string) {
  return stageTypeOptions.find(o => o.value === stageType)?.icon || Bot
}

// 階段排序
async function moveStage(direction: 'up' | 'down') {
  if (!configuringStage.value) return
  const stages = [...boardData.value]
  const idx = stages.findIndex(s => s.id === configuringStage.value.id)
  if (idx < 0) return
  const newIdx = direction === 'up' ? idx - 1 : idx + 1
  if (newIdx < 0 || newIdx >= stages.length) return

  // Swap positions
  ;[stages[idx], stages[newIdx]] = [stages[newIdx], stages[idx]]
  const order = stages.map(s => s.id)

  try {
    const res = await fetch('/api/v1/lists/reorder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ order }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    await fetchBoard()
    store.addToast('順序已更新', 'success')
  } catch (e: any) {
    store.addToast(e.message || '排序失敗', 'error')
  }
}

function canMoveStage(direction: 'up' | 'down'): boolean {
  if (!configuringStage.value) return false
  const idx = boardData.value.findIndex(s => s.id === configuringStage.value.id)
  if (direction === 'up') return idx > 0
  return idx < boardData.value.length - 1
}

// 封存面板
const showArchivePanel = ref(false)
const archivedCards = ref<any[]>([])
const archiveLoading = ref(false)
useEscapeKey(showArchivePanel, () => { showArchivePanel.value = false })
const unarchiveLoading = ref<number | null>(null)

async function fetchArchivedCards() {
  if (!selectedProjectId.value) return
  archiveLoading.value = true
  try {
    const res = await fetch(`/api/v1/projects/${selectedProjectId.value}/archived`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    archivedCards.value = await res.json()
  } catch {
    archivedCards.value = []
  } finally {
    archiveLoading.value = false
  }
}

function openArchivePanel() {
  showArchivePanel.value = true
  fetchArchivedCards()
}

async function unarchiveCard(cardId: number) {
  unarchiveLoading.value = cardId
  try {
    const res = await fetch(`/api/v1/cards/${cardId}/unarchive`, { method: 'POST' })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    store.addToast('卡片已恢復', 'success')
    await fetchArchivedCards()
    await fetchBoard()
  } catch (e: any) {
    store.addToast(e.message || '恢復失敗', 'error')
  } finally {
    unarchiveLoading.value = null
  }
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Sticky Header / Toolbar -->
    <div class="sticky top-0 z-10 h-14 sm:h-16 shrink-0 bg-slate-900/50 backdrop-blur-md border-b border-slate-800 px-2 sm:px-8 flex items-center justify-between gap-2 sm:gap-4">

      <!-- Left: Project Name + Runner -->
      <div class="flex items-center gap-2 sm:gap-4 min-w-0 relative">
        <!-- Project Name (click → sidebar projects mode or mobile dropdown) -->
        <button
          @click="switchToProjectsSidebar"
          class="flex items-center gap-1.5 sm:gap-2 min-w-0 group"
        >
          <FolderOpen class="w-4 sm:w-5 h-4 sm:h-5 text-emerald-400 shrink-0" />
          <span class="text-sm sm:text-lg font-bold text-slate-100 truncate group-hover:text-emerald-400 transition-colors max-w-[120px] sm:max-w-none">
            {{ currentProject?.name || '選擇專案' }}
          </span>
          <ChevronDown class="w-3 sm:w-4 h-3 sm:h-4 text-slate-500 shrink-0 transition-transform" :class="{ 'rotate-180': showProjectDropdown }" />
        </button>

        <!-- Mobile Project Dropdown -->
        <div
          v-if="showProjectDropdown && isMobile"
          class="absolute top-full left-0 mt-2 w-56 bg-slate-800 rounded-lg border border-slate-700 shadow-xl z-50 max-h-64 overflow-y-auto"
        >
          <button
            v-for="p in projects"
            :key="p.id"
            @click="selectProject(p.id)"
            class="w-full flex items-center gap-2 px-3 py-2.5 text-sm transition-colors"
            :class="selectedProjectId === p.id
              ? 'bg-emerald-500/20 text-emerald-400'
              : 'text-slate-300 hover:bg-slate-700'"
          >
            <FolderOpen class="w-4 h-4 shrink-0" :class="selectedProjectId === p.id ? 'text-emerald-400' : 'text-slate-500'" />
            <span class="truncate">{{ p.name }}</span>
          </button>
          <div v-if="projects.length === 0" class="px-3 py-4 text-sm text-slate-500 text-center">
            沒有專案
          </div>
        </div>

        <!-- Runner Controls (hide on mobile) -->
        <button
          v-if="!isMobile"
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
      <div class="flex items-center gap-1 sm:gap-2 shrink-0">
        <!-- 排程狀態群組（per-project）- hide on mobile -->
        <div v-if="!isMobile" class="flex items-center bg-slate-700/50 rounded-lg border border-slate-600/50 overflow-hidden">
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

        <!-- Archive button - icon only on mobile -->
        <button
          @click="openArchivePanel"
          class="flex items-center justify-center gap-1.5 bg-slate-700/50 hover:bg-slate-600 text-slate-300 p-2 sm:px-3 sm:py-1.5 rounded-lg text-xs font-medium transition-colors border border-slate-600/50"
          title="封存卡片"
        >
          <Archive class="w-4 h-4 sm:w-3.5 sm:h-3.5" />
          <span class="hidden sm:inline">封存</span>
        </button>

        <!-- New task button -->
        <button @click="showNewTaskModal = true" class="flex items-center justify-center gap-1.5 bg-emerald-500 hover:bg-emerald-600 text-white p-2 sm:px-3 sm:py-1.5 rounded-lg text-xs font-medium transition-colors shadow-lg shadow-emerald-500/20">
          <Plus class="w-4 h-4 sm:w-3.5 sm:h-3.5" />
          <span class="hidden sm:inline">新增任務</span>
        </button>
      </div>
    </div>

    <!-- Kanban Board -->
    <div
      class="flex gap-3 sm:gap-5 flex-1 items-start overflow-x-auto px-2 sm:px-6 py-2 sm:py-4 custom-scrollbar transition-opacity duration-300"
      :class="{'opacity-50 grayscale pointer-events-none select-none': currentProject?.is_active === false}"
    >
      <div v-for="stage in boardData" :key="stage.id" class="w-72 sm:w-80 shrink-0 bg-slate-800/40 rounded-xl p-3 sm:p-4 border border-slate-700/50 flex flex-col max-h-full">
        <div class="flex items-center justify-between mb-4 px-1">
          <h3 class="font-medium text-slate-200 flex items-center gap-2">
            <!-- Stage Type Icon -->
            <component
              :is="getStageTypeIcon(stage.stage_type)"
              class="w-4 h-4"
              :class="{
                'text-slate-500': stage.stage_type === 'manual',
                'text-emerald-400': stage.stage_type === 'auto_process',
                'text-blue-400': stage.stage_type === 'auto_review',
                'text-slate-600': stage.stage_type === 'terminal',
              }"
              :title="stageTypeOptions.find(o => o.value === stage.stage_type)?.label || '自動執行'"
            />
            {{ stage.name }}
            <span v-if="stage.cards.some((c: any) => c.status === 'running')" class="relative flex h-2 w-2 ml-1">
              <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
          </h3>
          <div class="flex items-center gap-1.5">
            <!-- Member (left) -->
            <button
              @click.stop="openAssignDialog(stage)"
              class="flex items-center justify-center w-6 h-6 rounded-full transition-colors"
              :class="stage.member ? 'bg-slate-700 hover:bg-slate-600' : 'text-slate-600 hover:text-slate-400 hover:bg-slate-700/50'"
              :title="stage.member ? `${stage.member.name} (${stage.member.provider})` : '指派成員'"
            >
              <span v-if="stage.member" class="text-xs">{{ stage.member.avatar || '🤖' }}</span>
              <UserCircle v-else class="w-4 h-4" />
            </button>
            <!-- Stage Config (right) -->
            <button
              @click.stop="openStageConfigDialog(stage)"
              class="flex items-center justify-center w-6 h-6 rounded-full text-slate-600 hover:text-slate-400 hover:bg-slate-700/50 transition-colors"
              title="階段配置"
            >
              <Settings2 class="w-3.5 h-3.5" />
            </button>
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
          :disabled="isMobile"
        >
          <template #item="{ element: card }">
            <div
              @click="openCardDetail(card.id)"
              class="bg-slate-800 p-3 sm:p-4 rounded-xl border border-slate-700 shadow-sm transition-colors group relative"
              :class="[
                card.status === 'running' || card.status === 'pending'
                  ? 'cursor-not-allowed border-emerald-500/50 shadow-[0_0_10px_rgba(16,185,129,0.1)]'
                  : isMobile ? 'cursor-pointer hover:border-emerald-500/50' : 'cursor-grab hover:border-emerald-500/50'
              ]"
            >
              <!-- Card Menu Button -->
              <div class="absolute top-3 right-3 touch-visible">
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
                    @click.stop="archiveCard(card.id)"
                    class="w-full flex items-center gap-2 px-3 py-2 text-xs text-slate-300 hover:bg-slate-600 transition-colors"
                    :class="{ 'opacity-50 cursor-not-allowed': card.status === 'running' || card.status === 'pending' }"
                    :disabled="card.status === 'running' || card.status === 'pending'"
                  >
                    <Archive class="w-3.5 h-3.5 text-slate-400" /> 封存
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

  <!-- Stage Config Dialog -->
  <Teleport to="body">
    <div v-if="showStageConfigDialog" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" @click.self="showStageConfigDialog = false">
      <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-sm p-5 space-y-4">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-bold text-slate-200">階段配置</h3>
          <div class="flex items-center gap-1">
            <button
              @click="moveStage('up')"
              :disabled="!canMoveStage('up')"
              class="p-1.5 rounded-lg transition-colors"
              :class="canMoveStage('up') ? 'text-slate-400 hover:text-slate-200 hover:bg-slate-700' : 'text-slate-600 cursor-not-allowed'"
              title="往前移"
            >
              <ChevronLeft class="w-4 h-4" />
            </button>
            <button
              @click="moveStage('down')"
              :disabled="!canMoveStage('down')"
              class="p-1.5 rounded-lg transition-colors"
              :class="canMoveStage('down') ? 'text-slate-400 hover:text-slate-200 hover:bg-slate-700' : 'text-slate-600 cursor-not-allowed'"
              title="往後移"
            >
              <ChevronRight class="w-4 h-4" />
            </button>
          </div>
        </div>

        <!-- Name -->
        <div class="space-y-1.5">
          <label class="block text-xs font-medium text-slate-400">階段名稱</label>
          <input
            v-model="stageConfigForm.name"
            type="text"
            class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 text-sm"
            placeholder="階段名稱"
          />
        </div>

        <!-- Stage Type -->
        <div class="space-y-2">
          <label class="block text-xs font-medium text-slate-400">階段類型</label>
          <div class="space-y-1.5">
            <button
              v-for="opt in stageTypeOptions"
              :key="opt.value"
              @click="stageConfigForm.stage_type = opt.value"
              class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors border"
              :class="stageConfigForm.stage_type === opt.value
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                : 'border-transparent hover:bg-slate-700/50 hover:border-slate-600 text-slate-300'"
            >
              <component :is="opt.icon" class="w-4 h-4" />
              <div class="flex-1">
                <div class="text-sm font-medium">{{ opt.label }}</div>
                <div class="text-[10px] text-slate-500">{{ opt.desc }}</div>
              </div>
            </button>
          </div>
        </div>

        <!-- Is AI Stage -->
        <div class="flex items-center justify-between py-2 px-1">
          <div>
            <div class="text-sm text-slate-200">AI 處理階段</div>
            <div class="text-[10px] text-slate-500">關閉後不會自動分派給 AI 成員</div>
          </div>
          <button
            @click="stageConfigForm.is_ai_stage = !stageConfigForm.is_ai_stage"
            class="relative w-10 h-5 rounded-full transition-colors"
            :class="stageConfigForm.is_ai_stage ? 'bg-emerald-500' : 'bg-slate-600'"
          >
            <span
              class="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform"
              :class="stageConfigForm.is_ai_stage ? 'left-5' : 'left-0.5'"
            />
          </button>
        </div>

        <!-- Actions -->
        <div class="flex justify-end gap-2 pt-2 border-t border-slate-700">
          <button @click="showStageConfigDialog = false" class="px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors">取消</button>
          <button @click="saveStageConfig" class="px-4 py-1.5 text-xs bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg transition-colors">儲存</button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- Archive Panel -->
  <Teleport to="body">
    <div v-if="showArchivePanel" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" @click.self="showArchivePanel = false">
      <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-lg max-h-[70vh] flex flex-col">
        <!-- Header -->
        <div class="flex items-center justify-between p-5 border-b border-slate-700">
          <div class="flex items-center gap-3">
            <Archive class="w-5 h-5 text-slate-400" />
            <h3 class="text-sm font-bold text-slate-200">封存卡片</h3>
          </div>
          <button @click="showArchivePanel = false" class="text-slate-400 hover:text-slate-200 p-1 rounded-lg hover:bg-slate-700">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
        </div>

        <!-- Content -->
        <div class="flex-1 overflow-y-auto p-4 custom-scrollbar">
          <!-- Loading -->
          <div v-if="archiveLoading" class="flex items-center justify-center py-8 text-slate-500">
            <Loader2 class="w-5 h-5 animate-spin mr-2" />
            載入中...
          </div>

          <!-- Empty -->
          <div v-else-if="archivedCards.length === 0" class="text-center py-12 text-slate-500">
            <Archive class="w-10 h-10 mx-auto mb-3 opacity-30" />
            <p class="text-sm">沒有封存的卡片</p>
          </div>

          <!-- Card List -->
          <div v-else class="space-y-2">
            <div
              v-for="card in archivedCards"
              :key="card.id"
              class="flex items-center justify-between p-3 bg-slate-900/50 rounded-lg border border-slate-700/50"
            >
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2 mb-0.5">
                  <span class="text-[10px] font-bold text-blue-400 bg-blue-500/10 px-1.5 py-0.5 rounded">C-{{ card.id }}</span>
                  <span
                    class="text-[10px] font-bold px-1.5 py-0.5 rounded"
                    :class="{
                      'bg-green-500/10 text-green-400': card.status === 'completed',
                      'bg-red-500/10 text-red-400': card.status === 'failed',
                      'bg-slate-500/10 text-slate-400': card.status === 'idle',
                    }"
                  >{{ card.status }}</span>
                </div>
                <div class="text-sm text-slate-200 truncate">{{ card.title }}</div>
              </div>
              <button
                @click="unarchiveCard(card.id)"
                :disabled="unarchiveLoading !== null"
                class="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 rounded-lg text-xs font-medium transition-colors disabled:opacity-50 ml-3"
              >
                <Loader2 v-if="unarchiveLoading === card.id" class="w-3 h-3 animate-spin" />
                <RotateCcw v-else class="w-3 h-3" />
                恢復
              </button>
            </div>
          </div>
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
/* Use global .custom-scrollbar and .touch-visible from style.css */
</style>
