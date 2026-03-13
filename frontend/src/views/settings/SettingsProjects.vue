<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { FolderKanban, Plus, Edit3, Trash2, FolderOpen, Lock, Loader2, Github, FolderInput, Search, Globe, ChevronRight } from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'
import ConfirmDialog from '../../components/ConfirmDialog.vue'

import { config } from '../../config'
import { authHeaders } from '../../utils/authFetch'

const store = useAegisStore()
const API = config.apiUrl

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

interface GitHubRepo {
  full_name: string
  name: string
  clone_url: string
  description: string | null
  private: boolean
  default_branch: string
}

const loading = ref(true)
const saving = ref(false)
const projects = ref<ProjectInfo[]>([])
const members = ref<MemberOption[]>([])

// Dialog
const showDialog = ref(false)
const editingProject = ref<ProjectInfo | null>(null)
const createMode = ref<'local' | 'github'>('local')
const form = ref({
  name: '',
  path: '',
  default_member_id: null as number | null,
})

// GitHub mode
const githubUrl = ref('')
const githubParsing = ref(false)
const githubRepos = ref<GitHubRepo[]>([])
const githubReposLoading = ref(false)
const githubSearch = ref('')
const githubSearchTimeout = ref<ReturnType<typeof setTimeout> | null>(null)
const githubSelectedRepo = ref<GitHubRepo | null>(null)
const githubConnected = ref(false)
const cloning = ref(false)
const cloneStatus = ref('')

// Relocate
const showRelocate = ref(false)
const relocatePath = ref('')
const relocateSaving = ref(false)
const confirmRelocate = ref(false)

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

async function checkGithubStatus() {
  try {
    const res = await fetch(`${API}/api/v1/github/status`)
    if (res.ok) {
      const data = await res.json()
      githubConnected.value = data.connected
    }
  } catch {}
}

onMounted(() => {
  fetchProjects()
  fetchMembers()
  checkGithubStatus()
})

function openDialog(project?: ProjectInfo) {
  if (project) {
    editingProject.value = project
    form.value = {
      name: project.name,
      path: project.path,
      default_member_id: project.default_member_id,
    }
    showRelocate.value = false
    relocatePath.value = ''
  } else {
    editingProject.value = null
    form.value = { name: '', path: '', default_member_id: null }
    createMode.value = 'local'
    githubUrl.value = ''
    githubSelectedRepo.value = null
    cloning.value = false
    cloneStatus.value = ''
  }
  showDialog.value = true
}

// --- Local create / edit ---
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
      headers: authHeaders({ 'Content-Type': 'application/json' }),
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

// --- GitHub: Parse URL ---
async function parseGithubUrl() {
  const url = githubUrl.value.trim()
  if (!url) return
  githubParsing.value = true
  try {
    const res = await fetch(`${API}/api/v1/github/parse-url`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ url }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '無效的 URL' }))
      throw new Error(err.detail)
    }
    const data = await res.json()
    form.value.name = data.suggested_name
    form.value.path = `~/projects/${data.suggested_name}`
    githubSelectedRepo.value = {
      full_name: data.full_name,
      name: data.repo,
      clone_url: data.clone_url,
      description: null,
      private: false,
      default_branch: 'main',
    }
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
  githubParsing.value = false
}

// --- GitHub: Browse repos ---
async function fetchGithubRepos(search = '') {
  githubReposLoading.value = true
  try {
    const params = new URLSearchParams({ per_page: '30', page: '1' })
    if (search) params.set('search', search)
    const res = await fetch(`${API}/api/v1/github/repos?${params}`)
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '載入失敗' }))
      throw new Error(err.detail)
    }
    githubRepos.value = await res.json()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
  githubReposLoading.value = false
}

function onGithubSearchInput() {
  if (githubSearchTimeout.value) clearTimeout(githubSearchTimeout.value)
  githubSearchTimeout.value = setTimeout(() => {
    fetchGithubRepos(githubSearch.value)
  }, 400)
}

function selectGithubRepo(repo: GitHubRepo) {
  githubSelectedRepo.value = repo
  form.value.name = repo.name
  form.value.path = `~/projects/${repo.name}`
}

