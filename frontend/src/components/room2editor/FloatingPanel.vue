<script setup lang="ts">
import { ref, onMounted } from 'vue'

const props = withDefaults(defineProps<{
  title: string
  initialX?: number
  initialY?: number
  width?: string
  collapsible?: boolean
}>(), {
  initialX: 0,
  initialY: 0,
  width: '220px',
  collapsible: true,
})

const x = ref(props.initialX)
const y = ref(props.initialY)
const collapsed = ref(false)
const panelRef = ref<HTMLDivElement>()

let dragging = false
let offsetX = 0
let offsetY = 0

function onDragStart(e: PointerEvent) {
  dragging = true
  offsetX = e.clientX - x.value
  offsetY = e.clientY - y.value
  ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
}

function onDragMove(e: PointerEvent) {
  if (!dragging) return
  x.value = Math.max(0, e.clientX - offsetX)
  y.value = Math.max(0, e.clientY - offsetY)
}

function onDragEnd() {
  dragging = false
}

onMounted(() => {
  // 確保面板不超出視窗
  if (panelRef.value) {
    const rect = panelRef.value.getBoundingClientRect()
    if (x.value + rect.width > window.innerWidth) x.value = window.innerWidth - rect.width - 8
    if (y.value + rect.height > window.innerHeight) y.value = window.innerHeight - rect.height - 8
  }
})
</script>

<template>
  <div
    ref="panelRef"
    class="fixed z-[60] rounded-lg shadow-2xl border border-gray-600 bg-gray-800/95 backdrop-blur-sm select-none"
    :style="{ left: x + 'px', top: y + 'px', width: props.width }"
  >
    <!-- 標題列（拖曳把手） -->
    <div
      class="flex items-center gap-1.5 px-2 py-1 bg-gray-700/80 rounded-t-lg cursor-move text-xs text-gray-300"
      @pointerdown="onDragStart"
      @pointermove="onDragMove"
      @pointerup="onDragEnd"
      @pointercancel="onDragEnd"
    >
      <span class="flex-1 font-medium truncate">{{ title }}</span>
      <button
        v-if="collapsible"
        class="w-4 h-4 text-center text-gray-500 hover:text-gray-300 leading-none"
        @click.stop="collapsed = !collapsed"
      >
        {{ collapsed ? '+' : '-' }}
      </button>
    </div>
    <!-- 內容 -->
    <div v-show="!collapsed" class="overflow-hidden">
      <slot />
    </div>
  </div>
</template>
