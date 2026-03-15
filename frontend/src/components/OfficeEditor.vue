<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import Phaser from 'phaser'
import { EditorScene } from '../game/EditorScene'
import {
  GroundType, isWall,
  type OfficeLayout, type EditorLayer,
} from '../game/types'
import { GROUND_LABELS, GROUND_COLORS, GROUND_TILE_FRAMES, WALL_TILE_FRAMES } from '../game/groundData'
import { FURNITURE_ASSETS, FURNITURE_CATALOG, PROPS_CATALOG, type CatalogCategory } from '../game/furnitureData'

const props = defineProps<{
  layout: OfficeLayout
}>()

const emit = defineEmits<{
  (e: 'save', layout: OfficeLayout): void
  (e: 'cancel'): void
}>()

const activeLayer = ref<EditorLayer>('ground')
const selectedTool = ref<string | null>(null)
const isDeleteMode = ref(false)
const activeCategory = ref<string>(FURNITURE_CATALOG[0]?.name ?? '')  // 當前選中的分類 Tab
const slotDirection = ref<'down' | 'left' | 'right' | 'up'>('up')

let game: Phaser.Game | null = null
let editorScene: EditorScene | null = null

onMounted(async () => {
  await document.fonts.ready
  await nextTick()

  game = new Phaser.Game({
    type: Phaser.AUTO,
    parent: 'editor-canvas',
    backgroundColor: '#1a1510',
    pixelArt: true,
    scale: { mode: Phaser.Scale.RESIZE, parent: 'editor-canvas' },
    scene: [],
  })

  const edScene = new EditorScene()
  game.scene.add('EditorScene', edScene, true, { layout: props.layout })

  // Wait for scene to initialize
  const checkScene = () => {
    const s = game?.scene.getScene('EditorScene') as EditorScene | null
    if (s) {
      editorScene = s
    } else {
      setTimeout(checkScene, 100)
    }
  }
  setTimeout(checkScene, 200)
})

onUnmounted(() => {
  game?.destroy(true)
  game = null
  editorScene = null
  window.removeEventListener('keydown', handleKeyDown)
  window.removeEventListener('wheel', handleWheel)
})

// ── Keyboard shortcuts: 1=ground 2=wall 3=furniture 4=props 0=delete ──
const LAYER_KEYS: Record<string, EditorLayer> = { '1': 'ground', '2': 'wall', '3': 'furniture', '4': 'props', '5': 'slots' }

function switchLayer(layer: EditorLayer) {
  activeLayer.value = layer
  isDeleteMode.value = false
  editorScene?.setDeleteMode(false)
}

function handleKeyDown(e: KeyboardEvent) {
  if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
  const layer = LAYER_KEYS[e.key]
  if (layer) {
    e.preventDefault()
    switchLayer(layer)
  } else if (e.key === '0') {
    e.preventDefault()
    toggleDeleteMode()
  }
}

// ── Scroll wheel: cycle through palette items ──
function handleWheel(e: WheelEvent) {
  // Only cycle when pointer is over the canvas area
  const canvas = document.getElementById('editor-canvas')
  if (!canvas?.contains(e.target as Node)) return

  const dir = e.deltaY > 0 ? 1 : -1

  if (activeLayer.value === 'ground') {
    const items = groundTypes.value
    if (items.length === 0) return
    const curIdx = items.findIndex(g => g.value === selectedTool.value)
    const nextIdx = curIdx < 0 ? 0 : ((curIdx + dir + items.length) % items.length)
    selectedTool.value = items[nextIdx]!.value
    editorScene?.setSelectedTool(selectedTool.value)
    isDeleteMode.value = false
  } else if (activeLayer.value === 'wall') {
    const items = wallStyles.value
    if (items.length === 0) return
    const curIdx = items.findIndex(w => w.value === selectedTool.value)
    const nextIdx = curIdx < 0 ? 0 : ((curIdx + dir + items.length) % items.length)
    selectedTool.value = items[nextIdx]!.value
    editorScene?.setSelectedTool(selectedTool.value)
    isDeleteMode.value = false
  } else if (activeLayer.value === 'furniture' || activeLayer.value === 'props') {
    const catalog = currentCatalog.value
    // 只在當前分類內切換
    const cat = catalog.find(c => c.name === activeCategory.value)
    const items = cat?.items ?? []
    if (items.length === 0) return
    const curIdx = items.indexOf(selectedTool.value ?? '')
    const nextIdx = curIdx < 0 ? 0 : ((curIdx + dir + items.length) % items.length)
    selectedTool.value = items[nextIdx]!
    editorScene?.setSelectedTool(selectedTool.value)
    isDeleteMode.value = false
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
  window.addEventListener('wheel', handleWheel, { passive: false })
})

