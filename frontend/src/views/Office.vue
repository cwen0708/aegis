<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useAegisStore } from '../stores/aegis'
import { useAuthStore } from '../stores/auth'
import { useDomainStore } from '../stores/domain'
import { useResponsive } from '../composables/useResponsive'

const { isMobile } = useResponsive()
const route = useRoute()
const auth = useAuthStore()
const domainStore = useDomainStore()
import { Settings } from 'lucide-vue-next'
import { createOfficeGame, OfficeScene } from '../game/OfficeScene'
import OfficeEditor from '../components/OfficeEditor.vue'
import CharacterDialog from '../components/CharacterDialog.vue'
import type { OfficeLayout } from '../game/types'
import { deserializeLayout, serializeLayout } from '../game/layoutManager'
import { buildDefaultLayout } from '../game/defaultLayout'
import type Phaser from 'phaser'

const store = useAegisStore()

// ===== Room support =====
const currentRoomId = computed(() => {
  const id = route.params.roomId as string | undefined
  if (id) return id
  // Fallback: if domain has rooms, use the first one
  if (domainStore.rooms && domainStore.rooms.length > 0) return String(domainStore.rooms[0]!.id)
  return null
})

// ===== Layout management =====
const currentLayout = ref<OfficeLayout | null>(null)
const isEditing = ref(false)

async function loadLayoutFromSettings() {
  if (currentRoomId.value) {
    // Load layout from room API
    try {
      const res = await fetch(`/api/v1/rooms/${currentRoomId.value}`)
      if (res.ok) {
        const room = await res.json()
        if (room.layout_json) {
          const layout = deserializeLayout(room.layout_json)
          if (layout) {
            if (!layout.slots || layout.slots.length === 0) {
              const defaultLayout = buildDefaultLayout(totalDesks.value || 4)
              layout.slots = defaultLayout.slots
            }
            currentLayout.value = layout
            return
          }
        }
      }
    } catch (e) {
      console.warn('Failed to load room layout:', e)
    }
    // Fallback to default layout if room API fails
    currentLayout.value = buildDefaultLayout(totalDesks.value || 4)
  } else {
    // Original behavior: load from system settings
    await store.fetchSettings()
    const raw = store.settings.office_layout
    if (raw) {
      const layout = deserializeLayout(raw)
      if (layout) {
        if (!layout.slots || layout.slots.length === 0) {
          const defaultLayout = buildDefaultLayout(totalDesks.value || 4)
          layout.slots = defaultLayout.slots
        }
        currentLayout.value = layout
        return
      }
    }
    currentLayout.value = buildDefaultLayout(totalDesks.value || 4)
  }
}

async function handleSaveLayout(layout: OfficeLayout) {
  currentLayout.value = layout
  if (currentRoomId.value) {
    // Save to room
    await fetch(`/api/v1/rooms/${currentRoomId.value}/layout`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ layout_json: serializeLayout(layout) }),
    })
  } else {
    // Save to system settings
    await store.updateSettings({ office_layout: serializeLayout(layout) })
  }
}

function handleExitEdit() {
  isEditing.value = false
  rebuildOfficeGame()
}

function enterEditMode() {
  game?.destroy(true)
  game = null
  isEditing.value = true
}

// 成員資料
interface MemberInfo {
  id: number
  name: string
  avatar: string
  provider: string
  role?: string
  portrait?: string
  sprite_index?: number
}

const members = ref<MemberInfo[]>([])
let pollId: number

async function fetchMembers() {
  try {
    const res = await fetch('/api/v1/members')
    if (res.ok) members.value = await res.json()
  } catch {}
}

onMounted(() => {
  fetchMembers()
  pollId = window.setInterval(fetchMembers, 10000)
})
onUnmounted(() => clearInterval(pollId))

// 工作台數量
const totalDesks = computed(() => store.systemInfo.workstations_total)

// 哪些成員正在忙碌（從 running_tasks 取 member_id）
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

// 工作台分配：busyMembers 佔據工作台
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

// 休息區成員：不在忙碌的啟用成員
const restingMembers = computed(() => {
  const busy = busyMemberMap.value
  return members.value.filter(m => !busy.has(m.id))
})

// 對話泡泡
const IDLE_BUBBLES = [
  '休息一下～',
  '等待任務中...',
  '喝杯咖啡',
  '隨時待命！',
  '整理思緒中',
  '充電完畢！',
  '看看有什麼新任務',
  '今天也要加油',
]

const WORK_BUBBLES = [
  '專注模式！',
  '程式碼寫起來！',
  '分析中...',
  '快完成了',
  '全力輸出！',
  '進度推進中',
]

const bubbles = ref<Map<number, string>>(new Map())

