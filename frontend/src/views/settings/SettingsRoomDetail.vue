<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft, Save, Loader2, Trash2, AlertTriangle, FolderKanban, Users,
} from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { config } from '../../config'
import { authHeaders } from '../../utils/authFetch'

const route = useRoute()
const router = useRouter()
const store = useAegisStore()
const API = config.apiUrl

const roomId = Number(route.params.id)
const loading = ref(true)
const saving = ref(false)
const confirmDelete = ref(false)

// ── Types ──

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

// ── Form ──

const form = ref({
  name: '',
  description: '',
  project_ids: [] as number[],
  member_ids: [] as number[],
})

const projects = ref<ProjectOption[]>([])
const members = ref<MemberOption[]>([])

// ── Fetch ──

async function fetchRoom() {
  try {
    const res = await fetch(`${API}/api/v1/rooms/${roomId}`, { headers: authHeaders() })
    if (!res.ok) throw new Error('載入失敗')
    const room: RoomInfo = await res.json()
    form.value = {
      name: room.name,
      description: room.description,
      project_ids: [...room.project_ids],
      member_ids: [...room.member_ids],
    }
  } catch (e: any) {
    store.addToast(e.message || '房間載入失敗', 'error')
    router.push('/settings/rooms')
  }
}

async function fetchProjects() {
  try {
    const res = await fetch(`${API}/api/v1/projects/?all=true`, { headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      projects.value = data.map((p: any) => ({ id: p.id, name: p.name }))
    }
  } catch {}
}

async function fetchMembers() {
  try {
    const res = await fetch(`${API}/api/v1/members?all=true`, { headers: authHeaders() })
    if (res.ok) members.value = await res.json()
  } catch {}
}

// ── Save ──

async function saveRoom() {
  if (!form.value.name.trim()) {
    store.addToast('請填寫房間名稱', 'error')
    return
  }
  saving.value = true
  try {
    // 1. 更新基本資訊
    const res = await fetch(`${API}/api/v1/rooms/${roomId}`, {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ name: form.value.name, description: form.value.description }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '儲存失敗' }))
      throw new Error(err.detail)
    }
    // 2. 更新專案綁定
    const projRes = await fetch(`${API}/api/v1/rooms/${roomId}/projects`, {
      method: 'PUT',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ project_ids: form.value.project_ids }),
    })
    if (!projRes.ok) throw new Error('專案綁定失敗')
    // 3. 更新成員綁定
    const memRes = await fetch(`${API}/api/v1/rooms/${roomId}/members`, {
      method: 'PUT',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ member_ids: form.value.member_ids }),
    })
    if (!memRes.ok) throw new Error('成員綁定失敗')

    store.addToast('房間已更新', 'success')
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
  saving.value = false
}

// ── Delete ──

async function doDelete() {
  try {
    const res = await fetch(`${API}/api/v1/rooms/${roomId}`, {
      method: 'DELETE',
      headers: authHeaders(),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '刪除失敗' }))
      throw new Error(err.detail)
    }
    store.addToast('房間已刪除', 'success')
    router.push('/settings/rooms')
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}

// ── Init ──

onMounted(async () => {
  await Promise.all([fetchRoom(), fetchProjects(), fetchMembers()])
  loading.value = false
})
</script>