// --- GitHub: Clone ---
function onCloneProgress(e: Event) {
  const detail = (e as CustomEvent).detail
  if (detail.status === 'done') {
    cloning.value = false
    cloneStatus.value = ''
    store.addToast('Clone 完成，專案已建立', 'success')
    showDialog.value = false
    fetchProjects()
  } else if (detail.status === 'error') {
    cloning.value = false
    cloneStatus.value = ''
    store.addToast(detail.message || 'Clone 失敗', 'error')
  }
}

onMounted(() => {
  window.addEventListener('aegis:clone-progress', onCloneProgress)
})
onUnmounted(() => {
  window.removeEventListener('aegis:clone-progress', onCloneProgress)
})

async function startClone() {
  if (!githubSelectedRepo.value || !form.value.path.trim() || !form.value.name.trim()) {
    store.addToast('請選擇 repo 並填寫路徑', 'error')
    return
  }
  cloning.value = true
  cloneStatus.value = '正在 clone...'
  try {
    const res = await fetch(`${API}/api/v1/github/clone`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        repo_url: githubSelectedRepo.value.clone_url,
        destination: form.value.path,
        project_name: form.value.name,
        default_member_id: form.value.default_member_id,
      }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Clone 請求失敗' }))
      throw new Error(err.detail)
    }
    const data = await res.json()
    // 開始 polling fallback（WebSocket 可能沒連上）
    pollCloneStatus(data.task_id)
  } catch (e: any) {
    cloning.value = false
    cloneStatus.value = ''
    store.addToast(e.message, 'error')
  }
}

async function pollCloneStatus(taskId: string) {
  // 最多 polling 120 次（約 4 分鐘）
  for (let i = 0; i < 120; i++) {
    if (!cloning.value) return // 已被 WebSocket callback 處理
    await new Promise(r => setTimeout(r, 2000))
    if (!cloning.value) return
    try {
      const res = await fetch(`${API}/api/v1/github/clone/${taskId}`)
      if (!res.ok) continue
      const data = await res.json()
      if (data.status === 'done') {
        cloning.value = false
        cloneStatus.value = ''
        store.addToast('Clone 完成，專案已建立', 'success')
        showDialog.value = false
        fetchProjects()
        return
      } else if (data.status === 'error') {
        cloning.value = false
        cloneStatus.value = ''
        store.addToast(data.message || 'Clone 失敗', 'error')
        return
      }
    } catch {}
  }
  cloning.value = false
  cloneStatus.value = ''
  store.addToast('Clone 逾時', 'error')
}

// --- Relocate ---
async function doRelocate() {
  if (!editingProject.value || !relocatePath.value.trim()) return
  relocateSaving.value = true
  try {
    const res = await fetch(`${API}/api/v1/projects/${editingProject.value.id}/relocate`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ new_path: relocatePath.value.trim() }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '搬移失敗' }))
      throw new Error(err.detail)
    }
    store.addToast('專案目錄已搬移', 'success')
    showRelocate.value = false
    relocatePath.value = ''
    await fetchProjects()
    // 更新 form 中的 path
    const updated = await res.json().catch(() => null)
    if (updated) form.value.path = updated.path
    else showDialog.value = false
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
  relocateSaving.value = false
}

// --- Delete ---
function requestDelete(project: ProjectInfo) {
  deleteTarget.value = project
  confirmDelete.value = true
}

async function doDelete() {
  if (!deleteTarget.value) return
  try {
    const res = await fetch(`${API}/api/v1/projects/${deleteTarget.value.id}`, { method: 'DELETE', headers: authHeaders() })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '刪除失敗' }))
      throw new Error(err.detail)
    }
    store.addToast('專案已刪除', 'success')
    confirmDelete.value = false
    deleteTarget.value = null
    showDialog.value = false
    await fetchProjects()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}

