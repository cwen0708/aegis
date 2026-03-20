<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { Plus, Play, Pause, Square, Trash2, Zap, MoreVertical, ChevronLeft, ChevronRight, FolderOpen, ListTodo, UserCircle, Settings2, Bot, Hand, Archive, RotateCcw, Loader2, Lock } from 'lucide-vue-next'
import draggable from 'vuedraggable'
import { useAegisStore } from '../stores/aegis'
import { useAuthStore } from '../stores/auth'
import { apiClient } from '../services/api/client'
import { useEscapeKey } from '../composables/useEscapeKey'
import { useResponsive } from '../composables/useResponsive'
import { useProjectSelector } from '../composables/useProjectSelector'
import PageHeader from '../components/PageHeader.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import CardDetailDialog from '../components/CardDetailDialog.vue'

const { isMobile } = useResponsive()

const store = useAegisStore()
const auth = useAuthStore()

// 全域專案選擇（共用 composable）
const { projects, selectedProjectId, currentProject } = useProjectSelector()

// 資料狀態
const boardData = ref<any[]>([])

// Modal 狀態
const showNewTaskModal = ref(false)
const newTaskForm = ref({ title: '', description: '', list_id: null as number | null })
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
const fetchBoard = async () => {
  if (!selectedProjectId.value) return
  boardData.value = await apiClient.get(`/api/v1/projects/${selectedProjectId.value}/board`)
}

const createCard = async () => {
  if (!newTaskForm.value.title || boardData.value.length === 0) return
  const listId = newTaskForm.value.list_id || boardData.value[0].id
  await apiClient.post('/api/v1/cards/', { list_id: listId, title: newTaskForm.value.title, description: newTaskForm.value.description })
  await fetchBoard()
  showNewTaskModal.value = false
  newTaskForm.value = { title: '', description: '', list_id: null }
}

// 卡片詳情 Modal
const selectedCard = ref<any>(null)

const openCardDetail = async (cardId: number) => {
  openMenuCardId.value = null
  selectedCard.value = await apiClient.get(`/api/v1/cards/${cardId}`)
}

const closeCardDetail = () => { selectedCard.value = null }

const saveCardDetail = async (card: any) => {
  if (!card) return
  await apiClient.patch(`/api/v1/cards/${card.id}`, {
    title: card.title,
    description: card.description,
    content: card.content
  })
  await fetchBoard()
}

