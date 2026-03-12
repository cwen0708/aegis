<script setup lang="ts">
import { ref } from 'vue'
import { Activity } from 'lucide-vue-next'
import { useAegisStore } from '../stores/aegis'
import { useProjectSelector } from '../composables/useProjectSelector'
import PageHeader from '../components/PageHeader.vue'
import RunningTaskCard from '../components/RunningTaskCard.vue'
import TerminalViewer from '../components/TerminalViewer.vue'

const store = useAegisStore()
useProjectSelector() // 初始化全域專案狀態

const expandedTaskId = ref<number | null>(null)

function toggleTaskLog(taskId: number) {
  expandedTaskId.value = expandedTaskId.value === taskId ? null : taskId
}

async function handleAbort(taskId: number) {
  try {
    await store.abortCard(taskId)
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <PageHeader :icon="Activity">
      <div class="flex items-center gap-2 text-xs text-slate-500">
        <Activity class="w-4 h-4" />
        <span>{{ store.runningTasks.length }} 個任務</span>
      </div>
    </PageHeader>

    <div class="flex-1 overflow-auto p-2 sm:p-8">
      <div v-if="store.runningTasks.length === 0" class="bg-slate-800/30 rounded-2xl border border-slate-700/50 p-10 sm:p-20 text-center">
        <Activity class="w-10 h-10 mx-auto mb-3 text-slate-600" />
        <p class="text-sm text-slate-500">目前沒有運行中的任務</p>
      </div>

      <div v-else class="space-y-3">
        <div v-for="task in store.runningTasks" :key="task.task_id">
          <RunningTaskCard
            :task="task"
            @abort="handleAbort"
            @click="toggleTaskLog"
          />
          <!-- 展開 log -->
          <div v-if="expandedTaskId === task.task_id" class="mt-2 h-64 bg-slate-900 rounded-xl border border-slate-700 p-3">
            <TerminalViewer :card-id="task.task_id" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
