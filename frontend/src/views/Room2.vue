<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useAegisStore } from '../stores/aegis'
import { apiClient } from '../services/api/client'
import { assetUrl } from '../config'
import CharacterDialog from '../components/CharacterDialog.vue'
import Room2Editor from '../components/Room2Editor.vue'
import type Phaser from 'phaser'
import type Room2Scene from '../game2/Room2Scene'

const route = useRoute()
const store = useAegisStore()

const canvasRef = ref<HTMLDivElement>()
const error = ref('')
const isEditing = ref(false)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const customMapJson = ref<Record<string, any> | null>(null)
let game: Phaser.Game | null = null

// ===== Room support =====
const currentRoomId = computed(() => {
  const id = route.params.roomId as string | undefined
  return id || null
})

// ===== 成員資料 =====
interface MemberInfo {
  id: number
  name: string
  avatar: string
  provider: string
  role?: string
  portrait?: string
  sprite_index?: number
  sprite_sheet?: string
  sprite_scale?: number
}

const members = ref<MemberInfo[]>([])
let pollId: number

async function fetchMembers() {
  try {
    let all = await apiClient.get<any[]>('/api/v1/members')
    const rid = currentRoomId.value
    if (rid) {
      try {
        const roomData = await apiClient.get<any>(`/api/v1/rooms/${rid}`)
        const memberIds = roomData.member_ids || []
        if (memberIds.length > 0) {
          const allowed = new Set(memberIds)
          all = all.filter((m: any) => allowed.has(m.id))
        }
      } catch { /* use all members */ }
    }
    members.value = all
  } catch {}
}

// ===== 工作台 / 休息 =====
const totalDesks = computed(() => store.systemInfo.workstations_total)

const busyMemberMap = computed(() => {
  const map = new Map<number, { card_title: string; project: string; provider: string }>()
  for (const t of store.runningTasks) {
    const mid = (t as any).member_id
    if (mid) {
      map.set(mid, { card_title: t.card_title, project: t.project, provider: t.provider })
    }
  }
  return map
})

const deskAssignments = computed(() => {
  const desks: Array<{ member: MemberInfo; task: { card_title: string; project: string; provider: string } } | null> = []
  const busy = busyMemberMap.value
  for (const m of members.value) {
    if (busy.has(m.id) && desks.length < totalDesks.value) {
      desks.push({ member: m, task: busy.get(m.id)! })
    }
  }
  while (desks.length < totalDesks.value) {
    desks.push(null)
  }
  return desks
})

const restingMembers = computed(() => {
  const busy = busyMemberMap.value
  return members.value.filter(m => !busy.has(m.id))
})

// ===== 對話泡泡 =====
const IDLE_BUBBLES = [
  '休息一下～', '等待任務中...', '喝杯咖啡', '隨時待命！',
  '整理思緒中', '充電完畢！', '看看有什麼新任務', '今天也要加油',
]
const WORK_BUBBLES = [
  '專注模式！', '程式碼寫起來！', '分析中...', '快完成了', '全力輸出！', '進度推進中',
]

const bubbles = ref<Map<number, string>>(new Map())

function randomBubble(memberId: number, isWorking: boolean) {
  const list = isWorking ? WORK_BUBBLES : IDLE_BUBBLES
  const text = list[Math.floor(Math.random() * list.length)]!
  bubbles.value.set(memberId, text)
  setTimeout(() => { bubbles.value.delete(memberId) }, 4000)
}

let bubbleInterval: number

// ===== Phaser Game =====
function getScene(): Room2Scene | null {
  if (!game) return null
  return game.scene.getScene('room2') as Room2Scene | null
}

function pushDataToScene() {
  const scene = getScene()
  if (!scene?.updateData) return

  scene.updateData({
    totalDesks: totalDesks.value,
    desks: deskAssignments.value.map(d => d ? {
      member: {
        id: d.member.id, name: d.member.name, provider: d.member.provider,
        sprite_index: d.member.sprite_index ?? 0,
        sprite_sheet: d.member.sprite_sheet,
        sprite_scale: d.member.sprite_scale,
      },
      task: { card_title: d.task.card_title, project: d.task.project },
    } : null),
    resting: restingMembers.value.map(m => ({
      id: m.id, name: m.name, provider: m.provider,
      sprite_index: m.sprite_index ?? 0,
      sprite_sheet: m.sprite_sheet,
      sprite_scale: m.sprite_scale,
    })),
    bubbles: bubbles.value,
    used: store.systemInfo.workstations_used,
    total: store.systemInfo.workstations_total,
    memberCount: members.value.length,
  })
}

// ===== Character Dialog (AVG) =====
interface CharacterInfo {
  memberId: number
  name: string
  provider: string
  role?: string
  portrait?: string
}
const showCharacterDialog = ref(false)
const selectedCharacter = ref<CharacterInfo | null>(null)

function onMemberDialoguePopup(e: Event) {
  const detail = (e as CustomEvent).detail
  if (!detail.member_id) return
  if (detail.dialogue_type !== 'task_complete' && detail.dialogue_type !== 'task_failed') return
  if (showCharacterDialog.value && selectedCharacter.value?.memberId !== detail.member_id) return

  const member = members.value.find(m => m.id === detail.member_id)
  if (!member) return

  selectedCharacter.value = {
    memberId: member.id,
    name: member.name,
    provider: member.provider,
    role: member.role || (member.provider === 'claude' ? 'Claude 開發者' : '開發者'),
    portrait: member.portrait || '',
  }
  showCharacterDialog.value = true
}

