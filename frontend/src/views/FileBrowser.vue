<template>
  <div class="h-full flex flex-col">
    <PageHeader :icon="FolderOpen">
      <!-- Breadcrumb -->
      <div v-if="selectedFile" class="flex items-center gap-1 text-xs text-slate-500">
        <button class="hover:text-slate-300" @click="selectedFile = ''">根目錄</button>
        <template v-for="(part, i) in breadcrumbs" :key="i">
          <ChevronRight class="w-3 h-3" />
          <span class="text-slate-400">{{ part }}</span>
        </template>
      </div>

      <!-- View toggle -->
      <div class="flex items-center gap-1">
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
    </PageHeader>

    <!-- Empty state -->
    <div v-if="!selectedProjectId" class="flex-1 flex items-center justify-center">
      <div class="text-center">
        <FolderOpen class="w-12 h-12 text-slate-700 mx-auto mb-3" />
        <p class="text-slate-500 text-sm">選擇一個專案以瀏覽檔案</p>
      </div>
    </div>

    <!-- Content -->
    <div v-else class="flex-1 flex overflow-hidden">
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
import { ref, computed, watch } from 'vue'
import { FolderOpen, ChevronRight, GitBranch } from 'lucide-vue-next'
import PageHeader from '../components/PageHeader.vue'
import FileTree from '../components/files/FileTree.vue'
import FileViewer from '../components/files/FileViewer.vue'
import GitPanel from '../components/files/GitPanel.vue'
import { useProjectSelector } from '../composables/useProjectSelector'
import type { FileEntry } from '../components/files/FileTree.vue'

const { selectedProjectId } = useProjectSelector()

const selectedFile = ref('')
const viewMode = ref<'files' | 'git'>('files')

const breadcrumbs = computed(() => {
  if (!selectedFile.value) return []
  return selectedFile.value.split('/')
})

function onSelectFile(entry: FileEntry) {
  selectedFile.value = entry.path
}

watch(selectedProjectId, () => {
  selectedFile.value = ''
})
</script>
