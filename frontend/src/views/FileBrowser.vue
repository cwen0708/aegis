<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="flex items-center gap-3 px-6 py-3 border-b border-slate-700/50 shrink-0">
      <FolderOpen class="w-5 h-5 text-emerald-400" />
      <h1 class="text-lg font-semibold text-slate-200">檔案瀏覽</h1>

      <!-- 專案選擇 -->
      <select
        v-model="selectedProjectId"
        class="ml-4 bg-slate-800 text-slate-300 text-sm rounded-lg border border-slate-700 px-3 py-1.5 focus:outline-none focus:border-emerald-500"
      >
        <option :value="0" disabled>選擇專案</option>
        <option v-for="p in projects" :key="p.id" :value="p.id">
          {{ p.name }}
        </option>
      </select>

      <!-- Breadcrumb -->
      <div v-if="selectedFile" class="flex items-center gap-1 text-xs text-slate-500 ml-4">
        <button class="hover:text-slate-300" @click="selectedFile = ''">根目錄</button>
        <template v-for="(part, i) in breadcrumbs" :key="i">
          <ChevronRight class="w-3 h-3" />
          <span class="text-slate-400">{{ part }}</span>
        </template>
      </div>

      <!-- View toggle -->
      <div class="ml-auto flex items-center gap-1">
        <button
          class="p-1.5 rounded transition-colors"
          :class="viewMode === 'files' ? 'bg-slate-700 text-emerald-400' : 'text-slate-500 hover:text-slate-300'"
          @click="viewMode = 'files'"
          title="檔案"
        >
          <FolderOpen class="w-4 h-4" />
        </button>
        <button
          class="p-1.5 rounded transition-colors"
          :class="viewMode === 'git' ? 'bg-slate-700 text-emerald-400' : 'text-slate-500 hover:text-slate-300'"
          @click="viewMode = 'git'"
          title="Git"
        >
          <GitBranch class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!selectedProjectId" class="flex-1 flex items-center justify-center">
      <div class="text-center">
        <FolderOpen class="w-12 h-12 text-slate-700 mx-auto mb-3" />
        <p class="text-slate-500 text-sm">選擇一個專案以瀏覽檔案</p>
      </div>
    </div>

    <!-- Content -->
    <div v-else class="flex-1 flex overflow-hidden">
      <!-- File tree (左側) -->
      <div
        v-if="viewMode === 'files'"
        class="w-64 border-r border-slate-700/50 overflow-y-auto custom-scrollbar shrink-0 bg-slate-900/50"
      >
        <FileTree
          :project-id="selectedProjectId"
          :selected-path="selectedFile"
          @select="onSelectFile"
        />
      </div>

      <!-- Main content -->
      <div class="flex-1 overflow-hidden">
        <FileViewer
          v-if="viewMode === 'files'"
          :project-id="selectedProjectId"
          :path="selectedFile"
        />
        <GitPanel
          v-else
          :project-id="selectedProjectId"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { FolderOpen, ChevronRight, GitBranch } from 'lucide-vue-next'
import { config } from '../config'
import FileTree from '../components/files/FileTree.vue'
import FileViewer from '../components/files/FileViewer.vue'
import GitPanel from '../components/files/GitPanel.vue'
import type { FileEntry } from '../components/files/FileTree.vue'

const API = config.apiUrl
const route = useRoute()
const router = useRouter()

interface ProjectInfo {
  id: number
  name: string
  path: string
}

const projects = ref<ProjectInfo[]>([])
const selectedProjectId = ref(0)
const selectedFile = ref('')
const viewMode = ref<'files' | 'git'>('files')

const breadcrumbs = computed(() => {
  if (!selectedFile.value) return []
  return selectedFile.value.split('/')
})

function onSelectFile(entry: FileEntry) {
  selectedFile.value = entry.path
}

async function loadProjects() {
  const res = await fetch(`${API}/api/v1/projects/`)
  if (res.ok) {
    const data = await res.json()
    projects.value = data.filter((p: any) => p.is_active)
  }
}

// URL 參數同步
watch(selectedProjectId, (id) => {
  if (id) {
    router.replace({ path: `/files/${id}` })
    selectedFile.value = ''
  }
})

onMounted(async () => {
  await loadProjects()
  const paramId = Number(route.params.projectId)
  if (paramId && projects.value.find(p => p.id === paramId)) {
    selectedProjectId.value = paramId
  } else if (projects.value.length > 0) {
    // 預設選第一個非系統專案
    const nonSystem = projects.value.find(p => !(p as any).is_system)
    if (nonSystem) selectedProjectId.value = nonSystem.id
  }
})
</script>
