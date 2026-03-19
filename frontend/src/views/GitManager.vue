<template>
  <div class="h-full flex flex-col">
    <PageHeader :icon="GitBranch">
      <span class="text-sm text-slate-400">版本控制</span>
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
import { GitBranch } from 'lucide-vue-next'
import PageHeader from '../components/PageHeader.vue'
import GitPanel from '../components/files/GitPanel.vue'
import { useProjectSelector } from '../composables/useProjectSelector'

const { selectedProjectId } = useProjectSelector()
</script>