function setupCharacterClickListener() {
  const scene = getScene()
  if (!scene) return
  scene.events.on('character-clicked', (data: CharacterInfo) => {
    const member = members.value.find(m => m.id === data.memberId)
    selectedCharacter.value = {
      ...data,
      role: member?.role || (member?.provider === 'claude' ? 'Claude 開發者' : member?.provider === 'gemini' ? 'Gemini 開發者' : '開發者'),
      portrait: member?.portrait || '',
    }
    showCharacterDialog.value = true
  })
}

function closeCharacterDialog() {
  showCharacterDialog.value = false
  selectedCharacter.value = null
}

async function loadRoomMap() {
  const rid = currentRoomId.value
  if (!rid) return
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const roomData = await apiClient.get<any>(`/api/v1/rooms/${rid}`)
    if (roomData.layout_json) {
      try {
        const parsed = typeof roomData.layout_json === 'string'
          ? JSON.parse(roomData.layout_json)
          : roomData.layout_json
        if (parsed && typeof parsed === 'object' && Array.isArray(parsed.layers)) {
          customMapJson.value = parsed
        }
      } catch { /* 損壞的 JSON，用預設 map */ }
    }
  } catch { /* 用預設 map */ }
}

function enterEditMode() {
  game?.destroy(true)
  game = null
  isEditing.value = true
}

async function handleSave(mapJson: object) {
  const rid = currentRoomId.value
  if (rid) {
    try {
      await apiClient.patch(`/api/v1/rooms/${rid}/layout`, { layout_json: mapJson })
      customMapJson.value = mapJson as Record<string, unknown>
    } catch (e) {
      console.error('[Room2] Failed to save map:', e)
    }
  }
  isEditing.value = false
  await nextTick()
  await createGame()
}

async function exitEditMode() {
  isEditing.value = false
  await nextTick()
  await createGame()
}

async function createGame() {
  const { createRoom2Game } = await import('../game2/Room2Scene')
  if (canvasRef.value) {
    game = createRoom2Game('room2-canvas', customMapJson.value ?? undefined)
    setupGameListeners()
    pushDataToScene()
  }
}

function setupGameListeners() {
  if (!game) return
  game.events.on('scene-ready', () => {
    pushDataToScene()
    setupCharacterClickListener()
  })
}

// ===== Lifecycle =====
onMounted(async () => {
  try {
    await loadRoomMap()
    await createGame()
    if (!canvasRef.value) {
      error.value = 'Canvas element not found'
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    error.value = msg
    console.error('[Room2] Failed to create game:', e)
  }

  fetchMembers()
  pollId = window.setInterval(fetchMembers, 10000)

  bubbleInterval = window.setInterval(() => {
    const allMembers = members.value
    if (allMembers.length === 0) return
    const m = allMembers[Math.floor(Math.random() * allMembers.length)]!
    randomBubble(m.id, busyMemberMap.value.has(m.id))
  }, 5000)

  window.addEventListener('aegis:member-dialogue', onMemberDialoguePopup)
})

onUnmounted(() => {
  clearInterval(pollId)
  clearInterval(bubbleInterval)
  window.removeEventListener('aegis:member-dialogue', onMemberDialoguePopup)
  game?.destroy(true)
  game = null
})

// Watch reactive data → push to Phaser
watch(
  [deskAssignments, restingMembers, bubbles, () => store.systemInfo, members],
  pushDataToScene,
  { deep: true },
)

// Watch room changes
watch(
  () => route.params.roomId,
  () => { fetchMembers() },
)
</script>

<template>
  <div class="h-full w-full bg-[#1a1a2e] relative">
    <!-- 編輯模式 -->
    <Room2Editor
      v-if="isEditing"
      :custom-map-json="customMapJson"
      @save="handleSave"
      @cancel="exitEditMode"
    />

    <!-- 遊戲模式 -->
    <template v-else>
      <div v-if="error" class="absolute inset-0 flex items-center justify-center z-10">
        <div class="bg-red-900/50 border border-red-500/30 rounded-lg p-6 max-w-md">
          <p class="text-red-400 text-sm font-mono">{{ error }}</p>
        </div>
      </div>

      <div class="flex flex-col h-full">
        <!-- Canvas -->
        <div id="room2-canvas" ref="canvasRef" class="flex-1 min-h-0" />

        <!-- Footer -->
        <div class="flex items-center gap-2 sm:gap-4 px-2 sm:px-3 h-6 bg-slate-800 border-t border-slate-700 z-10 shrink-0"
             style="font-family: 'Press Start 2P', monospace;">
          <span class="text-[8px] text-emerald-400">ACTIVE:{{ store.systemInfo.workstations_used }}</span>
          <span class="text-[8px] text-slate-400">IDLE:{{ restingMembers.length }}</span>
          <span class="text-[8px] text-slate-400">TOTAL:{{ members.length }}</span>
          <span class="flex-1"></span>
          <button
            class="text-[8px] text-amber-400/60 hover:text-amber-300 cursor-pointer"
            style="font-family: 'Press Start 2P', monospace;"
            @click="enterEditMode"
          >
            EDIT
          </button>
        </div>
      </div>

      <!-- Character Dialog -->
      <CharacterDialog
        v-if="showCharacterDialog && selectedCharacter"
        :member-id="selectedCharacter.memberId"
        :name="selectedCharacter.name"
        :provider="selectedCharacter.provider"
        :role="selectedCharacter.role"
        :portrait="assetUrl(selectedCharacter.portrait || '')"
        @close="closeCharacterDialog"
      />
    </template>
  </div>
</template>

<style scoped>
#room2-canvas {
  image-rendering: pixelated;
  image-rendering: crisp-edges;
}
#room2-canvas canvas {
  image-rendering: pixelated !important;
  image-rendering: crisp-edges !important;
}
</style>