// Sync layer & tool to Phaser scene
watch(activeLayer, (layer) => {
  selectedTool.value = null
  isDeleteMode.value = false
  editorScene?.setActiveLayer(layer)
  // 切換圖層時設定預設分類
  if (layer === 'furniture' && FURNITURE_CATALOG.length > 0) {
    activeCategory.value = FURNITURE_CATALOG[0]!.name
  } else if (layer === 'props' && PROPS_CATALOG.length > 0) {
    activeCategory.value = PROPS_CATALOG[0]!.name
  }
})

// Ground types for palette (exclude all wall types — they have their own layer)
const groundTypes = computed(() =>
  Object.entries(GROUND_LABELS)
    .filter(([val]) => !isWall(parseInt(val)))
    .map(([val, label]) => ({
      value: val,
      label,
      color: GROUND_COLORS[parseInt(val) as GroundType],
      tileFrame: (GROUND_TILE_FRAMES[parseInt(val) as GroundType] ?? [])[0],
    }))
)

// Wall styles for palette (from WALL_TILE_FRAMES)
const wallStyles = computed(() =>
  Object.entries(WALL_TILE_FRAMES).map(([val, frames]) => ({
    value: val,
    label: GROUND_LABELS[parseInt(val) as GroundType] ?? '牆壁',
    color: GROUND_COLORS[parseInt(val) as GroundType],
    frames: frames as number[],
  }))
)

// Current catalog
const currentCatalog = computed<CatalogCategory[]>(() => {
  if (activeLayer.value === 'furniture') return FURNITURE_CATALOG
  if (activeLayer.value === 'props') return PROPS_CATALOG
  return []
})

// 當前分類的項目
const currentCategoryItems = computed(() => {
  const cat = currentCatalog.value.find(c => c.name === activeCategory.value)
  return cat?.items ?? []
})

function selectGroundTool(val: string) {
  isDeleteMode.value = false
  selectedTool.value = selectedTool.value === val ? null : val
  editorScene?.setSelectedTool(selectedTool.value)
}

function selectItemTool(type: string) {
  isDeleteMode.value = false
  selectedTool.value = selectedTool.value === type ? null : type
  editorScene?.setSelectedTool(selectedTool.value)
}

function toggleDeleteMode() {
  isDeleteMode.value = !isDeleteMode.value
  selectedTool.value = null
  editorScene?.setDeleteMode(isDeleteMode.value)
}

function setSlotDir(dir: 'down' | 'left' | 'right' | 'up') {
  slotDirection.value = dir
  editorScene?.setSlotDirection(dir)
}

function clearLayout() {
  if (!confirm('確定要清空所有地面、家具和小物嗎？')) return
  if (!editorScene) return
  const layout = editorScene.getLayout()
  layout.ground = new Array(layout.cols * layout.rows).fill(0)
  layout.furniture = []
  layout.props = []
  layout.workstations = []
  layout.slots = []
  editorScene.loadLayout(layout)
}

function handleSave() {
  if (!editorScene) return
  const layout = editorScene.getLayout()
  emit('save', layout)
}

