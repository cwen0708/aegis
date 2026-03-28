<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Save, Loader2, Trash2, AlertTriangle } from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'
import { useDialogState } from '../../composables/useDialogState'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { config } from '../../config'
import { authHeaders } from '../../utils/authFetch'

const route = useRoute()
const router = useRouter()
const store = useAegisStore()
const API = config.apiUrl

const domainId = Number(route.params.id)
const loading = ref(true)

// 使用 useDialogState 管理表單和保存狀態
const { form, loading: saving } = useDialogState({
  initialForm: {
    hostname: '',
    name: '',
    is_default: false,
    is_active: true,
    require_login: false,
    show_onboarding: true,
  },
})

const confirmDelete = ref(false)

async function fetchDomain() {
  try {
    const res = await fetch(`${API}/api/v1/domains/${domainId}`, { headers: authHeaders() })
    if (!res.ok) throw new Error('載入失敗')
    const d = await res.json()
    // 使用 resetForm 更新表單數據
    form.value = {
      hostname: d.hostname,
      name: d.name || '',
      is_default: d.is_default,
      is_active: d.is_active ?? true,
      require_login: d.require_login ?? false,
      show_onboarding: d.show_onboarding ?? true,
    }
  } catch (e: any) {
    store.addToast(e.message || '網域載入失敗', 'error')
    router.push('/settings/domains')
  }
}

async function saveDomain() {
  if (!form.value.hostname.trim()) {
    store.addToast('請填寫主機名稱', 'error')
    return
  }
  saving.value = true
  try {
    const res = await fetch(`${API}/api/v1/domains/${domainId}`, {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(form.value),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '儲存失敗' }))
      throw new Error(err.detail)
    }
    store.addToast('網域已更新', 'success')
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
  saving.value = false
}

async function doDelete() {
  try {
    const res = await fetch(`${API}/api/v1/domains/${domainId}`, {
      method: 'DELETE',
      headers: authHeaders(),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '刪除失敗' }))
      throw new Error(err.detail)
    }
    store.addToast('網域已刪除', 'success')
    router.push('/settings/domains')
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}

onMounted(async () => {
  await fetchDomain()
  loading.value = false
})
</script>

<template>
  <div class="space-y-6">
    <Teleport to="#settings-header-actions">
      <button
        @click="saveDomain"
        :disabled="saving || !form.hostname.trim()"
        class="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded-lg text-xs font-medium transition-colors"
      >
        <Loader2 v-if="saving" class="w-3.5 h-3.5 animate-spin" />
        <Save v-else class="w-3.5 h-3.5" />
        儲存
      </button>
    </Teleport>

    <div class="flex items-center gap-3">
      <button @click="router.push('/settings/domains')" class="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 rounded-lg transition-colors">
        <ArrowLeft class="w-5 h-5" />
      </button>
      <h2 class="text-xl font-semibold text-slate-200">{{ form.hostname || '網域設定' }}</h2>
    </div>

    <div v-if="loading" class="flex justify-center py-12">
      <Loader2 class="w-8 h-8 animate-spin text-slate-400" />
    </div>

    <template v-else>
      <!-- 基本資訊 -->
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-6 space-y-4">
        <h3 class="text-sm font-bold text-slate-300 uppercase tracking-wider">基本資訊</h3>
        <div>
          <label class="block text-sm text-slate-400 mb-1">主機名稱 (hostname) <span class="text-red-400">*</span></label>
          <input v-model="form.hostname" type="text" class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-500" placeholder="如：aegis.example.com" />
        </div>
        <div>
          <label class="block text-sm text-slate-400 mb-1">顯示名稱</label>
          <input v-model="form.name" type="text" class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-500" placeholder="如：公司內部站台" />
        </div>
        <div class="flex items-center gap-3">
          <label class="text-sm text-slate-400">設為預設</label>
          <button @click="form.is_default = !form.is_default" :class="['relative inline-flex h-6 w-11 items-center rounded-full transition-colors', form.is_default ? 'bg-amber-600' : 'bg-slate-600']">
            <span :class="['inline-block h-4 w-4 transform rounded-full bg-white transition-transform', form.is_default ? 'translate-x-6' : 'translate-x-1']" />
          </button>
          <span class="text-xs text-slate-500">未匹配時的 fallback</span>
        </div>
        <div class="flex items-center gap-3">
          <label class="text-sm text-slate-400">啟用</label>
          <button @click="form.is_active = !form.is_active" :class="['relative inline-flex h-6 w-11 items-center rounded-full transition-colors', form.is_active ? 'bg-emerald-600' : 'bg-slate-600']">
            <span :class="['inline-block h-4 w-4 transform rounded-full bg-white transition-transform', form.is_active ? 'translate-x-6' : 'translate-x-1']" />
          </button>
        </div>
      </div>

      <!-- 存取控制 -->
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-6 space-y-4">
        <h3 class="text-sm font-bold text-slate-300 uppercase tracking-wider">存取控制</h3>
        <div class="flex items-center justify-between">
          <div>
            <span class="text-sm text-slate-300">強制登入才能瀏覽</span>
            <p class="text-xs text-slate-500 mt-0.5">開啟後，未登入的使用者會被導向登入畫面</p>
          </div>
          <button @click="form.require_login = !form.require_login" :class="['relative inline-flex h-6 w-11 items-center rounded-full transition-colors', form.require_login ? 'bg-amber-600' : 'bg-slate-600']">
            <span :class="['inline-block h-4 w-4 transform rounded-full bg-white transition-transform', form.require_login ? 'translate-x-6' : 'translate-x-1']" />
          </button>
        </div>
        <div class="flex items-center justify-between">
          <div>
            <span class="text-sm text-slate-300">顯示設定引導頁</span>
            <p class="text-xs text-slate-500 mt-0.5">關閉後，此網域不會顯示初始設定引導</p>
          </div>
          <button @click="form.show_onboarding = !form.show_onboarding" :class="['relative inline-flex h-6 w-11 items-center rounded-full transition-colors', form.show_onboarding ? 'bg-emerald-600' : 'bg-slate-600']">
            <span :class="['inline-block h-4 w-4 transform rounded-full bg-white transition-transform', form.show_onboarding ? 'translate-x-6' : 'translate-x-1']" />
          </button>
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
            <span class="text-sm text-slate-300">刪除網域</span>
            <p class="text-xs text-slate-500">此操作無法復原。</p>
          </div>
          <button @click="confirmDelete = true" class="flex items-center gap-2 px-4 py-2 text-red-400 hover:text-red-300 hover:bg-red-500/10 border border-red-500/30 rounded-lg transition text-sm">
            <Trash2 class="w-4 h-4" />
            刪除網域
          </button>
        </div>
      </div>
    </template>

    <ConfirmDialog :show="confirmDelete" title="刪除網域" :message="`確定要刪除網域「${form.hostname}」？此操作無法復原。`" confirm-text="刪除" @confirm="doDelete" @cancel="confirmDelete = false" />
  </div>
</template>
