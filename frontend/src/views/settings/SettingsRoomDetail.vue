<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Save, Loader2, Trash2, AlertTriangle, Users } from 'lucide-vue-next'
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

interface MemberOption { id: number; name: string; avatar: string }

const form = ref({
  name: '',
  description: '',
  allow_anonymous: false,
  member_ids: [] as number[],
})

const members = ref<MemberOption[]>([])

async function fetchRoom() {
  try {
    const res = await fetch(`${API}/api/v1/rooms/${roomId}`, { headers: authHeaders() })
    if (!res.ok) throw new Error('載入失敗')
    const room = await res.json()
    form.value = {
      name: room.name,
      description: room.description,
      allow_anonymous: room.allow_anonymous ?? false,
      member_ids: [...(room.member_ids || [])],
    }
  } catch (e: any) {
    store.addToast(e.message || '空間載入失敗', 'error')
    router.push('/settings/rooms')
  }
}

async function fetchMembers() {
  try {
    const res = await fetch(`${API}/api/v1/members?all=true`, { headers: authHeaders() })
    if (res.ok) members.value = await res.json()
  } catch {}
}

async function saveRoom() {
  if (!form.value.name.trim()) {
    store.addToast('請填寫空間名稱', 'error')
    return
  }
  saving.value = true
  try {
    const res = await fetch(`${API}/api/v1/rooms/${roomId}`, {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        name: form.value.name,
        description: form.value.description,
        allow_anonymous: form.value.allow_anonymous,
      }),
    })
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || '儲存失敗')

    const memRes = await fetch(`${API}/api/v1/rooms/${roomId}/members`, {
      method: 'PUT',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ member_ids: form.value.member_ids }),
    })
    if (!memRes.ok) throw new Error('成員綁定失敗')

    store.addToast('空間已更新', 'success')
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
  saving.value = false
}

async function doDelete() {
  try {
    const res = await fetch(`${API}/api/v1/rooms/${roomId}`, { method: 'DELETE', headers: authHeaders() })
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || '刪除失敗')
    store.addToast('空間已刪除', 'success')
    router.push('/settings/rooms')
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}

onMounted(async () => {
  await Promise.all([fetchRoom(), fetchMembers()])
  loading.value = false
})
</script>

<template>
  <div class="space-y-6">
    <Teleport to="#settings-header-actions">
      <button @click="saveRoom" :disabled="saving || !form.name.trim()" class="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded-lg text-xs font-medium transition-colors">
        <Loader2 v-if="saving" class="w-3.5 h-3.5 animate-spin" />
        <Save v-else class="w-3.5 h-3.5" />
        儲存
      </button>
    </Teleport>

    <div class="flex items-center gap-3">
      <button @click="router.push('/settings/rooms')" class="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 rounded-lg transition-colors">
        <ArrowLeft class="w-5 h-5" />
      </button>
      <h2 class="text-xl font-semibold text-slate-200">{{ form.name || '空間設定' }}</h2>
    </div>

    <div v-if="loading" class="flex justify-center py-12">
      <Loader2 class="w-8 h-8 animate-spin text-slate-400" />
    </div>

    <template v-else>
      <!-- 基本資訊 -->
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-6 space-y-4">
        <h3 class="text-sm font-bold text-slate-300 uppercase tracking-wider">基本資訊</h3>
        <div>
          <label class="block text-sm text-slate-400 mb-1">空間名稱 <span class="text-red-400">*</span></label>
          <input v-model="form.name" type="text" class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-500" placeholder="如：研發部" />
        </div>
        <div>
          <label class="block text-sm text-slate-400 mb-1">描述</label>
          <input v-model="form.description" type="text" class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-500" />
        </div>
        <div class="flex items-center justify-between">
          <div>
            <span class="text-sm text-slate-300">允許未登入瀏覽</span>
            <p class="text-xs text-slate-500 mt-0.5">開啟後，未登入的使用者也能看到此空間</p>
          </div>
          <button @click="form.allow_anonymous = !form.allow_anonymous" :class="['relative inline-flex h-6 w-11 items-center rounded-full transition-colors', form.allow_anonymous ? 'bg-emerald-600' : 'bg-slate-600']">
            <span :class="['inline-block h-4 w-4 transform rounded-full bg-white transition-transform', form.allow_anonymous ? 'translate-x-6' : 'translate-x-1']" />
          </button>
        </div>
      </div>

      <!-- AI 成員 -->
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-6 space-y-4">
        <div class="flex items-center gap-2">
          <Users class="w-4 h-4 text-sky-400" />
          <h3 class="text-sm font-bold text-slate-300 uppercase tracking-wider">AI 成員</h3>
          <span class="text-xs text-slate-500 ml-auto">{{ form.member_ids.length }} / {{ members.length }}</span>
        </div>
        <div v-if="members.length === 0" class="text-center py-6 text-slate-500 text-sm">尚無可用成員</div>
        <div v-else class="space-y-1 max-h-60 overflow-y-auto">
          <label v-for="m in members" :key="m.id" class="flex items-center gap-2 px-3 py-2 bg-slate-900 rounded-lg cursor-pointer hover:bg-slate-800">
            <input type="checkbox" :value="m.id" v-model="form.member_ids" class="rounded bg-slate-700 border-slate-600 text-sky-500 focus:ring-sky-500" />
            <span class="text-sm text-slate-300">{{ m.avatar }} {{ m.name }}</span>
          </label>
        </div>
      </div>

      <!-- 危險區域 -->
      <div class="bg-slate-800/50 rounded-2xl border border-red-500/20 p-6 space-y-4">
        <div class="flex items-center gap-2">
          <AlertTriangle class="w-4 h-4 text-red-400" />
          <h3 class="text-sm font-bold text-red-400 uppercase tracking-wider">危險區域</h3>
        </div>
        <div class="flex items-center justify-between">
          <div>
            <span class="text-sm text-slate-300">刪除空間</span>
            <p class="text-xs text-slate-500">不會刪除專案和成員，只移除分組。</p>
          </div>
          <button @click="confirmDelete = true" class="flex items-center gap-2 px-4 py-2 text-red-400 hover:text-red-300 hover:bg-red-500/10 border border-red-500/30 rounded-lg transition text-sm">
            <Trash2 class="w-4 h-4" />
            刪除空間
          </button>
        </div>
      </div>
    </template>

    <ConfirmDialog :show="confirmDelete" title="刪除空間" :message="`確定要刪除空間「${form.name}」？`" confirm-text="刪除" @confirm="doDelete" @cancel="confirmDelete = false" />
  </div>
</template>
