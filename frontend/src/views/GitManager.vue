<template>
  <div class="h-full flex flex-col">
    <PageHeader :icon="GitBranch">
      <router-link
        :to="`/files?project=${selectedProjectId || ''}`"
        class="p-1.5 rounded-lg text-slate-400 hover:text-emerald-400 hover:bg-slate-700 transition-colors"
        title="切換到檔案瀏覽"
      >
        <FolderOpen class="w-4 h-4" />
      </router-link>
    </PageHeader>

    <div v-if="!selectedProjectId" class="flex-1 flex items-center justify-center">
      <div class="text-center">
        <GitBranch class="w-12 h-12 text-slate-700 mx-auto mb-3" />
        <p class="text-slate-500 text-sm">選擇一個專案以管理 Git</p>
      </div>
    </div>

    <div v-else class="flex-1 overflow-hidden">
      <GitPanel :project-id="selectedProjectId" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { GitBranch, FolderOpen } from 'lucide-vue-next'
import PageHeader from '../components/PageHeader.vue'
import GitPanel from '../components/files/GitPanel.vue'
import { useProjectSelector } from '../composables/useProjectSelector'

const { selectedProjectId } = useProjectSelector()
</script>
