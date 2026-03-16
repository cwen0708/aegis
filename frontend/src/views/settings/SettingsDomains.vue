<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Globe, Plus, Loader2, Building2, Star, ChevronRight, X } from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'
import { config } from '../../config'
import { authHeaders } from '../../utils/authFetch'

const router = useRouter()
const store = useAegisStore()
const API = config.apiUrl

// ─── Types ──────────────────────────────────────────────

interface RoomOption {
  id: number
  name: string
}

interface DomainInfo {
  id: number
  hostname: string
  name: string
  is_default: boolean
  is_active: boolean
  room_ids: number[]
  created_at: string
}

// ─── State ──────────────────────────────────────────────

const loading = ref(true)
const domains = ref<DomainInfo[]>([])
const roomOptions = ref<RoomOption[]>([])

// Create dialog
const showCreateDialog = ref(false)
const createForm = ref({
  hostname: '',
  name: '',
  is_default: false,
  room_ids: [] as number[],
})
const creating = ref(false)

// ─── Fetch ──────────────────────────────────────────────

async function fetchDomains() {
  loading.value = true
  try {
    const res = await fetch(`${API}/api/v1/domains`, { headers: authHeaders() })
    if (!res.ok) throw new Error('載入失敗')
    const raw = await res.json()
    domains.value = raw.map((d: any) => ({
      ...d,
      room_ids: typeof d.room_ids_json === 'string' ? JSON.parse(d.room_ids_json || '[]') : (d.room_ids || []),
    }))
  } catch (e: any) {
    store.addToast(e.message || '網域載入失敗', 'error')
  }
  loading.value = false
}

async function fetchRooms() {
  try {
    const res = await fetch(`${API}/api/v1/rooms`, { headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      roomOptions.value = data.map((r: any) => ({ id: r.id, name: r.name }))
    }
  } catch {}
}

onMounted(() => {
  fetchDomains()
  fetchRooms()
})

// ─── Create ─────────────────────────────────────────────

function openCreateDialog() {
  createForm.value = { hostname: '', name: '', is_default: false, room_ids: [] }
  showCreateDialog.value = true
}

async function createDomain() {
  if (!createForm.value.hostname.trim()) {
    store.addToast('請填寫主機名稱', 'error')
    return
  }
  creating.value = true
  try {
    const payload: any = {
      ...createForm.value,
      room_ids_json: JSON.stringify(createForm.value.room_ids),
    }
    delete payload.room_ids
    const res = await fetch(`${API}/api/v1/domains`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '建立失敗' }))
      throw new Error(err.detail)
    }
    const created = await res.json()
    store.addToast('網域已建立', 'success')
    showCreateDialog.value = false
    router.push(`/settings/domains/${created.id}`)
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
  creating.value = false
}

// ─── Helpers ────────────────────────────────────────────

function getRoomName(id: number): string {
  return roomOptions.value.find(r => r.id === id)?.name || `#${id}`
}
</script>

