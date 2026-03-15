<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Building2, Plus, Trash2, Users, FolderKanban, Loader2, ChevronDown, ChevronUp } from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { config } from '../../config'
import { authHeaders } from '../../utils/authFetch'

const store = useAegisStore()
const API = config.apiUrl

// ─── Types ──────────────────────────────────────────────

interface ProjectOption {
  id: number
  name: string
}

interface MemberOption {
  id: number
  name: string
  avatar: string
}

interface RoomInfo {
  id: number
  name: string
  description: string
  project_ids: number[]
  member_ids: number[]
  created_at: string
}

// ─── State ──────────────────────────────────────────────

const loading = ref(true)
const rooms = ref<RoomInfo[]>([])
const projects = ref<ProjectOption[]>([])
const members = ref<MemberOption[]>([])

const expandedId = ref<number | null>(null)
const editForm = ref({
  name: '',
  description: '',
  project_ids: [] as number[],
  member_ids: [] as number[],
})
const saving = ref(false)

// Create dialog
const showCreateDialog = ref(false)
const createForm = ref({
  name: '',
  description: '',
  project_ids: [] as number[],
  member_ids: [] as number[],
})
const creating = ref(false)

// Delete
const confirmDelete = ref(false)
const deleteTarget = ref<RoomInfo | null>(null)

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

async function fetchProjects() {
  try {
    const res = await fetch(`${API}/api/v1/projects/`)
    if (res.ok) {
      const data = await res.json()
      projects.value = data.map((p: any) => ({ id: p.id, name: p.name }))
    }
  } catch {}
}

async function fetchMembers() {
  try {
    const res = await fetch(`${API}/api/v1/members`)
    if (res.ok) members.value = await res.json()
  } catch {}
}

onMounted(() => {
  fetchRooms()
  fetchProjects()
  fetchMembers()
})

// ─── Expand / Edit ──────────────────────────────────────

function toggleExpand(room: RoomInfo) {
  if (expandedId.value === room.id) {
    expandedId.value = null
    return
  }
  expandedId.value = room.id
  editForm.value = {
    name: room.name,
    description: room.description,
    project_ids: [...room.project_ids],
    member_ids: [...room.member_ids],
  }
}

async function saveRoom() {
  if (!expandedId.value) return
  if (!editForm.value.name.trim()) {
    store.addToast('請填寫房間名稱', 'error')
    return
  }
  saving.value = true
  try {
    const res = await fetch(`${API}/api/v1/rooms/${expandedId.value}`, {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(editForm.value),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '儲存失敗' }))
      throw new Error(err.detail)
    }
    store.addToast('房間已更新', 'success')
    expandedId.value = null
    await fetchRooms()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
  saving.value = false
}

// ─── Create ─────────────────────────────────────────────

function openCreateDialog() {
  createForm.value = { name: '', description: '', project_ids: [], member_ids: [] }
  showCreateDialog.value = true
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
    store.addToast('房間已建立', 'success')
    showCreateDialog.value = false
    await fetchRooms()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
  creating.value = false
}

// ─── Delete ─────────────────────────────────────────────

function requestDelete(room: RoomInfo) {
  deleteTarget.value = room
  confirmDelete.value = true
}

