<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { Archive, RotateCcw, Trash2, Loader2 } from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'
import { authHeaders } from '../../utils/authFetch'

const store = useAegisStore()

interface ArchivedCard {
  id: number
  title: string
  description: string | null
  status: string
  list_id: number
  created_at: string
  updated_at: string
}

interface Project {
  id: number
  name: string
}

const loading = ref(true)
const projects = ref<Project[]>([])
const selectedProjectId = ref<number | null>(null)
const archivedCards = ref<ArchivedCard[]>([])
const actionLoading = ref<number | null>(null)

async function fetchProjects() {
  try {
    const res = await fetch('/api/v1/projects/')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    projects.value = await res.json()
    if (projects.value.length > 0 && !selectedProjectId.value) {
      selectedProjectId.value = projects.value[0]?.id ?? null
    }
  } catch (e: any) {
    store.addToast('載入專案失敗', 'error')
  }
}

async function fetchArchivedCards() {
  if (!selectedProjectId.value) return
  loading.value = true
  try {
    const res = await fetch(`/api/v1/projects/${selectedProjectId.value}/archived`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    archivedCards.value = await res.json()
  } catch (e: any) {
    store.addToast('載入封存卡片失敗', 'error')
  } finally {
    loading.value = false
  }
}

async function unarchiveCard(cardId: number) {
  actionLoading.value = cardId
  try {
    const res = await fetch(`/api/v1/cards/${cardId}/unarchive`, { method: 'POST', headers: authHeaders() })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    store.addToast('卡片已恢復', 'success')
    await fetchArchivedCards()
  } catch (e: any) {
    store.addToast(e.message || '恢復失敗', 'error')
  } finally {
    actionLoading.value = null
  }
}

async function deleteCard(cardId: number) {
  if (!confirm('確定要永久刪除這張卡片？此操作無法復原。')) return
  actionLoading.value = cardId
  try {
    const res = await fetch(`/api/v1/cards/${cardId}`, { method: 'DELETE', headers: authHeaders() })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    store.addToast('卡片已刪除', 'success')
    await fetchArchivedCards()
  } catch (e: any) {
    store.addToast(e.message || '刪除失敗', 'error')
  } finally {
    actionLoading.value = null
  }
}

watch(selectedProjectId, () => {
  fetchArchivedCards()
})

onMounted(() => {
  fetchProjects()
})
</script>

<template>
  <div class="max-w-3xl">
    <div class="flex items-center gap-3 mb-6">
      <div class="p-2.5 rounded-xl bg-slate-700/50">
        <Archive class="w-5 h-5 text-slate-400" />
      </div>
      <div>
        <h2 class="text-lg font-bold text-slate-100">封存卡片</h2>
        <p class="text-xs text-slate-500">查看已封存的卡片，可恢復或永久刪除</p>
      </div>
    </div>

    <!-- Project Selector -->
    <div class="mb-6">
      <label class="block text-xs font-medium text-slate-400 mb-1.5">選擇專案</label>
      <select
        v-model="selectedProjectId"
        class="w-64 bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none text-sm"
      >
        <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex items-center gap-2 text-slate-500 py-8">
      <Loader2 class="w-4 h-4 animate-spin" />
      載入中...
    </div>

    <!-- Empty State -->
    <div v-else-if="archivedCards.length === 0" class="text-center py-12 text-slate-500">
      <Archive class="w-12 h-12 mx-auto mb-3 opacity-30" />
      <p class="text-sm">此專案沒有封存的卡片</p>
    </div>

    <!-- Card List -->
    <div v-else class="space-y-3">
      <div
        v-for="card in archivedCards"
        :key="card.id"
        class="flex items-center justify-between p-4 bg-slate-800/50 rounded-xl border border-slate-700"
      >
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2 mb-1">
            <span class="text-[10px] font-bold text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded">C-{{ card.id }}</span>
            <span
              class="text-[10px] font-bold px-2 py-0.5 rounded"
              :class="{
                'bg-green-500/10 text-green-400': card.status === 'completed',
                'bg-red-500/10 text-red-400': card.status === 'failed',
                'bg-slate-500/10 text-slate-400': card.status === 'idle',
              }"
            >{{ card.status }}</span>
          </div>
          <div class="text-sm text-slate-200 truncate">{{ card.title }}</div>
          <div class="text-[10px] text-slate-500 mt-1">
            封存於 {{ new Date(card.updated_at).toLocaleString('zh-TW', { timeZone: store.settings.timezone || 'Asia/Taipei' }) }}
          </div>
        </div>
        <div class="flex items-center gap-2 ml-4">
          <button
            @click="unarchiveCard(card.id)"
            :disabled="actionLoading !== null"
            class="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 rounded-lg text-xs font-medium transition-colors disabled:opacity-50"
          >
            <Loader2 v-if="actionLoading === card.id" class="w-3 h-3 animate-spin" />
            <RotateCcw v-else class="w-3 h-3" />
            恢復
          </button>
          <button
            @click="deleteCard(card.id)"
            :disabled="actionLoading !== null"
            class="flex items-center gap-1.5 px-3 py-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 rounded-lg text-xs font-medium transition-colors disabled:opacity-50"
          >
            <Trash2 class="w-3 h-3" />
            刪除
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
