<script setup lang="ts">
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { useAegisStore } from '../stores/aegis'
import { useFlowDiagram } from '../composables/useFlowDiagram'

const props = defineProps<{
  cardId: number
  memberName?: string
}>()

const store = useAegisStore()
const container = ref<HTMLElement>()
const svgContent = ref('')
const renderError = ref('')

const rawLogs = computed(() => store.taskLogs.get(props.cardId) || [])
const { mermaidCode, hasData } = useFlowDiagram(rawLogs, props.memberName)

let mermaidModule: any = null

async function loadMermaid() {
  if (mermaidModule) return mermaidModule
  const mod = await import('mermaid')
  mod.default.initialize({
    startOnLoad: false,
    theme: 'dark',
    themeVariables: {
      primaryColor: '#1e293b',
      primaryTextColor: '#e2e8f0',
      primaryBorderColor: '#475569',
      lineColor: '#94a3b8',
      secondaryColor: '#0f172a',
      tertiaryColor: '#1e293b',
      noteBkgColor: '#334155',
      noteTextColor: '#e2e8f0',
      noteBorderColor: '#475569',
      actorBkg: '#1e293b',
      actorBorder: '#10b981',
      actorTextColor: '#e2e8f0',
      signalColor: '#94a3b8',
      signalTextColor: '#e2e8f0',
    },
    sequence: {
      actorMargin: 50,
      messageMargin: 30,
      mirrorActors: false,
      bottomMarginAdj: 10,
      useMaxWidth: false,
    },
    securityLevel: 'loose',
  })
  mermaidModule = mod.default
  return mermaidModule
}

async function renderDiagram() {
  if (!mermaidCode.value || !container.value) {
    svgContent.value = ''
    return
  }

  try {
    const mermaid = await loadMermaid()
    const id = `flow-${props.cardId}-${Date.now()}`
    const { svg } = await mermaid.render(id, mermaidCode.value)
    svgContent.value = svg
    renderError.value = ''

    // 自動捲到底部
    await nextTick()
    if (container.value) {
      container.value.scrollTop = container.value.scrollHeight
    }
  } catch (e: any) {
    renderError.value = e.message || 'Mermaid 渲染失敗'
    svgContent.value = ''
  }
}

// 監聽 mermaidCode 變化，重新渲染（debounce）
let renderTimer: ReturnType<typeof setTimeout> | null = null
watch(mermaidCode, () => {
  if (renderTimer) clearTimeout(renderTimer)
  renderTimer = setTimeout(renderDiagram, 500)
})

onMounted(() => {
  if (mermaidCode.value) {
    renderDiagram()
  }
})
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- 無資料 -->
    <div v-if="!hasData" class="flex-1 flex items-center justify-center">
      <div class="text-xs text-slate-500">尚無執行流程資料</div>
    </div>

    <!-- 渲染錯誤 -->
    <div v-else-if="renderError" class="flex-1 flex flex-col gap-4 p-4">
      <div class="text-xs text-red-400">{{ renderError }}</div>
      <details class="text-xs text-slate-500">
        <summary class="cursor-pointer hover:text-slate-300">查看原始 Mermaid 語法</summary>
        <pre class="mt-2 p-3 bg-slate-900 rounded-lg overflow-auto text-slate-400 text-[10px] leading-relaxed">{{ mermaidCode }}</pre>
      </details>
    </div>

    <!-- 流程圖 -->
    <div v-else ref="container" class="flex-1 overflow-auto custom-scrollbar p-4">
      <div
        v-html="svgContent"
        class="mermaid-container [&_svg]:max-w-none [&_svg]:w-auto"
      />
    </div>
  </div>
</template>
