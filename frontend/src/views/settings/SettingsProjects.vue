<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { FolderKanban, Plus, Edit3, Trash2, FolderOpen, Lock, Loader2, UserCircle } from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'
import ConfirmDialog from '../../components/ConfirmDialog.vue'

const store = useAegisStore()
const API = import.meta.env.DEV ? '' : 'http://localhost:8899'

interface MemberOption {
  id: number
  name: string
  avatar: string
  provider: string
}

interface ProjectInfo {
  id: number
  name: string
  path: string
  default_member_id: number | null
  is_active: boolean
  is_system: boolean
  created_at: string
}

const loading = ref(true)
const saving = ref(false)
const projects = ref<ProjectInfo[]>([])
const members = ref<MemberOption[]>([])

// Dialog
const showDialog = ref(false)
const editingProject = ref<ProjectInfo | null>(null)
const form = ref({
  name: '',
  path: '',
  default_member_id: null as number | null,
})

// Delete confirm
const confirmDelete = ref(false)
const deleteTarget = ref<ProjectInfo | null>(null)

async function fetchProjects() {
  loading.value = true
  try {
    const res = await fetch(`${API}/api/v1/projects/`)
    if (!res.ok) throw new Error('載入失敗')
    projects.value = await res.json()
  } catch (e: any) {
    store.addToast(e.message || '專案載入失敗', 'error')
  }
  loading.value = false
}

async function fetchMembers() {
  try {
    const res = await fetch(`${API}/api/v1/members`)
    if (res.ok) members.value = await res.json()
  } catch {}
}

onMounted(() => {
  fetchProjects()
  fetchMembers()
})

function openDialog(project?: ProjectInfo) {
  if (project) {
    editingProject.value = project
    form.value = {
      name: project.name,
      path: project.path,
      default_member_id: project.default_member_id,
    }
  } else {
    editingProject.value = null
    form.value = { name: '', path: '', default_member_id: null }
  }
  showDialog.value = true
}

async function saveProject() {
  if (!form.value.name.trim() || !form.value.path.trim()) {
    store.addToast('請填寫名稱和路徑', 'error')
    return
  }
  saving.value = true
  try {
    const url = editingProject.value
      ? `${API}/api/v1/projects/${editingProject.value.id}`
      : `${API}/api/v1/projects/`
    const method = editingProject.value ? 'PATCH' : 'POST'
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '儲存失敗' }))
      throw new Error(err.detail)
    }
    store.addToast(editingProject.value ? '專案已更新' : '專案已建立', 'success')
    showDialog.value = false
    await fetchProjects()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
  saving.value = false
}

function requestDelete(project: ProjectInfo) {
  deleteTarget.value = project
  confirmDelete.value = true
}

async function doDelete() {
  if (!deleteTarget.value) return
  try {
    const res = await fetch(`${API}/api/v1/projects/${deleteTarget.value.id}`, { method: 'DELETE' })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '刪除失敗' }))
      throw new Error(err.detail)
    }
    store.addToast('專案已刪除', 'success')
    confirmDelete.value = false
    deleteTarget.value = null
    showDialog.value = false  // 關閉編輯對話框
    await fetchProjects()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}

