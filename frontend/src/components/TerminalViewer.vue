<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'
import { useAegisStore } from '../stores/aegis'
import { parseLine } from '../composables/useStreamParser'

const props = defineProps<{
  cardId: number
}>()

const store = useAegisStore()
const terminalEl = ref<HTMLPreElement | null>(null)

const parsedLogs = computed(() => {
  const raw = store.taskLogs.get(props.cardId) || []
  return raw.map(parseLine).filter(l => l.content)
})

// 自動捲到底部
watch(() => parsedLogs.value.length, async () => {
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
      <span v-if="parsedLogs.length" class="text-[10px] text-slate-600 font-mono">{{ parsedLogs.length }} entries</span>
    </div>
    <div
      ref="terminalEl"
      class="flex-1 bg-slate-950 rounded-lg p-3 overflow-y-auto text-xs leading-relaxed custom-scrollbar border border-slate-800 space-y-1"
    >
      <div
        v-for="(line, i) in parsedLogs"
        :key="i"
        class="flex gap-2"
      >
        <!-- assistant -->
        <template v-if="line.type === 'assistant'">
          <span class="text-cyan-400 shrink-0 select-none">AI</span>
          <span class="text-slate-200 whitespace-pre-wrap break-all">{{ line.content }}</span>
        </template>

        <!-- tool call -->
        <template v-else-if="line.type === 'tool_call'">
          <span class="text-amber-400 shrink-0 select-none">⚡</span>
          <span class="text-amber-300/80 font-mono">{{ line.content }}</span>
        </template>

        <!-- tool result -->
        <template v-else-if="line.type === 'tool_result'">
          <span class="text-slate-600 shrink-0 select-none">←</span>
          <span class="text-slate-500 font-mono whitespace-pre-wrap break-all">{{ line.content }}</span>
        </template>

        <!-- error -->
        <template v-else-if="line.type === 'error'">
          <span class="text-red-400 shrink-0 select-none">✗</span>
          <span class="text-red-400/80 font-mono">{{ line.content }}</span>
        </template>

        <!-- system -->
        <template v-else-if="line.type === 'system'">
          <span class="text-slate-600 italic">{{ line.content }}</span>
        </template>

        <!-- plain text -->
        <template v-else>
          <span class="text-green-400 whitespace-pre-wrap break-all">{{ line.content }}</span>
        </template>
      </div>

      <span v-if="!parsedLogs.length" class="text-slate-600">等待輸出...</span>
    </div>
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