async function toggleActive(project: ProjectInfo) {
  try {
    const res = await fetch(`${API}/api/v1/projects/${project.id}`, {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
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

const canSaveGithub = computed(() => {
  return !!githubSelectedRepo.value && !!form.value.name.trim() && !!form.value.path.trim() && !cloning.value
})
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
        <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-lg p-6 space-y-4 max-h-[85vh] overflow-y-auto">
          <h3 class="text-sm font-bold text-slate-200">
            {{ editingProject ? '編輯專案' : '新增專案' }}
          </h3>

          <!-- Mode Switcher (create only) -->
          <div v-if="!editingProject" class="flex bg-slate-900 rounded-lg p-1">
            <button
              @click="createMode = 'local'"
              :class="[
                'flex-1 flex items-center justify-center gap-2 py-2 text-sm rounded-md transition',
                createMode === 'local' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200'
              ]"
            >
              <FolderOpen class="w-4 h-4" />
              本地
            </button>
            <button
              @click="createMode = 'github'; if (!githubRepos.length && githubConnected) fetchGithubRepos()"
              :class="[
                'flex-1 flex items-center justify-center gap-2 py-2 text-sm rounded-md transition',
                createMode === 'github' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200'
              ]"
            >
              <Github class="w-4 h-4" />
              GitHub
            </button>
          </div>

          <!-- === LOCAL MODE (create) or EDIT MODE === -->
          <div v-if="editingProject || createMode === 'local'" class="space-y-4">
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
              <div class="flex items-center gap-2">
                <input
                  v-model="form.path"
                  type="text"
                  class="flex-1 px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-500"
                  placeholder="如：/home/user/projects/my-app"
                  :disabled="editingProject !== null"
                />
                <button
                  v-if="editingProject && !editingProject.is_system"
                  @click="showRelocate = !showRelocate; relocatePath = form.path"
                  class="p-2 text-slate-400 hover:text-emerald-400 hover:bg-slate-700 rounded-lg transition"
                  title="搬移目錄"
                >
                  <FolderInput class="w-4 h-4" />
                </button>
              </div>
              <p v-if="!editingProject" class="text-xs text-slate-500 mt-1">
                卡片檔案存放於此路徑的 .aegis/cards/ 目錄下
              </p>
            </div>

            <!-- Relocate Panel -->
            <div v-if="showRelocate && editingProject" class="bg-slate-900/80 rounded-lg border border-slate-600 p-3 space-y-2">
              <label class="block text-sm text-slate-400">搬移至新路徑</label>
              <input
                v-model="relocatePath"
                type="text"
                class="w-full px-3 py-2 bg-slate-950 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-500"
                placeholder="/home/user/projects/new-location"
              />
              <div class="flex justify-end gap-2">
                <button
                  @click="showRelocate = false"
                  class="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-200 transition"
                >
                  取消
                </button>
                <button
                  @click="confirmRelocate = true"
                  :disabled="relocateSaving || !relocatePath.trim() || relocatePath.trim() === form.path"
                  class="flex items-center gap-1 px-3 py-1.5 text-sm bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition"
                >
                  <Loader2 v-if="relocateSaving" class="w-3 h-3 animate-spin" />
                  搬移
                </button>
              </div>
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

          <!-- === GITHUB MODE (create only) === -->
          <div v-if="!editingProject && createMode === 'github'" class="space-y-4">

            <!-- Not connected warning -->
            <div v-if="!githubConnected" class="bg-amber-500/10 border border-amber-500/30 rounded-lg p-3 text-sm text-amber-300">
              尚未連線 GitHub，請先至「一般設定」設定 Personal Access Token。
            </div>

            <template v-else>
              <!-- Paste URL -->
              <div>
                <label class="block text-sm text-slate-400 mb-1">GitHub URL</label>
                <div class="flex items-center gap-2">
                  <input
                    v-model="githubUrl"
                    type="text"
                    class="flex-1 px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-500"
                    placeholder="https://github.com/org/repo"
                    @keydown.enter="parseGithubUrl"
                  />
                  <button
                    @click="parseGithubUrl"
                    :disabled="githubParsing || !githubUrl.trim()"
                    class="px-3 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded-lg transition"
                  >
                    <Loader2 v-if="githubParsing" class="w-4 h-4 animate-spin" />
                    <ChevronRight v-else class="w-4 h-4" />
                  </button>
                </div>
              </div>

              <div class="flex items-center gap-3 text-xs text-slate-500">
                <div class="flex-1 border-t border-slate-700"></div>
                <span>或從列表選取</span>
                <div class="flex-1 border-t border-slate-700"></div>
              </div>

              <!-- Repo Browser -->
              <div>
                <div class="relative mb-2">
                  <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                  <input
                    v-model="githubSearch"
                    @input="onGithubSearchInput"
                    type="text"
                    class="w-full pl-9 pr-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-500 text-sm"
                    placeholder="搜尋 repo..."
                  />
                </div>
                <div class="max-h-48 overflow-y-auto rounded-lg border border-slate-700 bg-slate-900/50">
                  <div v-if="githubReposLoading" class="flex justify-center py-6">
                    <Loader2 class="w-5 h-5 animate-spin text-slate-400" />
                  </div>
                  <div v-else-if="githubRepos.length === 0" class="text-center py-6 text-sm text-slate-500">
                    無結果
                  </div>
                  <button
                    v-else
                    v-for="repo in githubRepos"
                    :key="repo.full_name"
                    @click="selectGithubRepo(repo)"
                    :class="[
                      'w-full text-left px-3 py-2 border-b border-slate-700/50 last:border-b-0 hover:bg-slate-700/50 transition',
                      githubSelectedRepo?.full_name === repo.full_name ? 'bg-emerald-500/10 border-l-2 border-l-emerald-500' : ''
                    ]"
                  >
                    <div class="flex items-center gap-2">
                      <Globe v-if="!repo.private" class="w-3.5 h-3.5 text-slate-500 shrink-0" />
                      <Lock v-else class="w-3.5 h-3.5 text-amber-500 shrink-0" />
                      <span class="text-sm text-slate-200 truncate">{{ repo.full_name }}</span>
                    </div>
                    <p v-if="repo.description" class="text-xs text-slate-500 mt-0.5 truncate ml-5">{{ repo.description }}</p>
                  </button>
                </div>
              </div>

              <!-- Selected repo info -->
              <div v-if="githubSelectedRepo" class="bg-emerald-500/10 border border-emerald-500/30 rounded-lg p-3">
                <div class="text-sm text-emerald-300 font-medium">{{ githubSelectedRepo.full_name }}</div>
                <div class="text-xs text-slate-400 mt-1">{{ githubSelectedRepo.clone_url }}</div>
              </div>

              <!-- Clone destination -->
              <div>
                <label class="block text-sm text-slate-400 mb-1">專案名稱</label>
                <input
                  v-model="form.name"
                  type="text"
                  class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-500"
                  placeholder="repo-name"
                />
              </div>
              <div>
                <label class="block text-sm text-slate-400 mb-1">Clone 至路徑</label>
                <input
                  v-model="form.path"
                  type="text"
                  class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-500"
                  placeholder="~/projects/repo-name"
                />
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
              </div>
            </template>
          </div>

          <!-- Clone Progress -->
          <div v-if="cloning" class="flex items-center gap-3 bg-slate-900 rounded-lg p-3">
            <Loader2 class="w-5 h-5 animate-spin text-emerald-400" />
            <span class="text-sm text-slate-300">{{ cloneStatus }}</span>
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
            <!-- Right: Cancel & Save/Clone -->
            <div class="flex gap-3">
              <button
                @click="showDialog = false"
                class="px-4 py-2 text-slate-400 hover:text-slate-200 transition"
                :disabled="cloning"
              >
                取消
              </button>

              <!-- Local mode or Edit: save -->
              <button
                v-if="editingProject || createMode === 'local'"
                @click="saveProject"
                :disabled="saving || !form.name.trim() || !form.path.trim()"
                class="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition"
              >
                <Loader2 v-if="saving" class="w-4 h-4 animate-spin" />
                {{ editingProject ? '儲存' : '建立' }}
              </button>

              <!-- GitHub mode: clone -->
              <button
                v-if="!editingProject && createMode === 'github'"
                @click="startClone"
                :disabled="!canSaveGithub"
                class="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition"
              >
                <Github class="w-4 h-4" />
                Clone & 建立
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

    <!-- Confirm Relocate -->
    <ConfirmDialog
      v-model:show="confirmRelocate"
      title="搬移專案目錄"
      :message="`確定要將「${editingProject?.name}」搬移至\n${relocatePath}？`"
      confirm-text="搬移"
      @confirm="doRelocate"
    />
  </div>
</template>