function randomBubble(memberId: number, isWorking: boolean) {
  const list = isWorking ? WORK_BUBBLES : IDLE_BUBBLES
  const text = list[Math.floor(Math.random() * list.length)]!
  bubbles.value.set(memberId, text)
  setTimeout(() => {
    bubbles.value.delete(memberId)
  }, 4000)
}

let bubbleInterval: number
onMounted(() => {
  bubbleInterval = window.setInterval(() => {
    const allMembers = members.value
    if (allMembers.length === 0) return
    const m = allMembers[Math.floor(Math.random() * allMembers.length)]!
    randomBubble(m.id, busyMemberMap.value.has(m.id))
  }, 5000)
})
onUnmounted(() => clearInterval(bubbleInterval))

// 時間顯示
const now = ref(Date.now())
let timeInterval: number
onMounted(() => { timeInterval = window.setInterval(() => now.value = Date.now(), 1000) })
onUnmounted(() => clearInterval(timeInterval))

// Debug: 格子座標追蹤
const hoverPos = ref<{ row: number; col: number; frame: string | number }>({ row: 0, col: 0, frame: '--' })
const TILE = 16, ZOOM = 3, tileSize = TILE * ZOOM

function onCanvasMouseMove(e: MouseEvent) {
  const canvas = (e.target as HTMLElement).querySelector('canvas') || e.target as HTMLCanvasElement
  if (!canvas || canvas.tagName !== 'CANVAS') return

  const rect = canvas.getBoundingClientRect()
  const scaleX = canvas.width / rect.width
  const scaleY = canvas.height / rect.height

  let offsetX = 0, offsetY = 0
  const scene = getScene()
  if (scene?.cameras?.main) {
    offsetX = scene.cameras.main.scrollX
    offsetY = scene.cameras.main.scrollY
  }

  const worldX = (e.clientX - rect.left) * scaleX + offsetX
  const worldY = (e.clientY - rect.top) * scaleY + offsetY
  const col = Math.floor(worldX / tileSize)
  const row = Math.floor(worldY / tileSize)

  // 取得 frame
  let frame: string | number = '--'
  if (scene?.layout) {
    const { cols, rows, ground } = scene.layout
    if (row >= 0 && row < rows && col >= 0 && col < cols) {
      const gt = ground[row * cols + col]!
      const isWall = gt === 1 || (gt >= 13 && gt <= 16)
      if (!isWall) {
        frame = `g${gt}`
      } else {
        const x = col * tileSize, y = row * tileSize
        const images = scene.children.list.filter((c: any) => c.type === 'Image' && c.texture?.key === 'floor_tiles')
        for (const img of images as any[]) {
          if (Math.abs(img.x - x) < 2 && Math.abs(img.y - y) < 2) {
            frame = img.frame?.name ?? '--'
            break
          }
        }
      }
    }
  }
  hoverPos.value = { row, col, frame }
}

function copyPos() {
  const { row, col, frame } = hoverPos.value
  const scene = getScene()
  let info = `row=${row}, col=${col}, frame=${frame}`

  if (scene?.layout) {
    const { cols, rows, ground } = scene.layout
    const getType = (r: number, c: number) => {
      if (r < 0 || r >= rows || c < 0 || c >= cols) return 'X'
      const gt = ground[r * cols + c]!
      if (gt === 0) return 'V' // void
      if (gt === 1 || (gt >= 13 && gt <= 16)) return 'W' // wall
      return 'F' // floor
    }

    // 8 neighbors: N, NE, E, SE, S, SW, W, NW
    const n = getType(row - 1, col)
    const ne = getType(row - 1, col + 1)
    const e = getType(row, col + 1)
    const se = getType(row + 1, col + 1)
    const s = getType(row + 1, col)
    const sw = getType(row + 1, col - 1)
    const w = getType(row, col - 1)
    const nw = getType(row - 1, col - 1)

    info += `\nneighbors: n=${n}, ne=${ne}, e=${e}, se=${se}, s=${s}, sw=${sw}, w=${w}, nw=${nw}`
    info += `\n  ${nw} ${n} ${ne}`
    info += `\n  ${w} * ${e}`
    info += `\n  ${sw} ${s} ${se}`
    info += `\nshould be => `
  }

  navigator.clipboard.writeText(info)
}

// ===== Phaser Game =====
let game: Phaser.Game | null = null

function getScene(): OfficeScene | null {
  if (!game) return null
  return game.scene.getScene('OfficeScene') as OfficeScene | null
}

