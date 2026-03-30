<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTaskStore } from '../stores/task'
import { apiClient } from '../services/api/client'
import { Loader2, Box, Monitor } from 'lucide-vue-next'
import CharacterDialog from '../components/CharacterDialog.vue'
import { useOffice3D } from '../game3d/useOffice3D'
import { assetUrl } from '../config'
import type { SceneData3D, CharacterClickInfo } from '../game3d/types'

const route = useRoute()
const router = useRouter()
const taskStore = useTaskStore()

// ===== Refs =====
const canvasRef = ref<HTMLCanvasElement | null>(null)
const labelContainerRef = ref<HTMLDivElement | null>(null)

// ===== Room =====
const currentRoomId = computed(() => {
  const id = route.params.roomId as string | undefined
  return id || null
})

// ===== Members =====
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

// ===== Busy/Idle =====
const busyMemberMap = computed(() => {
  const map = new Map<number, { card_title: string; project: string; provider: string }>()
  for (const t of taskStore.runningTasks) {
    const mid = (t as any).member_id
    if (mid) {
      map.set(mid, { card_title: t.card_title, project: t.project, provider: t.provider })
    }
  }
  return map
})

const deskAssignments = computed(() => {
  const desks: Array<{ memberId: number; name: string; provider: string; deskIndex: number }> = []
  let idx = 0
  for (const m of members.value) {
    if (busyMemberMap.value.has(m.id) && idx < 6) {
      desks.push({ memberId: m.id, name: m.name, provider: m.provider, deskIndex: idx })
      idx++
    }
  }
  return desks
})

const restingMembers = computed(() => {
  const busy = busyMemberMap.value
  return members.value.filter(m => !busy.has(m.id)).map(m => ({
    memberId: m.id,
    name: m.name,
    provider: m.provider,
  }))
})

// ===== Character Dialog =====
const showCharacterDialog = ref(false)
const selectedCharacter = ref<{ memberId: number; name: string; provider: string; role?: string; portrait?: string } | null>(null)

function onCharacterClicked(info: CharacterClickInfo) {
  const member = members.value.find(m => m.id === info.memberId)
  selectedCharacter.value = {
    ...info,
    role: member?.role || (member?.provider === 'claude' ? 'Claude 開發者' : member?.provider === 'gemini' ? 'Gemini 開發者' : '開發者'),
    portrait: member?.portrait || '',
  }
  showCharacterDialog.value = true
}

function closeCharacterDialog() {
  showCharacterDialog.value = false
  selectedCharacter.value = null
}

// ===== Member dialogue popup (from runner) =====
function onMemberDialoguePopup(e: Event) {
  const detail = (e as CustomEvent).detail
  if (!detail?.member_id || !detail?.member_name) return
  if (showCharacterDialog.value && selectedCharacter.value?.memberId !== detail.member_id) return
  selectedCharacter.value = {
    memberId: detail.member_id,
    name: detail.member_name,
    provider: detail.provider || 'claude',
  }
  showCharacterDialog.value = true
}

// ===== 3D Scene =====
const office3d = useOffice3D(canvasRef, labelContainerRef, { onCharacterClicked })

function pushDataToScene() {
  const data: SceneData3D = {
    desks: deskAssignments.value,
    resting: restingMembers.value,
    bubbles: new Map(),
  }
  office3d.updateData(data)
}

watch([deskAssignments, restingMembers], pushDataToScene)

// ===== Lifecycle =====
onMounted(async () => {
  fetchMembers()
  pollId = window.setInterval(fetchMembers, 10000)
  window.addEventListener('aegis:member-dialogue', onMemberDialoguePopup)

  await nextTick()
  await office3d.init()

  // Push initial data after scene is ready
  setTimeout(pushDataToScene, 500)
})

onUnmounted(() => {
  clearInterval(pollId)
  window.removeEventListener('aegis:member-dialogue', onMemberDialoguePopup)
})

function goTo2D() {
  const rid = currentRoomId.value
  router.push(rid ? `/rooms/${rid}` : '/rooms')
}
</script>

<template>
  <div class="h-screen w-full bg-gray-900 relative overflow-hidden">
    <!-- 3D Canvas -->
    <canvas ref="canvasRef" class="w-full h-full block" />

    <!-- CSS2D Label Layer -->
    <div ref="labelContainerRef" class="absolute inset-0 pointer-events-none" />

    <!-- Loading -->
    <div v-if="office3d.isLoading.value" class="absolute inset-0 flex items-center justify-center bg-gray-900/80 z-20">
      <div class="text-center">
        <Loader2 class="animate-spin text-emerald-400 mx-auto" :size="48" />
        <div class="text-slate-400 mt-3 text-sm">Loading 3D scene...</div>
      </div>
    </div>

    <!-- Top bar -->
    <div class="absolute top-3 right-3 z-10 flex items-center gap-2">
      <button
        @click="goTo2D"
        class="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800/90 hover:bg-slate-700 text-slate-300 rounded-lg text-xs border border-slate-700 transition"
      >
        <Monitor :size="14" />
        2D
      </button>
    </div>

    <!-- Bottom status bar -->
    <div class="absolute bottom-0 left-0 right-0 h-7 bg-slate-800/90 border-t border-slate-700 flex items-center px-4 text-xs text-slate-400 z-10 gap-4">
      <div class="flex items-center gap-1.5">
        <Box :size="12" class="text-emerald-400" />
        <span>3D Office</span>
      </div>
      <div>
        <span class="text-amber-400">ACTIVE:</span> {{ deskAssignments.length }}
      </div>
      <div>
        <span class="text-slate-500">IDLE:</span> {{ restingMembers.length }}
      </div>
      <div>
        <span class="text-slate-500">TOTAL:</span> {{ members.length }}
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
  </div>
</template>

<style>
/* Head label styling for CSS2DRenderer */
.head-label-3d {
  background: rgba(15, 23, 42, 0.88);
  border: 1px solid #475569;
  border-radius: 6px;
  padding: 2px 8px;
  text-align: center;
  pointer-events: none;
  transform: translateY(-8px);
}
.head-label-3d .hl-name {
  font-size: 11px;
  font-weight: 600;
  color: #e2e8f0;
  white-space: nowrap;
}
.head-label-3d .hl-state {
  font-size: 9px;
  color: #94a3b8;
}
.head-label-3d .hl-state.busy {
  color: #fbbf24;
}
</style>