// 拖曳
const onDragChange = async (event: any, targetListId: number) => {
  if (event.added) {
    const cardId = event.added.element.id
    try {
      await apiClient.patch(`/api/v1/cards/${cardId}`, { list_id: targetListId })
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
    await apiClient.post(`/api/v1/cards/${cardId}/archive`)
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

onMounted(() => {
  // 確保初始載入：selectedProjectId 可能在 mount 前已有值（全域 singleton）
  if (selectedProjectId.value) fetchBoard()
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
    allMembers.value = await apiClient.get('/api/v1/members')
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
    await apiClient.patch(`/api/v1/lists/${assigningListId.value}`, { member_id: memberId })
    showAssignDialog.value = false
    await fetchBoard()
  } catch (e: any) {
    store.addToast(e.message || '指派失敗', 'error')
  }
}

// 手機版：Trello 風格單列顯示
const mobileStageIndex = ref(0)
const currentMobileStage = computed(() => boardData.value[mobileStageIndex.value] || null)

// 當 boardData 改變時，確保 index 不超出範圍
watch(boardData, (newData) => {
  if (mobileStageIndex.value >= newData.length) {
    mobileStageIndex.value = Math.max(0, newData.length - 1)
  }
})

function goToStage(index: number) {
  if (index >= 0 && index < boardData.value.length) {
    mobileStageIndex.value = index
  }
}

function prevStage() {
  if (mobileStageIndex.value > 0) {
    mobileStageIndex.value--
  }
}

function nextStage() {
  if (mobileStageIndex.value < boardData.value.length - 1) {
    mobileStageIndex.value++
  }
}

// 手機版：滑動手勢支援
const touchStartX = ref(0)
const touchEndX = ref(0)
const isSwiping = ref(false)

function onTouchStart(e: TouchEvent) {
  const touch = e.touches[0]
  if (touch) {
    touchStartX.value = touch.clientX
    touchEndX.value = touch.clientX
    isSwiping.value = true
  }
}

function onTouchMove(e: TouchEvent) {
  if (!isSwiping.value) return
  const touch = e.touches[0]
  if (touch) {
    touchEndX.value = touch.clientX
  }
}

function onTouchEnd() {
  if (!isSwiping.value) return
  isSwiping.value = false

  const diff = touchStartX.value - touchEndX.value
  const threshold = 50 // 最小滑動距離

  if (Math.abs(diff) < threshold) return

  if (diff > 0) {
    // 向左滑 → 下一個
    nextStage()
  } else {
    // 向右滑 → 上一個
    prevStage()
  }
}

// 階段配置 Dialog
const showStageConfigDialog = ref(false)
const configuringStage = ref<any>(null)
const stageConfigForm = ref({
  name: '',
  description: '',
  is_ai_stage: true,
  on_success_action: 'none',
  on_fail_action: 'none',
})

useEscapeKey(showStageConfigDialog, () => { showStageConfigDialog.value = false })

function openStageConfigDialog(stage: any) {
  configuringStage.value = stage
  stageConfigForm.value = {
    name: stage.name || '',
    description: stage.description || '',
    is_ai_stage: stage.is_ai_stage ?? true,
    on_success_action: stage.on_success_action || 'none',
    on_fail_action: stage.on_fail_action || 'none',
  }
  showStageConfigDialog.value = true
}

// 取得可用的動作選項（含「移到某列表」）
function getActionOptions(excludeListId?: number) {
  const opts = [
    { value: 'none', label: '不動作' },
    { value: 'archive', label: '封存' },
    { value: 'delete', label: '刪除' },
  ]
  for (const stage of boardData.value) {
    if (stage.id !== excludeListId) {
      opts.push({ value: `move_to:${stage.id}`, label: `移到「${stage.name}」` })
    }
  }
  return opts
}

async function saveStageConfig() {
  if (!configuringStage.value) return
  try {
    await apiClient.patch(`/api/v1/lists/${configuringStage.value.id}`, stageConfigForm.value)
    showStageConfigDialog.value = false
    await fetchBoard()
    store.addToast('階段配置已更新', 'success')
  } catch (e: any) {
    store.addToast(e.message || '儲存失敗', 'error')
  }
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
    await apiClient.post('/api/v1/lists/reorder', { order })
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
    archivedCards.value = await apiClient.get(`/api/v1/projects/${selectedProjectId.value}/archived`)
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
    await apiClient.post(`/api/v1/cards/${cardId}/unarchive`)
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
    <!-- Header -->
    <PageHeader :icon="ListTodo">
      <!-- Runner Controls (hide on mobile) -->
      <button
        v-if="!isMobile && auth.isAuthenticated"
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

      <!-- Archive button -->
      <button
        v-if="auth.isAuthenticated"
        @click="openArchivePanel"
        class="flex items-center justify-center gap-1.5 bg-slate-700/50 hover:bg-slate-600 text-slate-300 p-2 sm:px-3 sm:py-1.5 rounded-lg text-xs font-medium transition-colors border border-slate-600/50"
        title="封存卡片"
      >
        <Archive class="w-4 h-4 sm:w-3.5 sm:h-3.5" />
        <span class="hidden sm:inline">封存</span>
      </button>

      <!-- New task button -->
      <button v-if="auth.isAuthenticated" @click="showNewTaskModal = true" class="flex items-center justify-center gap-1.5 bg-emerald-500 hover:bg-emerald-600 text-white p-2 sm:px-3 sm:py-1.5 rounded-lg text-xs font-medium transition-colors shadow-lg shadow-emerald-500/20">
        <Plus class="w-4 h-4 sm:w-3.5 sm:h-3.5" />
        <span class="hidden sm:inline">新增任務</span>
      </button>
    </PageHeader>

    <!-- Mobile Stage Navigator -->
    <div v-if="isMobile && boardData.length > 0" class="shrink-0 bg-slate-900/50 border-b border-slate-800 px-2 py-2">
      <div class="flex items-center justify-between gap-2">
        <!-- Prev Button -->
        <button
          @click="prevStage"
          :disabled="mobileStageIndex === 0"
          class="p-2 rounded-lg transition-colors"
          :class="mobileStageIndex === 0 ? 'text-slate-700' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'"
        >
          <ChevronLeft class="w-5 h-5" />
        </button>

        <!-- Stage Dots -->
        <div class="flex-1 flex items-center justify-center gap-1.5 overflow-x-auto">
          <button
            v-for="(stage, idx) in boardData"
            :key="stage.id"
            @click="goToStage(idx)"
            class="flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium transition-all"
            :class="idx === mobileStageIndex
              ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
              : 'text-slate-500 hover:text-slate-300'"
          >
            <span class="w-1.5 h-1.5 rounded-full" :class="idx === mobileStageIndex ? 'bg-emerald-400' : 'bg-slate-600'"></span>
            <span class="truncate max-w-[60px]">{{ stage.name }}</span>
            <span v-if="stage.cards.length > 0" class="text-[10px] opacity-70">({{ stage.cards.length }})</span>
          </button>
        </div>

        <!-- Next Button -->
        <button
          @click="nextStage"
          :disabled="mobileStageIndex >= boardData.length - 1"
          class="p-2 rounded-lg transition-colors"
          :class="mobileStageIndex >= boardData.length - 1 ? 'text-slate-700' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'"
        >
          <ChevronRight class="w-5 h-5" />
        </button>
      </div>
    </div>

    <!-- Kanban Board -->
    <!-- Desktop: Show all columns -->
    <div
      v-if="!isMobile"
      class="flex gap-5 flex-1 items-start overflow-x-auto px-6 py-4 custom-scrollbar transition-opacity duration-300"
      :class="{'opacity-50 grayscale pointer-events-none select-none': currentProject()?.is_active === false}"
    >
      <div v-for="stage in boardData" :key="stage.id" class="w-80 shrink-0 bg-slate-800/40 rounded-xl p-4 border border-slate-700/50 flex flex-col max-h-full">
        <div class="flex items-center justify-between mb-4 px-1">
          <h3 class="font-medium text-slate-200 flex items-center gap-2">
            <!-- AI Stage Icon -->
            <component
              :is="stage.is_ai_stage ? Bot : Hand"
              class="w-4 h-4"
              :class="stage.is_ai_stage ? 'text-emerald-400' : 'text-slate-500'"
              :title="stage.is_ai_stage ? 'AI 自動處理' : '手動處理'"
            />
            {{ stage.name }}
            <span v-if="stage.cards.some((c: any) => c.status === 'running')" class="relative flex h-2 w-2 ml-1">
              <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
          </h3>
          <div class="flex items-center gap-1.5">
            <!-- Member (left) -->
            <Lock v-if="stage.is_member_bound" class="w-3 h-3 text-amber-400/60" title="成員綁定" />
            <button
              v-if="!stage.is_member_bound"
              @click.stop="openAssignDialog(stage)"
              class="flex items-center justify-center w-6 h-6 rounded-full transition-colors"
              :class="stage.member ? 'bg-slate-700 hover:bg-slate-600' : 'text-slate-600 hover:text-slate-400 hover:bg-slate-700/50'"
              :title="stage.member ? `${stage.member.name} (${stage.member.provider})` : '指派成員'"
            >
              <span v-if="stage.member" class="text-xs">{{ stage.member.avatar || '🤖' }}</span>
              <UserCircle v-else class="w-4 h-4" />
            </button>
            <span
              v-else-if="stage.member"
              class="flex items-center justify-center w-6 h-6 rounded-full bg-slate-700"
              :title="`${stage.member.name}（綁定）`"
            >
              <span class="text-xs">{{ stage.member.avatar || '🤖' }}</span>
            </span>
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
        <div v-if="stage.description" class="text-[10px] text-slate-500 px-1 -mt-2 mb-3 truncate" :title="stage.description">
          {{ stage.description }}
        </div>

        <draggable
          v-model="stage.cards"
          group="cards"
          item-key="id"
          class="flex-1 overflow-y-auto space-y-3 pr-2 custom-scrollbar min-h-[100px]"
          @change="onDragChange($event, stage.id)"
          ghost-class="opacity-50"
          :move="checkMove"
          :disabled="!auth.isAuthenticated"
        >
          <template #item="{ element: card }">
            <div
              @click="openCardDetail(card.id)"
              class="bg-slate-800 p-4 rounded-xl border border-slate-700 shadow-sm transition-colors group relative cursor-grab hover:border-emerald-500/50"
              :class="[
                card.status === 'running' || card.status === 'pending'
                  ? 'cursor-not-allowed border-emerald-500/50 shadow-[0_0_10px_rgba(16,185,129,0.1)]'
                  : ''
              ]"
            >
              <!-- Card Menu Button -->
              <div v-if="auth.isAuthenticated" class="absolute top-3 right-3 touch-visible">
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
                <button v-if="card.status === 'running' && auth.isAuthenticated" @click.stop="handleAbort(card.id)" class="text-red-400 hover:text-red-300" title="中止任務">
                  <Square class="w-3 h-3" />
                </button>
              </div>
            </div>
          </template>
        </draggable>
      </div>

    </div>

    <!-- Mobile: Single column view (Trello style) -->
    <div
      v-else-if="currentMobileStage"
      class="flex-1 flex flex-col overflow-hidden px-2 py-2 transition-opacity duration-300"
      :class="{'opacity-50 grayscale pointer-events-none select-none': currentProject()?.is_active === false}"
      @touchstart="onTouchStart"
      @touchmove="onTouchMove"
      @touchend="onTouchEnd"
    >
      <!-- Stage Header -->
      <div class="flex items-center justify-between mb-3 px-1">
        <h3 class="font-medium text-slate-200 flex items-center gap-2">
          <component
            :is="currentMobileStage.is_ai_stage ? Bot : Hand"
            class="w-4 h-4"
            :class="currentMobileStage.is_ai_stage ? 'text-emerald-400' : 'text-slate-500'"
          />
          {{ currentMobileStage.name }}
          <span class="text-xs text-slate-500">({{ currentMobileStage.cards.length }})</span>
          <span v-if="currentMobileStage.cards.some((c: any) => c.status === 'running')" class="relative flex h-2 w-2 ml-1">
            <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
          </span>
        </h3>
        <div class="flex items-center gap-1.5">
          <button
            @click.stop="openAssignDialog(currentMobileStage)"
            class="flex items-center justify-center w-7 h-7 rounded-full transition-colors"
            :class="currentMobileStage.member ? 'bg-slate-700 hover:bg-slate-600' : 'text-slate-600 hover:text-slate-400 hover:bg-slate-700/50'"
          >
            <span v-if="currentMobileStage.member" class="text-sm">{{ currentMobileStage.member.avatar || '🤖' }}</span>
            <UserCircle v-else class="w-4 h-4" />
          </button>
          <button
            @click.stop="openStageConfigDialog(currentMobileStage)"
            class="flex items-center justify-center w-7 h-7 rounded-full text-slate-600 hover:text-slate-400 hover:bg-slate-700/50 transition-colors"
          >
            <Settings2 class="w-4 h-4" />
          </button>
        </div>
      </div>
      <div v-if="currentMobileStage.description" class="text-[10px] text-slate-500 px-4 -mt-1 mb-2 truncate">
        {{ currentMobileStage.description }}
      </div>

      <!-- Cards List -->
      <div class="flex-1 overflow-y-auto space-y-2 custom-scrollbar">
        <div
          v-for="card in currentMobileStage.cards"
          :key="card.id"
          @click="openCardDetail(card.id)"
          class="bg-slate-800 p-3 rounded-xl border border-slate-700 shadow-sm transition-colors group relative cursor-pointer active:bg-slate-750"
          :class="[
            card.status === 'running' || card.status === 'pending'
              ? 'border-emerald-500/50 shadow-[0_0_10px_rgba(16,185,129,0.1)]'
              : 'hover:border-emerald-500/50'
          ]"
        >
          <!-- Card Menu Button -->
          <div class="absolute top-3 right-3">
            <button
              @click.stop="openMenuCardId = openMenuCardId === card.id ? null : card.id"
              class="text-slate-500 hover:text-slate-300 p-1"
            >
              <MoreVertical class="w-4 h-4" />
            </button>
            <!-- Dropdown Menu -->
            <div v-if="openMenuCardId === card.id" @click.stop class="absolute right-0 mt-1 w-36 bg-slate-700 rounded-lg border border-slate-600 shadow-xl z-10 py-1">
              <button
                @click.stop="handleTrigger(card.id)"
                class="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-slate-200 hover:bg-slate-600 transition-colors"
                :class="{ 'opacity-50 cursor-not-allowed': card.status === 'running' }"
                :disabled="card.status === 'running'"
              >
                <Zap class="w-4 h-4 text-amber-400" /> 手動觸發
              </button>
              <button
                @click.stop="archiveCard(card.id)"
                class="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-slate-300 hover:bg-slate-600 transition-colors"
                :class="{ 'opacity-50 cursor-not-allowed': card.status === 'running' || card.status === 'pending' }"
                :disabled="card.status === 'running' || card.status === 'pending'"
              >
                <Archive class="w-4 h-4 text-slate-400" /> 封存
              </button>
              <button
                @click.stop="requestDeleteCard(card.id)"
                class="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-red-400 hover:bg-slate-600 transition-colors"
                :class="{ 'opacity-50 cursor-not-allowed': card.status === 'running' }"
                :disabled="card.status === 'running'"
              >
                <Trash2 class="w-4 h-4" /> 刪除卡片
              </button>
            </div>
          </div>

          <div class="flex gap-2 mb-2">
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

          <h4 class="text-sm font-medium text-slate-100 pr-8">{{ card.title }}</h4>

          <!-- AI Execution Indicator -->
          <div v-if="card.status === 'pending' || card.status === 'running'" class="mt-3 bg-slate-900/50 rounded-lg p-2 flex items-center justify-between border border-slate-700/50">
            <div class="flex items-center gap-2">
              <div class="w-4 h-4 rounded-full bg-emerald-500/20 flex items-center justify-center border border-emerald-500/30">
                <div class="w-1 h-1 rounded-full bg-emerald-400" :class="{'animate-pulse': card.status === 'running'}"></div>
              </div>
              <span class="text-[10px] text-slate-400 font-medium font-mono">
                {{ card.status === 'running' ? '執行中...' : '等待中...' }}
              </span>
            </div>
            <span v-if="card.status === 'running' && elapsedTimers.get(card.id)" class="text-[10px] text-emerald-400 font-mono mr-1">
              {{ elapsedTimers.get(card.id) }}
            </span>
            <button v-if="card.status === 'running'" @click.stop="handleAbort(card.id)" class="text-red-400 hover:text-red-300 p-1" title="中止任務">
              <Square class="w-3 h-3" />
            </button>
          </div>
        </div>

        <!-- Empty State -->
        <div v-if="currentMobileStage.cards.length === 0" class="flex flex-col items-center justify-center py-12 text-slate-500">
          <div class="w-12 h-12 rounded-full bg-slate-800 flex items-center justify-center mb-3">
            <FolderOpen class="w-6 h-6" />
          </div>
          <p class="text-sm">此階段沒有卡片</p>
        </div>
      </div>
    </div>

    <!-- No stages fallback -->
    <div v-else-if="isMobile && boardData.length === 0" class="flex-1 flex items-center justify-center">
      <p class="text-slate-500 text-sm">尚未建立任何階段</p>
    </div>
  </div>

  <!-- Card Detail Modal -->
  <CardDetailDialog
    v-if="selectedCard"
    :card="selectedCard"
    :is-running="isCardRunning(selectedCard.id)"
    @close="closeCardDetail"
    @save="saveCardDetail"
    @trigger="(id) => { handleTrigger(id); fetchBoard() }"
    @abort="(id) => { handleAbort(id); fetchBoard() }"
  />

  <!-- New Task Modal -->
  <div v-if="showNewTaskModal" class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
    <div class="bg-slate-800 border border-slate-700 rounded-2xl p-6 w-full max-w-lg shadow-2xl">
      <h3 class="text-lg font-bold text-slate-100 mb-4">建立新任務</h3>
      <div class="space-y-4">
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-sm font-medium text-slate-400 mb-1">目標專案</label>
            <select disabled class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-500 cursor-not-allowed text-sm">
              <option>{{ projects.find(p => p.id === selectedProjectId)?.name }}</option>
            </select>
          </div>
          <div>
            <label class="block text-sm font-medium text-slate-400 mb-1">目標列表</label>
            <select
              v-model="newTaskForm.list_id"
              class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-emerald-500 focus:border-emerald-500 outline-none text-sm"
            >
              <option :value="null">{{ boardData[0]?.name || '第一個列表' }}（預設）</option>
              <option v-for="stage in boardData" :key="stage.id" :value="stage.id">{{ stage.name }}</option>
            </select>
          </div>
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

        <!-- Description -->
        <div class="space-y-1.5">
          <label class="block text-xs font-medium text-slate-400">階段說明</label>
          <input
            v-model="stageConfigForm.description"
            type="text"
            class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 text-sm"
            placeholder="例：AI 自動審查程式碼品質"
          />
        </div>

        <!-- AI 處理開關 -->
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

        <!-- On Success Action -->
        <div class="space-y-1.5">
          <label class="block text-xs font-medium text-slate-400">成功後動作</label>
          <select
            v-model="stageConfigForm.on_success_action"
            class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 text-sm"
          >
            <option v-for="opt in getActionOptions(configuringStage?.id)" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
        </div>

        <!-- On Fail Action -->
        <div class="space-y-1.5">
          <label class="block text-xs font-medium text-slate-400">失敗後動作</label>
          <select
            v-model="stageConfigForm.on_fail_action"
            class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 text-sm"
          >
            <option v-for="opt in getActionOptions(configuringStage?.id)" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
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