function handleExit() {
  emit('cancel')
}

function colorToHex(color: number): string {
  return '#' + color.toString(16).padStart(6, '0')
}

// Tile thumbnail: CSS background-position from room_builder.png spritesheet
function tileThumbStyle(frameIdx: number) {
  const cols = 16 // 256px / 16px
  const scale = 2  // display 16px tile at 32px (w-8)
  const ox = (frameIdx % cols) * 16 * scale
  const oy = Math.floor(frameIdx / cols) * 16 * scale
  return {
    backgroundImage: 'url(/assets/office/tiles/room_builder.png)',
    backgroundSize: `${256 * scale}px ${224 * scale}px`,
    backgroundPosition: `-${ox}px -${oy}px`,
    imageRendering: 'pixelated' as const,
  }
}
</script>

<template>
  <div class="flex flex-col h-full w-full bg-slate-900">
    <!-- Canvas -->
    <div id="editor-canvas" class="flex-1 min-h-0 overflow-hidden" style="image-rendering: pixelated;" />

    <!-- Horizontal Palette -->
    <div class="h-20 bg-slate-700/50 border-t border-slate-600 flex items-center gap-2 px-3 overflow-x-auto shrink-0">
      <!-- Ground palette -->
      <template v-if="activeLayer === 'ground'">
        <span class="text-[10px] text-slate-300 font-mono shrink-0">地面</span>
        <button
          v-for="gt in groundTypes"
          :key="gt.value"
          @click="selectGroundTool(gt.value)"
          class="flex flex-col items-center gap-0.5 p-1.5 rounded border transition-colors shrink-0"
          :class="selectedTool === gt.value
            ? 'border-amber-400 bg-slate-600'
            : 'border-slate-500/30 hover:border-slate-400/60'"
        >
          <div
            v-if="gt.tileFrame !== undefined"
            class="w-8 h-8 rounded"
            :style="tileThumbStyle(gt.tileFrame as number)"
          />
          <div
            v-else
            class="w-8 h-8 rounded"
            :style="{ backgroundColor: colorToHex(gt.color) }"
          />
          <span class="text-[8px] text-slate-400 font-mono">{{ gt.label }}</span>
        </button>
      </template>

      <!-- Wall palette -->
      <template v-else-if="activeLayer === 'wall'">
        <span class="text-[10px] text-slate-300 font-mono shrink-0">牆壁</span>
        <button
          v-for="ws in wallStyles"
          :key="ws.value"
          @click="selectGroundTool(ws.value)"
          class="flex flex-col items-center gap-0.5 p-1.5 rounded border transition-colors shrink-0"
          :class="selectedTool === ws.value
            ? 'border-amber-400 bg-slate-600'
            : 'border-slate-500/30 hover:border-slate-400/60'"
        >
          <div class="flex gap-0.5">
            <div
              v-for="frame in ws.frames.slice(0, 3)"
              :key="frame"
              class="w-5 h-5 rounded"
              :style="tileThumbStyle(frame)"
            />
          </div>
          <span class="text-[8px] text-slate-400 font-mono">{{ ws.label }}</span>
        </button>
      </template>

      <!-- Furniture / Props palette (items only, tabs are below) -->
      <template v-else-if="activeLayer === 'furniture' || activeLayer === 'props'">
        <button
          v-for="itemType in currentCategoryItems"
          :key="itemType"
          @click="selectItemTool(itemType)"
          class="flex flex-col items-center p-1 rounded border transition-colors shrink-0"
          :class="selectedTool === itemType
            ? 'border-amber-400 bg-slate-600'
            : 'border-slate-500/30 hover:border-slate-400/60'"
          :title="itemType"
        >
          <img
            :src="`/assets/office/furniture/${FURNITURE_ASSETS[itemType]}.png`"
            class="h-12 w-auto"
            style="image-rendering: pixelated;"
          />
        </button>
        <span v-if="currentCategoryItems.length === 0" class="text-[10px] text-slate-400 font-mono">
          選擇下方分類
        </span>
      </template>

      <!-- Slots palette -->
      <template v-else-if="activeLayer === 'slots'">
        <span class="text-[10px] text-slate-400 font-mono shrink-0">右鍵點擊設定工位</span>
        <div class="w-px h-12 bg-slate-500/30 shrink-0" />
        <span class="text-[10px] text-slate-300 font-mono shrink-0">方向</span>
        <button
          v-for="dir in (['up', 'down', 'left', 'right'] as const)"
          :key="dir"
          @click="setSlotDir(dir)"
          class="w-10 h-10 flex items-center justify-center rounded border transition-colors text-lg shrink-0"
          :class="slotDirection === dir
            ? 'border-amber-400 bg-slate-600 text-white'
            : 'border-slate-500/40 text-slate-400 hover:border-slate-400/70'"
          :title="{ up: '上', down: '下', left: '左', right: '右' }[dir]"
        >{{ { up: '↑', down: '↓', left: '←', right: '→' }[dir] }}</button>
      </template>
    </div>

    <!-- Category Tabs (for furniture/props) -->
    <div
      v-if="activeLayer === 'furniture' || activeLayer === 'props'"
      class="flex items-center gap-1 px-3 h-8 bg-slate-700 border-t border-slate-600 shrink-0 overflow-x-auto"
    >
      <button
        v-for="cat in currentCatalog"
        :key="cat.name"
        @click="activeCategory = cat.name"
        class="px-2 py-1 text-[10px] font-mono rounded transition-colors shrink-0"
        :class="activeCategory === cat.name
          ? 'bg-slate-600 text-white'
          : 'text-slate-400 hover:text-slate-200 hover:bg-slate-600/50'"
      >
        {{ cat.name }}
      </button>
    </div>

    <!-- Bottom Toolbar -->
    <div class="flex items-center gap-2 px-3 h-10 bg-slate-800 border-t border-slate-700 shrink-0">
      <div class="flex gap-1">
        <button
          v-for="layer in (['ground', 'wall', 'furniture', 'props', 'slots'] as EditorLayer[])"
          :key="layer"
          @click="switchLayer(layer)"
          class="px-2 py-1 text-[10px] font-mono rounded transition-colors"
          :class="activeLayer === layer
            ? 'bg-emerald-600 text-white'
            : 'bg-slate-700 text-slate-300 hover:bg-slate-600'"
        >
          {{ { ground: '地面', wall: '牆壁', furniture: '家具', props: '小物', slots: '工位' }[layer] }}
        </button>
        <button
          @click="toggleDeleteMode"
          class="px-2 py-1 text-[10px] font-mono rounded transition-colors"
          :class="isDeleteMode
            ? 'bg-red-600 text-white'
            : 'bg-slate-700 text-slate-400 hover:bg-slate-600'"
        >
          刪除
        </button>
        <button
          @click="clearLayout"
          class="px-2 py-1 text-[10px] font-mono rounded transition-colors bg-slate-700 text-orange-400 hover:bg-orange-600 hover:text-white"
        >
          清空
        </button>
      </div>

      <div class="flex-1" />

      <span class="text-[10px] text-slate-500 font-mono">
        左鍵移動 / 右鍵放置
      </span>

      <button
        @click="handleSave"
        class="px-3 py-1 text-[10px] font-mono bg-emerald-600 text-white rounded hover:bg-emerald-500 transition-colors"
      >
        儲存
      </button>
      <button
        @click="handleExit"
        class="px-3 py-1 text-[10px] font-mono bg-slate-700 text-slate-300 rounded hover:bg-slate-600 transition-colors"
      >
        退出
      </button>
    </div>
  </div>
</template>

<style scoped>
#editor-canvas canvas {
  image-rendering: pixelated !important;
  image-rendering: crisp-edges !important;
}
</style>