<template>
  <div class="space-y-6">
    <!-- Hint -->
    <div class="bg-slate-800/30 rounded-xl border border-slate-700/30 p-4 text-sm text-slate-400">
      預設網域用於 hostname 不匹配任何設定時的 fallback。
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex justify-center py-12">
      <Loader2 class="w-8 h-8 animate-spin text-slate-400" />
    </div>

    <!-- Domain List -->
    <div v-else class="space-y-3">
      <div
        v-for="d in domains"
        :key="d.id"
        class="bg-slate-900/50 rounded-xl border border-slate-700/50 p-4 cursor-pointer hover:border-slate-600 hover:bg-slate-800/50 transition-all"
        @click="router.push(`/settings/domains/${d.id}`)"
      >
        <div class="flex items-center justify-between">
          <!-- Left: Info -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <Globe class="w-4 h-4 text-sky-400 shrink-0" />
              <span class="font-medium text-slate-200">{{ d.hostname }}</span>
              <span v-if="d.name" class="text-sm text-slate-500">{{ d.name }}</span>
              <span
                v-if="d.is_default"
                class="flex items-center gap-1 px-2 py-0.5 text-xs rounded bg-amber-500/20 text-amber-400 border border-amber-500/30"
              >
                <Star class="w-3 h-3" />
                預設
              </span>
              <span
                v-if="!d.is_active"
                class="px-2 py-0.5 text-xs rounded bg-red-500/20 text-red-400 border border-red-500/30"
              >
                停用
              </span>
            </div>
            <div v-if="d.room_ids.length > 0" class="flex flex-wrap gap-1 mt-2 ml-6">
              <span
                v-for="rid in d.room_ids"
                :key="rid"
                class="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700"
              >
                <Building2 class="w-3 h-3" />
                {{ getRoomName(rid) }}
              </span>
            </div>
            <div v-else class="text-xs text-slate-600 mt-1 ml-6">未指派房間</div>
          </div>

          <!-- Right: Chevron -->
          <ChevronRight class="w-5 h-5 text-slate-600 ml-4 shrink-0" />
        </div>
      </div>

      <!-- Empty State -->
      <div v-if="domains.length === 0" class="text-center py-12 text-slate-500">
        尚無網域綁定，點擊「新增網域」開始
      </div>

      <!-- Add Button (in list, not in header) -->
      <button
        @click.stop="openCreateDialog()"
        class="w-full flex items-center justify-center gap-2 py-3 bg-slate-900/30 hover:bg-slate-800/50 border border-dashed border-slate-700 hover:border-slate-600 rounded-xl text-sm text-slate-400 hover:text-slate-300 transition-all"
      >
        <Plus class="w-4 h-4" />
        新增網域
      </button>
    </div>

    <!-- Dialog: Create Domain -->
    <Teleport to="body">
      <div
        v-if="showCreateDialog"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
        @click.self="showCreateDialog = false"
      >
        <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-lg p-6 space-y-4 max-h-[85vh] overflow-y-auto">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-bold text-slate-200">新增網域</h3>
            <button @click="showCreateDialog = false" class="text-slate-400 hover:text-slate-200">
              <X class="w-5 h-5" />
            </button>
          </div>

          <div>
            <label class="block text-sm text-slate-400 mb-1">主機名稱 (hostname)</label>
            <input
              v-model="createForm.hostname"
              type="text"
              class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-500"
              placeholder="如：aegis.example.com"
            />
          </div>

          <div>
            <label class="block text-sm text-slate-400 mb-1">顯示名稱</label>
            <input
              v-model="createForm.name"
              type="text"
              class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-500"
              placeholder="如：公司內部站台"
            />
          </div>

          <div v-if="roomOptions.length > 0">
            <label class="block text-sm text-slate-400 mb-1">指派房間</label>
            <div class="space-y-1 max-h-40 overflow-y-auto">
              <label
                v-for="r in roomOptions"
                :key="r.id"
                class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer hover:bg-slate-800"
              >
                <input
                  type="checkbox"
                  :value="r.id"
                  v-model="createForm.room_ids"
                  class="rounded bg-slate-700 border-slate-600 text-emerald-500 focus:ring-emerald-500"
                />
                <span class="text-sm text-slate-300">{{ r.name }}</span>
              </label>
            </div>
          </div>

          <div class="flex items-center gap-3">
            <label class="text-sm text-slate-400">設為預設</label>
            <button
              @click="createForm.is_default = !createForm.is_default"
              :class="[
                'relative inline-flex h-6 w-11 items-center rounded-full transition-colors',
                createForm.is_default ? 'bg-amber-600' : 'bg-slate-600'
              ]"
            >
              <span
                :class="[
                  'inline-block h-4 w-4 transform rounded-full bg-white transition-transform',
                  createForm.is_default ? 'translate-x-6' : 'translate-x-1'
                ]"
              />
            </button>
          </div>

          <div class="flex justify-end gap-3 pt-2">
            <button
              @click="showCreateDialog = false"
              class="px-4 py-2 text-slate-400 hover:text-slate-200 transition"
            >
              取消
            </button>
            <button
              @click="createDomain"
              :disabled="creating || !createForm.hostname.trim()"
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