function pushDataToScene() {
  const scene = getScene()
  if (!scene?.updateData) return

  scene.updateData({
    totalDesks: totalDesks.value,
    desks: deskAssignments.value.map(d => d ? {
      member: { id: d.member.id, name: d.member.name, provider: d.member.provider, sprite_index: d.member.sprite_index ?? 0 },
      task: { card_title: d.task.card_title, project: d.task.project },
    } : null),
    resting: restingMembers.value.map(m => ({
      id: m.id, name: m.name, provider: m.provider, sprite_index: m.sprite_index ?? 0,
    })),
    bubbles: bubbles.value,
    used: store.systemInfo.workstations_used,
    total: store.systemInfo.workstations_total,
    memberCount: members.value.length,
  })
}

// ===== Character Dialog =====
interface CharacterInfo {
  memberId: number
  name: string
  provider: string
  role?: string
  portrait?: string
}
const showCharacterDialog = ref(false)
const selectedCharacter = ref<CharacterInfo | null>(null)

function setupCharacterClickListener() {
  const scene = getScene()
  if (!scene) return
  scene.events.on('character-clicked', (data: CharacterInfo) => {
    // Find member role and portrait from members list
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

function setupGameListeners() {
  if (!game) return
  // Use 'scene-ready' emitted from OfficeScene.create() — reliable unlike
  // 'ready' which may fire synchronously during new Phaser.Game() constructor
  game.events.on('scene-ready', () => {
    pushDataToScene()
    setupCharacterClickListener()
  })
}

async function rebuildOfficeGame() {
  game?.destroy(true)
  game = null

  // Wait for Vue to re-render #office-canvas
  await nextTick()

  if (isEditing.value) return
  const el = document.getElementById('office-canvas')
  if (!el) return

  const layout = currentLayout.value || buildDefaultLayout(totalDesks.value || 4)
  game = createOfficeGame('office-canvas', layout)
  setupGameListeners()
}

onMounted(async () => {
  await loadLayoutFromSettings()
  await document.fonts.ready

  const layout = currentLayout.value || buildDefaultLayout(totalDesks.value || 4)
  game = createOfficeGame('office-canvas', layout)
  setupGameListeners()
})

onUnmounted(() => {
  game?.destroy(true)
  game = null
})

// Watch all reactive data and push to Phaser scene
watch(
  [deskAssignments, restingMembers, bubbles, () => store.systemInfo, members],
  pushDataToScene,
  { deep: true }
)

// Watch room changes — reload layout and rebuild game
watch(
  () => route.params.roomId,
  async () => {
    await loadLayoutFromSettings()
    await fetchMembers()
    rebuildOfficeGame()
  }
)
</script>

<template>
  <div class="h-full w-full bg-[#1a1510] relative">
    <!-- Editor mode -->
    <OfficeEditor
      v-if="isEditing && currentLayout"
      :layout="currentLayout"
      @save="handleSaveLayout"
      @cancel="handleExitEdit"
    />

    <!-- Normal office view -->
    <template v-else>
      <div class="flex flex-col h-full">
        <!-- Canvas -->
        <div id="office-canvas" class="flex-1 min-h-0" @mousemove="onCanvasMouseMove" @click="copyPos"></div>

        <!-- Footer -->
        <div class="flex items-center gap-2 sm:gap-4 px-2 sm:px-3 h-6 bg-slate-800 border-t border-slate-700 z-10 shrink-0"
             style="font-family: 'Press Start 2P', monospace;">
          <span class="text-[8px] text-emerald-400">ACTIVE:{{ store.systemInfo.workstations_used }}</span>
          <span class="text-[8px] text-slate-400">IDLE:{{ restingMembers.length }}</span>
          <span class="text-[8px] text-slate-400">TOTAL:{{ members.length }}</span>
          <span class="flex-1"></span>
          <!-- Debug info: hide on mobile -->
          <span v-if="!isMobile" class="text-[8px] text-amber-400 cursor-pointer" @click.stop="copyPos" title="Click to copy">
            row={{ hoverPos.row }}, col={{ hoverPos.col }}, frame={{ hoverPos.frame }}
          </span>
          <button
            v-if="!isMobile && auth.isAuthenticated"
            @click="enterEditMode"
            class="p-1 text-slate-400 hover:text-white hover:bg-slate-700 rounded transition-colors"
            title="裝修"
          >
            <Settings :size="14" />
          </button>
        </div>
      </div>
    </template>

    <!-- Character Dialog -->
    <CharacterDialog
      v-if="showCharacterDialog && selectedCharacter"
      :member-id="selectedCharacter.memberId"
      :name="selectedCharacter.name"
      :provider="selectedCharacter.provider"
      :role="selectedCharacter.role"
      :portrait="selectedCharacter.portrait"
      @close="closeCharacterDialog"
    />
  </div>
</template>

<style scoped>
#office-canvas {
  image-rendering: pixelated;
  image-rendering: crisp-edges;
}
#office-canvas canvas {
  image-rendering: pixelated !important;
  image-rendering: crisp-edges !important;
}
</style>
