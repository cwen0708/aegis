<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Building2, Plus, Loader2, ChevronRight, FolderKanban, Users, LayoutGrid, Monitor } from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'
import { useDialogState } from '../../composables/useDialogState'
import { config } from '../../config'
import { authHeaders } from '../../utils/authFetch'

const router = useRouter()
const store = useAegisStore()
const API = config.apiUrl

// ─── Types ──────────────────────────────────────────────

interface RoomInfo {
  id: number
  name: string
  description: string
  layout_type: 'classic' | 'tiled'
  project_ids: number[]
  member_ids: number[]
  created_at: string
}

// ─── State ──────────────────────────────────────────────

const loading = ref(true)
const rooms = ref<RoomInfo[]>([])

// Create dialog
const createDialog = useDialogState()
const createForm = ref({
  name: '',
  description: '',
  layout_type: 'tiled' as 'classic' | 'tiled',
})
const creating = ref(false)

// ─── Fetch ──────────────────────────────────────────────

async function fetchRooms() {
  loading.value = true
  try {
    const res = await fetch(`${API}/api/v1/rooms`, { headers: authHeaders() })
    if (!res.ok) throw new Error('載入失敗')
    rooms.value = await res.json()
  } catch (e: any) {
    store.addToast(e.message || '房間載入失敗', 'error')
  }
  loading.value = false
}

onMounted(() => {
  fetchRooms()
})

// ─── Create ─────────────────────────────────────────────

function openCreateDialog() {
  createForm.value = { name: '', description: '', layout_type: 'tiled' }
  createDialog.open()
}

async function createRoom() {
  if (!createForm.value.name.trim()) {
    store.addToast('請填寫房間名稱', 'error')
    return
  }
  creating.value = true
  try {
    const res = await fetch(`${API}/api/v1/rooms`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(createForm.value),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '建立失敗' }))
      throw new Error(err.detail)
    }
    const newRoom = await res.json()
    store.addToast('房間已建立', 'success')
    createDialog.close()
    router.push(`/settings/rooms/${newRoom.id}`)
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
  creating.value = false
}

</script>

<template>
  <div class="space-y-6">
    <!-- Header Actions (Teleport to layout header) -->
    <Teleport to="#settings-header-actions">
      <button
        @click="openCreateDialog()"
        class="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 rounded-lg text-xs font-medium transition"
      >
        <Plus class="w-3.5 h-3.5" />
        新增房間
      </button>
    </Teleport>

    <!-- Loading -->
    <div v-if="loading" class="flex justify-center py-12">
      <Loader2 class="w-6 h-6 animate-spin text-slate-400" />
    </div>

    <!-- Room List -->
    <div v-else class="space-y-3">
      <div v-if="rooms.length === 0" class="text-center py-12 text-slate-500 text-sm">
        尚無房間，點擊「新增房間」開始
      </div>

      <div
        v-for="room in rooms"
        :key="room.id"
        @click="router.push(`/settings/rooms/${room.id}`)"
        class="rounded-xl border p-4 cursor-pointer bg-slate-800/50 border-slate-700/50 hover:border-slate-600/50 hover:bg-slate-700/30 transition-all"
      >
        <div class="flex items-center gap-4">
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <Building2 class="w-4 h-4 text-emerald-400 shrink-0" />
              <span class="font-medium text-slate-200">{{ room.name }}</span>
              <span
                class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium"
                :class="room.layout_type === 'tiled' ? 'bg-sky-500/15 text-sky-400' : 'bg-amber-500/15 text-amber-400'"
              >
                <component :is="room.layout_type === 'tiled' ? LayoutGrid : Monitor" class="w-3 h-3" />
                {{ room.layout_type === 'tiled' ? '磚塊' : '經典' }}
              </span>
            </div>
            <p v-if="room.description" class="text-xs text-slate-500 mt-1 ml-6 truncate">{{ room.description }}</p>
            <div class="flex items-center gap-4 mt-2 ml-6 text-xs text-slate-500">
              <span class="flex items-center gap-1">
                <FolderKanban class="w-3.5 h-3.5" />
                {{ room.project_ids.length }} 專案
              </span>
              <span class="flex items-center gap-1">
                <Users class="w-3.5 h-3.5" />
                {{ room.member_ids.length }} 成員
              </span>
            </div>
          </div>
          <ChevronRight class="w-4 h-4 text-slate-600 shrink-0" />
        </div>
      </div>
    </div>

    <!-- Dialog: Create Room -->
    <Teleport to="body">
      <div
        v-if="createDialog.isOpen.value"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
        @click.self="createDialog.close()"
      >
        <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-lg p-6 space-y-4">
          <h3 class="text-sm font-bold text-slate-200">新增房間</h3>

          <div>
            <label class="block text-sm text-slate-400 mb-1">房間名稱</label>
            <input
              v-model="createForm.name"
              type="text"
              class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-500"
              placeholder="如：前端團隊"
            />
          </div>

          <div>
            <label class="block text-sm text-slate-400 mb-1">描述</label>
            <input
              v-model="createForm.description"
              type="text"
              class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-500"
              placeholder="如：前端相關專案和成員"
            />
          </div>

          <div>
            <label class="block text-sm text-slate-400 mb-2">佈局模式</label>
            <div class="flex gap-3">
              <label
                v-for="opt in ([
                  { value: 'tiled', label: '磚塊模式', icon: 'grid', desc: '卡片式成員排列' },
                  { value: 'classic', label: '經典模式', icon: 'monitor', desc: 'Phaser 虛擬辦公室' },
                ] as const)"
                :key="opt.value"
                class="flex-1 relative cursor-pointer rounded-lg border p-3 transition-all"
                :class="createForm.layout_type === opt.value
                  ? 'border-emerald-500 bg-emerald-500/10'
                  : 'border-slate-600 bg-slate-900 hover:border-slate-500'"
              >
                <input
                  type="radio"
                  :value="opt.value"
                  v-model="createForm.layout_type"
                  class="sr-only"
                />
                <div class="flex items-center gap-2">
                  <LayoutGrid v-if="opt.value === 'tiled'" class="w-4 h-4" :class="createForm.layout_type === opt.value ? 'text-emerald-400' : 'text-slate-500'" />
                  <Monitor v-else class="w-4 h-4" :class="createForm.layout_type === opt.value ? 'text-emerald-400' : 'text-slate-500'" />
                  <span class="text-sm font-medium" :class="createForm.layout_type === opt.value ? 'text-slate-200' : 'text-slate-400'">{{ opt.label }}</span>
                </div>
                <p class="text-xs mt-1 ml-6" :class="createForm.layout_type === opt.value ? 'text-slate-400' : 'text-slate-600'">{{ opt.desc }}</p>
              </label>
            </div>
          </div>

          <div class="flex justify-end gap-3 pt-2">
            <button
              @click="createDialog.close()"
              class="px-4 py-2 text-slate-400 hover:text-slate-200 transition"
            >
              取消
            </button>
            <button
              @click="createRoom"
              :disabled="creating || !createForm.name.trim()"
              class="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition"
            >
              <Loader2 v-if="creating" class="w-4 h-4 animate-spin" />
              建立
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