async function toggleActive(project: ProjectInfo) {
  try {
    const res = await fetch(`${API}/api/v1/projects/${project.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: !project.is_active }),
    })
    if (!res.ok) throw new Error('更新失敗')
    await fetchProjects()
  } catch {
    store.addToast('狀態更新失敗', 'error')
  }
}

function getMemberName(memberId: number | null): string {
  if (!memberId) return ''
  const m = members.value.find(m => m.id === memberId)
  return m ? m.name : ''
}

function getMemberAvatar(memberId: number | null): string {
  if (!memberId) return ''
  const m = members.value.find(m => m.id === memberId)
  return m?.avatar || ''
}

function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleDateString('zh-TW')
}
</script>

<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-3">
        <FolderKanban class="w-6 h-6 text-emerald-400" />
        <h2 class="text-xl font-semibold">專案管理</h2>
      </div>
      <button
        @click="openDialog()"
        class="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 rounded-lg transition"
      >
        <Plus class="w-4 h-4" />
        新增專案
      </button>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex justify-center py-12">
      <Loader2 class="w-8 h-8 animate-spin text-slate-400" />
    </div>

    <!-- Project List -->
    <div v-else class="space-y-3">
      <div
        v-for="project in projects"
        :key="project.id"
        class="bg-slate-900/50 rounded-xl border border-slate-700/50 p-4"
      >
        <div class="flex items-center justify-between">
          <!-- Left: Info -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <span class="font-medium text-slate-200">{{ project.name }}</span>
              <Lock v-if="project.is_system" class="w-4 h-4 text-slate-500" title="系統專案" />
              <span
                v-if="project.default_member_id"
                class="flex items-center gap-1 px-2 py-0.5 text-xs rounded border bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
              >
                <span>{{ getMemberAvatar(project.default_member_id) }}</span>
                {{ getMemberName(project.default_member_id) }}
              </span>
              <span
                v-if="!project.is_active"
                class="px-2 py-0.5 text-xs rounded bg-red-500/20 text-red-400 border border-red-500/30"
              >
                停用
              </span>
            </div>
            <div class="flex items-center gap-2 mt-1 text-sm text-slate-500">
              <FolderOpen class="w-4 h-4" />
              <span class="truncate">{{ project.path }}</span>
            </div>
            <div class="text-xs text-slate-600 mt-1">
              建立於 {{ formatDate(project.created_at) }}
            </div>
          </div>

          <!-- Right: Actions -->
          <div class="flex items-center gap-2 ml-4">
            <button
              v-if="!project.is_system"
              @click="toggleActive(project)"
              :class="[
                'px-3 py-1.5 text-sm rounded-lg transition',
                project.is_active
                  ? 'bg-slate-700 hover:bg-slate-600 text-slate-300'
                  : 'bg-emerald-600 hover:bg-emerald-500 text-white'
              ]"
            >
              {{ project.is_active ? '停用' : '啟用' }}
            </button>
            <button
              @click="openDialog(project)"
              class="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-700 rounded-lg transition"
              title="編輯"
            >
              <Edit3 class="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      <!-- Empty State -->
      <div v-if="projects.length === 0" class="text-center py-12 text-slate-500">
        尚無專案，點擊「新增專案」開始
      </div>
    </div>

    <!-- Dialog: Add/Edit Project -->
    <Teleport to="body">
      <div
        v-if="showDialog"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
        @click.self="showDialog = false"
      >
        <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-md p-6 space-y-4">
          <h3 class="text-lg font-semibold">
            {{ editingProject ? '編輯專案' : '新增專案' }}
          </h3>

          <div class="space-y-4">
            <!-- Name -->
            <div>
              <label class="block text-sm text-slate-400 mb-1">專案名稱</label>
              <input
                v-model="form.name"
                type="text"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-500"
                placeholder="如：Infinite Novel"
                :disabled="editingProject?.is_system"
              />
            </div>

            <!-- Path -->
            <div>
              <label class="block text-sm text-slate-400 mb-1">專案路徑</label>
              <input
                v-model="form.path"
                type="text"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-500"
                placeholder="如：G:\Projects\infinite-novel"
              />
              <p class="text-xs text-slate-500 mt-1">
                卡片檔案存放於此路徑的 .aegis/cards/ 目錄下
              </p>
            </div>

            <!-- Default Member -->
            <div>
              <label class="block text-sm text-slate-400 mb-1">預設成員</label>
              <select
                v-model="form.default_member_id"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500"
              >
                <option :value="null">無（使用全域設定）</option>
                <option v-for="m in members" :key="m.id" :value="m.id">
                  {{ m.avatar }} {{ m.name }} ({{ m.provider }})
                </option>
              </select>
              <p class="text-xs text-slate-500 mt-1">
                列表沒有指派成員時使用
              </p>
            </div>

          </div>

          <!-- Actions -->
          <div class="flex justify-between pt-2">
            <!-- Left: Delete (only when editing non-system project) -->
            <div>
              <button
                v-if="editingProject && !editingProject.is_system"
                @click="requestDelete(editingProject)"
                class="flex items-center gap-2 px-4 py-2 text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg transition"
              >
                <Trash2 class="w-4 h-4" />
                刪除專案
              </button>
            </div>
            <!-- Right: Cancel & Save -->
            <div class="flex gap-3">
              <button
                @click="showDialog = false"
                class="px-4 py-2 text-slate-400 hover:text-slate-200 transition"
              >
                取消
              </button>
              <button
                @click="saveProject"
                :disabled="saving || !form.name.trim() || !form.path.trim()"
                class="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition"
              >
                <Loader2 v-if="saving" class="w-4 h-4 animate-spin" />
                {{ editingProject ? '儲存' : '建立' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Confirm Delete -->
    <ConfirmDialog
      v-model:show="confirmDelete"
      title="刪除專案"
      :message="`確定要刪除「${deleteTarget?.name}」？此操作會刪除所有相關的卡片和資料。`"
      confirm-text="刪除"
      @confirm="doDelete"
    />
  </div>
</template>
