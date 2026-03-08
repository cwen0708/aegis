<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'
import { useAegisStore } from '../stores/aegis'

const props = defineProps<{
  cardId: number
}>()

const store = useAegisStore()
const terminalEl = ref<HTMLPreElement | null>(null)

const logs = computed(() => {
  return store.taskLogs.get(props.cardId) || []
})

// 自動捲到底部
watch(() => logs.value.length, async () => {
  await nextTick()
  if (terminalEl.value) {
    terminalEl.value.scrollTop = terminalEl.value.scrollHeight
  }
})
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="flex items-center justify-between mb-2">
      <span class="text-xs font-semibold text-slate-500 tracking-wider">即時輸出</span>
      <span v-if="logs.length" class="text-[10px] text-slate-600 font-mono">{{ logs.length }} lines</span>
    </div>
    <pre
      ref="terminalEl"
      class="flex-1 bg-slate-950 rounded-lg p-3 overflow-y-auto font-mono text-xs text-green-400 leading-relaxed custom-scrollbar border border-slate-800"
    ><template v-for="(line, i) in logs" :key="i">{{ line }}</template><span v-if="!logs.length" class="text-slate-600">等待輸出...</span></pre>
  </div>
</template>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 4px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: #1e293b;
  border-radius: 4px;
}
</style>