async function doDelete() {
  if (!deleteTarget.value) return
  try {
    const res = await fetch(`${API}/api/v1/rooms/${deleteTarget.value.id}`, {
      method: 'DELETE',
      headers: authHeaders(),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '刪除失敗' }))
      throw new Error(err.detail)
    }
    store.addToast('房間已刪除', 'success')
    if (expandedId.value === deleteTarget.value.id) expandedId.value = null
    await fetchRooms()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
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
      <Loader2 class="w-8 h-8 animate-spin text-slate-400" />
    </div>

    <!-- Room List -->
    <div v-else class="space-y-3">
      <div
        v-for="room in rooms"
        :key="room.id"
        class="bg-slate-900/50 rounded-xl border border-slate-700/50 transition-all"
        :class="{ 'border-slate-600': expandedId === room.id }"
      >
        <!-- Room Card Header -->
        <div
          class="p-4 cursor-pointer hover:bg-slate-800/50 transition-all"
          @click="toggleExpand(room)"
        >
          <div class="flex items-center justify-between">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <Building2 class="w-4 h-4 text-emerald-400 shrink-0" />
                <span class="font-medium text-slate-200">{{ room.name }}</span>
              </div>
              <p v-if="room.description" class="text-sm text-slate-500 mt-1 ml-6">{{ room.description }}</p>
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
            <div class="flex items-center gap-2 ml-4">
              <button
                @click.stop="requestDelete(room)"
                class="p-2 text-slate-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition"
                title="刪除"
              >
                <Trash2 class="w-4 h-4" />
              </button>
              <component
                :is="expandedId === room.id ? ChevronUp : ChevronDown"
                class="w-5 h-5 text-slate-500 shrink-0"
              />
            </div>
          </div>
        </div>

        <!-- Expanded Edit Panel -->
        <div v-if="expandedId === room.id" class="border-t border-slate-700/50 p-4 space-y-4">
          <div>
            <label class="block text-sm text-slate-400 mb-1">房間名稱</label>
            <input
              v-model="editForm.name"
              type="text"
              class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-500"
              placeholder="如：前端團隊"
            />
          </div>

          <div>
            <label class="block text-sm text-slate-400 mb-1">描述</label>
            <input
              v-model="editForm.description"
              type="text"
              class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-500"
              placeholder="如：前端相關專案和成員"
            />
          </div>

          <div v-if="projects.length > 0">
            <label class="block text-sm text-slate-400 mb-1">
              <FolderKanban class="w-3.5 h-3.5 inline" />
              包含專案
            </label>
            <div class="space-y-1 max-h-40 overflow-y-auto">
              <label
                v-for="p in projects"
                :key="p.id"
                class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer hover:bg-slate-800"
              >
                <input
                  type="checkbox"
                  :value="p.id"
                  v-model="editForm.project_ids"
                  class="rounded bg-slate-700 border-slate-600 text-emerald-500 focus:ring-emerald-500"
                />
                <span class="text-sm text-slate-300">{{ p.name }}</span>
              </label>
            </div>
          </div>

          <div v-if="members.length > 0">
            <label class="block text-sm text-slate-400 mb-1">
              <Users class="w-3.5 h-3.5 inline" />
              包含成員
            </label>
            <div class="space-y-1 max-h-40 overflow-y-auto">
              <label
                v-for="m in members"
                :key="m.id"
                class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer hover:bg-slate-800"
              >
                <input
                  type="checkbox"
                  :value="m.id"
                  v-model="editForm.member_ids"
                  class="rounded bg-slate-700 border-slate-600 text-emerald-500 focus:ring-emerald-500"
                />
                <span class="text-sm text-slate-300">{{ m.avatar }} {{ m.name }}</span>
              </label>
            </div>
          </div>

          <div class="flex justify-end gap-3 pt-2">
            <button
              @click="expandedId = null"
              class="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition"
            >
              取消
            </button>
            <button
              @click="saveRoom"
              :disabled="saving"
              class="flex items-center gap-2 px-4 py-2 text-sm bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded-lg transition"
            >
              <Loader2 v-if="saving" class="w-4 h-4 animate-spin" />
              儲存
            </button>
          </div>
        </div>
      </div>

      <!-- Empty State -->
      <div v-if="rooms.length === 0" class="text-center py-12 text-slate-500">
        尚無房間，點擊「新增房間」開始
      </div>
    </div>

    <!-- Dialog: Create Room -->
    <Teleport to="body">
      <div
        v-if="showCreateDialog"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
        @click.self="showCreateDialog = false"
      >
        <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-lg p-6 space-y-4 max-h-[85vh] overflow-y-auto">
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

          <div v-if="projects.length > 0">
            <label class="block text-sm text-slate-400 mb-1">包含專案</label>
            <div class="space-y-1 max-h-40 overflow-y-auto">
              <label
                v-for="p in projects"
                :key="p.id"
                class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer hover:bg-slate-800"
              >
                <input
                  type="checkbox"
                  :value="p.id"
                  v-model="createForm.project_ids"
                  class="rounded bg-slate-700 border-slate-600 text-emerald-500 focus:ring-emerald-500"
                />
                <span class="text-sm text-slate-300">{{ p.name }}</span>
              </label>
            </div>
          </div>

          <div v-if="members.length > 0">
            <label class="block text-sm text-slate-400 mb-1">包含成員</label>
            <div class="space-y-1 max-h-40 overflow-y-auto">
              <label
                v-for="m in members"
                :key="m.id"
                class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer hover:bg-slate-800"
              >
                <input
                  type="checkbox"
                  :value="m.id"
                  v-model="createForm.member_ids"
                  class="rounded bg-slate-700 border-slate-600 text-emerald-500 focus:ring-emerald-500"
                />
                <span class="text-sm text-slate-300">{{ m.avatar }} {{ m.name }}</span>
              </label>
            </div>
          </div>

          <div class="flex justify-end gap-3 pt-2">
            <button
              @click="showCreateDialog = false"
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

    <!-- Confirm Dialog -->
    <ConfirmDialog
      v-model:show="confirmDelete"
      title="刪除房間"
      :message="`確定要刪除房間「${deleteTarget?.name}」？\n此操作不會刪除房間內的專案和成員，只會移除房間的分組設定。`"
      confirm-text="刪除"
      @confirm="doDelete"
    />
  </div>
</template>