<template>
  <div class="space-y-6">
    <!-- Header actions via Teleport -->
    <Teleport to="#settings-header-actions">
      <button
        @click="saveRoom"
        :disabled="saving || !form.name.trim()"
        class="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded-lg text-xs font-medium transition-colors"
      >
        <Loader2 v-if="saving" class="w-3.5 h-3.5 animate-spin" />
        <Save v-else class="w-3.5 h-3.5" />
        儲存
      </button>
    </Teleport>

    <!-- Header -->
    <div class="flex items-center gap-3">
      <button
        @click="router.push('/settings/rooms')"
        class="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 rounded-lg transition-colors"
      >
        <ArrowLeft class="w-5 h-5" />
      </button>
      <h2 class="text-xl font-semibold text-slate-200">{{ form.name || '房間設定' }}</h2>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex justify-center py-12">
      <Loader2 class="w-8 h-8 animate-spin text-slate-400" />
    </div>

    <template v-else>
      <!-- Section 1: 基本資訊 -->
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-6 space-y-4">
        <h3 class="text-sm font-bold text-slate-300 uppercase tracking-wider">基本資訊</h3>

        <div class="space-y-4">
          <div>
            <label class="block text-sm text-slate-400 mb-1">房間名稱 <span class="text-red-400">*</span></label>
            <input
              v-model="form.name"
              type="text"
              class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-500"
              placeholder="如：前端團隊"
            />
          </div>

          <div>
            <label class="block text-sm text-slate-400 mb-1">描述</label>
            <input
              v-model="form.description"
              type="text"
              class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-500"
              placeholder="如：前端相關專案和成員"
            />
          </div>
        </div>
      </div>

      <!-- Section 2: 關聯專案 -->
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-6 space-y-4">
        <div class="flex items-center gap-2">
          <FolderKanban class="w-4 h-4 text-emerald-400" />
          <h3 class="text-sm font-bold text-slate-300 uppercase tracking-wider">關聯專案</h3>
          <span class="text-xs text-slate-500 ml-auto">{{ form.project_ids.length }} / {{ projects.length }}</span>
        </div>

        <div v-if="projects.length === 0" class="text-center py-6 text-slate-500 text-sm">
          尚無可用專案
        </div>

        <div v-else class="space-y-1 max-h-60 overflow-y-auto">
          <label
            v-for="p in projects"
            :key="p.id"
            class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer hover:bg-slate-800"
          >
            <input
              type="checkbox"
              :value="p.id"
              v-model="form.project_ids"
              class="rounded bg-slate-700 border-slate-600 text-emerald-500 focus:ring-emerald-500"
            />
            <span class="text-sm text-slate-300">{{ p.name }}</span>
          </label>
        </div>
      </div>

      <!-- Section 3: 關聯成員 -->
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-6 space-y-4">
        <div class="flex items-center gap-2">
          <Users class="w-4 h-4 text-sky-400" />
          <h3 class="text-sm font-bold text-slate-300 uppercase tracking-wider">關聯成員</h3>
          <span class="text-xs text-slate-500 ml-auto">{{ form.member_ids.length }} / {{ members.length }}</span>
        </div>

        <div v-if="members.length === 0" class="text-center py-6 text-slate-500 text-sm">
          尚無可用成員
        </div>

        <div v-else class="space-y-1 max-h-60 overflow-y-auto">
          <label
            v-for="m in members"
            :key="m.id"
            class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer hover:bg-slate-800"
          >
            <input
              type="checkbox"
              :value="m.id"
              v-model="form.member_ids"
              class="rounded bg-slate-700 border-slate-600 text-sky-500 focus:ring-sky-500"
            />
            <span class="text-sm text-slate-300">{{ m.avatar }} {{ m.name }}</span>
          </label>
        </div>
      </div>

      <!-- Section 4: 危險區域 -->
      <div class="bg-slate-800/50 rounded-2xl border border-red-500/20 p-6 space-y-4">
        <div class="flex items-center gap-2">
          <AlertTriangle class="w-4 h-4 text-red-400" />
          <h3 class="text-sm font-bold text-red-400 uppercase tracking-wider">危險區域</h3>
        </div>
        <div class="flex items-center justify-between">
          <div>
            <span class="text-sm text-slate-300">刪除房間</span>
            <p class="text-xs text-slate-500">此操作不會刪除房間內的專案和成員，只會移除房間的分組設定。</p>
          </div>
          <button
            @click="confirmDelete = true"
            class="flex items-center gap-2 px-4 py-2 text-red-400 hover:text-red-300 hover:bg-red-500/10 border border-red-500/30 rounded-lg transition text-sm"
          >
            <Trash2 class="w-4 h-4" />
            刪除房間
          </button>
        </div>
      </div>
    </template>

    <!-- Confirm Delete -->
    <ConfirmDialog
      :show="confirmDelete"
      title="刪除房間"
      :message="`確定要刪除房間「${form.name}」？\n此操作不會刪除房間內的專案和成員，只會移除房間的分組設定。`"
      confirm-text="刪除"
      @confirm="doDelete"
      @cancel="confirmDelete = false"
    />
  </div>
</template>
