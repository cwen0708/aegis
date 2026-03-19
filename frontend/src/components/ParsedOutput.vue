<script setup lang="ts">
import { computed } from 'vue'
import { parseOutput } from '../composables/useStreamParser'

const props = defineProps<{ output: string }>()
const lines = computed(() => parseOutput(props.output))
</script>

<template>
  <div class="space-y-1 text-xs leading-relaxed">
    <div
      v-for="(line, i) in lines"
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

    <span v-if="!lines.length" class="text-slate-600">無輸出內容</span>
  </div>
</template>
