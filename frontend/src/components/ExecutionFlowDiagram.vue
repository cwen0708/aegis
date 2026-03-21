<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { X, Maximize2, Minimize2, ZoomIn, ZoomOut, RotateCcw } from 'lucide-vue-next'
import { useAegisStore } from '../stores/aegis'
import { useFlowDiagram } from '../composables/useFlowDiagram'

const props = defineProps<{
  cardId: number
  memberName?: string
}>()

const store = useAegisStore()
const svgContainer = ref<HTMLElement>()
const svgContent = ref('')
const renderError = ref('')
const isFullscreen = ref(false)

let panZoomInstance: any = null

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
      actorMargin: 100,
      messageMargin: 60,
      mirrorActors: false,
      bottomMarginAdj: 40,
      useMaxWidth: false,
      width: 220,
      height: 65,
      noteMargin: 30,
      boxMargin: 20,
    },
    securityLevel: 'loose',
  })
  mermaidModule = mod.default
  return mermaidModule
}

async function initPanZoom() {
  await nextTick()
  if (!svgContainer.value) return

  const svgEl = svgContainer.value.querySelector('svg')
  if (!svgEl) return

  // 清除舊的 panZoom
  destroyPanZoom()

  // 確保 SVG 有正確的尺寸
  svgEl.removeAttribute('height')
  svgEl.style.width = '100%'
  svgEl.style.height = '100%'
  svgEl.style.minWidth = 'auto'
  svgEl.style.maxWidth = 'none'

  const svgPanZoom = await import('svg-pan-zoom')
  panZoomInstance = svgPanZoom.default(svgEl, {
    zoomEnabled: true,
    panEnabled: true,
    controlIconsEnabled: false,
    fit: true,
    center: true,
    minZoom: 0.2,
    maxZoom: 5,
    zoomScaleSensitivity: 0.3,
  })
}

function destroyPanZoom() {
  if (panZoomInstance) {
    try { panZoomInstance.destroy() } catch {}
    panZoomInstance = null
  }
}

function handleZoomIn() {
  panZoomInstance?.zoomIn()
}
function handleZoomOut() {
  panZoomInstance?.zoomOut()
}
function handleReset() {
  panZoomInstance?.resetZoom()
  panZoomInstance?.resetPan()
  panZoomInstance?.fit()
  panZoomInstance?.center()
}
function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value
  // 全螢幕切換後重新 fit
  nextTick(() => {
    panZoomInstance?.resize()
    panZoomInstance?.fit()
    panZoomInstance?.center()
  })
}

async function renderDiagram() {
  if (!mermaidCode.value) {
    svgContent.value = ''
    return
  }

  try {
    const mermaid = await loadMermaid()
    const id = `flow-${props.cardId}-${Date.now()}`
    const { svg } = await mermaid.render(id, mermaidCode.value)
    svgContent.value = svg
    renderError.value = ''

    await nextTick()
    await initPanZoom()
  } catch (e: any) {
    renderError.value = e.message || 'Mermaid 渲染失敗'
    svgContent.value = ''
  }
}

// debounce re-render
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

onBeforeUnmount(() => {
  destroyPanZoom()
  if (renderTimer) clearTimeout(renderTimer)
})
</script>

<template>
  <!-- 容器：內嵌或全螢幕 -->
  <div
    :class="isFullscreen
      ? 'fixed inset-0 z-[100] bg-slate-950'
      : 'h-full'"
    class="flex flex-col"
  >
    <!-- 工具列 -->
    <div class="flex items-center justify-between px-3 py-2 bg-slate-900/80 border-b border-slate-700/50 shrink-0">
      <span class="text-xs text-slate-400">執行流程圖</span>
      <div v-if="hasData && svgContent" class="flex items-center gap-1">
        <button @click="handleZoomIn" class="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-700 rounded transition-colors" title="放大">
          <ZoomIn class="w-3.5 h-3.5" />
        </button>
        <button @click="handleZoomOut" class="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-700 rounded transition-colors" title="縮小">
          <ZoomOut class="w-3.5 h-3.5" />
        </button>
        <button @click="handleReset" class="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-700 rounded transition-colors" title="重置">
          <RotateCcw class="w-3.5 h-3.5" />
        </button>
        <div class="w-px h-4 bg-slate-700 mx-1" />
        <button @click="toggleFullscreen" class="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-700 rounded transition-colors" :title="isFullscreen ? '退出全螢幕' : '全螢幕'">
          <Minimize2 v-if="isFullscreen" class="w-3.5 h-3.5" />
          <Maximize2 v-else class="w-3.5 h-3.5" />
        </button>
        <button v-if="isFullscreen" @click="isFullscreen = false" class="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-700 rounded transition-colors ml-1" title="關閉">
          <X class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>

    <!-- 內容區 -->
    <div class="flex-1 overflow-hidden relative">
      <!-- 無資料 -->
      <div v-if="!hasData" class="h-full flex items-center justify-center">
        <div class="text-xs text-slate-500">尚無執行流程資料</div>
      </div>

      <!-- 渲染錯誤 -->
      <div v-else-if="renderError" class="h-full flex flex-col gap-4 p-4 overflow-auto">
        <div class="text-xs text-red-400">{{ renderError }}</div>
        <details class="text-xs text-slate-500">
          <summary class="cursor-pointer hover:text-slate-300">查看原始 Mermaid 語法</summary>
          <pre class="mt-2 p-3 bg-slate-900 rounded-lg overflow-auto text-slate-400 text-[10px] leading-relaxed">{{ mermaidCode }}</pre>
        </details>
      </div>

      <!-- SVG 流程圖（可平移縮放） -->
      <div
        v-else
        ref="svgContainer"
        v-html="svgContent"
        class="h-full w-full [&_svg]:h-full [&_svg]:w-full"
      />

      <!-- 操作提示 -->
      <div v-if="hasData && svgContent" class="absolute bottom-2 left-3 text-[10px] text-slate-600 pointer-events-none">
        滾輪縮放 · 拖曳平移
      </div>
    </div>
  </div>
</template>
