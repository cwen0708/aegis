<script setup lang="ts">
import { ref, shallowRef, onMounted, onUnmounted, nextTick } from 'vue'
import Phaser from 'phaser'
import Room2EditorScene, { type EditorTool, type SelectionInfo } from '../game2/Room2EditorScene'
import type { TilesetInfo } from '../game2/tilesetRegistry'
import type { TiledMapJson } from '../game2/mapSerializer'
import { EditorBridge, EditorEvents } from '../game2/editorBridge'
import type { CompositeObject } from '../game2/compositeObjects'
import FloatingPanel from './room2editor/FloatingPanel.vue'
import ObjectPalette from './room2editor/ObjectPalette.vue'
import LayerPanel from './room2editor/LayerPanel.vue'
import PropertyPanel from './room2editor/PropertyPanel.vue'

const BACKUP_KEY = 'room2-editor-backup'

const props = defineProps<{
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  customMapJson?: Record<string, any> | null
}>()

const emit = defineEmits<{
  (e: 'save', mapJson: TiledMapJson): void
  (e: 'cancel'): void
}>()

const activeTool = ref<EditorTool>('select')
const selectedGid = ref(1)
const activeLayer = ref('Objects')
const selection = ref<SelectionInfo | null>(null)
const showCollision = ref(false)

let game: Phaser.Game | null = null
const bridge = new EditorBridge()
let backupInterval: number | null = null

const sceneRef = shallowRef<Phaser.Scene | null>(null)
const tilesetInfos = ref<TilesetInfo[]>([])
const layerPanelX = ref(800)
const propPanelX = ref(800)

// ── SVG icon paths ──────────────────────────────────────────────

const ICONS = {
  cursor: 'M4 2l12 10-5 1 3 7-3 1-3-7-4 4z',
  brush: 'M15.7 4.3a1 1 0 010 1.4l-7 7A3 3 0 116.3 10l7-7a1 1 0 011.4 0zM4 18h5v2H4z',
  fill: 'M16.6 9L9 1.4 7.6 2.8 9.2 4.4 2 11.6a1 1 0 000 1.4l5.6 5.6a1 1 0 001.4 0L16.6 11a1 1 0 000-1.4zM5.2 12L9 8.2l3.8 3.8H5.2zM19 14.5a2.5 2.5 0 01-5 0c0-1.4 2.5-4.5 2.5-4.5s2.5 3.1 2.5 4.5z',
  eraser: 'M19.1 10.9L13 4.8a1 1 0 00-1.4 0l-8.8 8.8a1 1 0 000 1.4l3.2 3.2H2v2h20v-2h-6.7l3.8-3.8a1 1 0 000-1.4zM8.3 18.2L4.1 14l4-4 4.2 4.2-4 4z',
  hand: 'M18 8.5V5a1 1 0 00-2 0V1.5a1 1 0 00-2 0V5a1 1 0 00-2 0V2a1 1 0 00-2 0v7l-1.8-2.4a1.2 1.2 0 00-2 1.4l4.3 7h0A5 5 0 0015.5 18h0a5 5 0 005-5v-3.5a1 1 0 00-2 0v-1z',
  undo: 'M7 8H3l4-4M3 8a9 9 0 1118 1',
  redo: 'M17 8h4l-4-4M21 8a9 9 0 10-18 1',
} as const

// ── 工具定義 ────────────────────────────────────────────────────

interface ToolDef { key: EditorTool; icon: keyof typeof ICONS; label: string; shortcut: string }

const toolbox: ToolDef[] = [
  { key: 'select', icon: 'cursor', label: '選取', shortcut: 'V' },
  { key: 'ground', icon: 'brush', label: '放置', shortcut: 'B' },
  { key: 'fill', icon: 'fill', label: '填充', shortcut: 'G' },
  { key: 'eraser', icon: 'eraser', label: '橡皮擦', shortcut: 'E' },
  { key: 'hand', icon: 'hand', label: '手掌', shortcut: 'H' },
]

// ── Lifecycle ───────────────────────────────────────────────────

onMounted(async () => {
  await document.fonts.ready
  await nextTick()

  layerPanelX.value = window.innerWidth - 220
  propPanelX.value = window.innerWidth - 220

  const backup = localStorage.getItem(BACKUP_KEY)
  let initialMap = props.customMapJson as TiledMapJson | undefined
  if (backup && !initialMap) {
    try {
      const parsed = JSON.parse(backup) as TiledMapJson
      if (parsed.layers && confirm('發現上次未儲存的編輯，是否還原？')) {
        initialMap = parsed
      }
    } catch { /* ignore */ }
  }

  const scene = new Room2EditorScene(initialMap)

  game = new Phaser.Game({
    type: Phaser.AUTO,
    parent: 'editor-canvas',
    backgroundColor: '#1a1a2e',
    pixelArt: true,
    scale: { mode: Phaser.Scale.RESIZE, parent: 'editor-canvas' },
    scene: [],
  })

  game.scene.add('room2-editor', scene, true)

  game.events.once(EditorEvents.READY, () => {
    bridge.bind(scene)
    sceneRef.value = bridge.getSceneRef()
    tilesetInfos.value = bridge.getTilesetInfos()
  })

  game.events.on(EditorEvents.OBJECT_SELECTED, (info: SelectionInfo | null) => {
    selection.value = info
  })

  game.events.on(EditorEvents.COLLISION_TOGGLED, (on: boolean) => {
    showCollision.value = on
  })

  backupInterval = window.setInterval(autoBackup, 30000)
})

onUnmounted(() => {
  if (backupInterval) clearInterval(backupInterval)
  game?.events.off(EditorEvents.OBJECT_SELECTED)
  game?.events.off(EditorEvents.COLLISION_TOGGLED)
  bridge.unbind()
  game?.destroy(true)
  game = null
})

async function autoBackup() {
  if (!bridge.isBound) return
  try {
    const json = await bridge.getMapData()
    if (json) localStorage.setItem(BACKUP_KEY, JSON.stringify(json))
  } catch { /* ignore */ }
}

// ── 工具操作 ────────────────────────────────────────────────────

function handleUndo() { bridge.undo() }
function handleRedo() { bridge.redo() }

function setTool(tool: EditorTool) {
  activeTool.value = tool
  bridge.setTool(tool)
}

function handlePaletteSelect(gid: number, layerName: string) {
  selectedGid.value = gid
  bridge.setSelectedGid(gid)
  bridge.setTargetLayer(layerName)
  bridge.setComposite(null)
  activeLayer.value = layerName
  if (layerName === 'Ground') {
    if (activeTool.value !== 'ground' && activeTool.value !== 'fill') setTool('ground')
  } else {
    bridge.setTool('object')
    activeTool.value = 'ground'
  }
}

function handleCompositeSelect(comp: CompositeObject) {
  bridge.setComposite(comp)
  bridge.setTargetLayer(comp.targetLayer)
  bridge.setTool('object')
  activeLayer.value = comp.targetLayer
  activeTool.value = 'ground'
}

function handleLayerSelect(layerName: string) {
  activeLayer.value = layerName
  bridge.setTargetLayer(layerName)
}

function handleToggleVisibility(layerName: string, visible: boolean) {
  bridge.toggleLayerVisibility(layerName, visible)
}

function handleToggleCollision() {
  bridge.toggleCollisionPreview()
}

function handleUpdatePosition(layerName: string, objId: number, x: number, y: number) {
  bridge.updateObjectPosition(layerName, objId, x, y)
}

function handleDeleteFromPanel() {
  bridge.deleteSelected()
}

// ── 匯出/匯入 ──────────────────────────────────────────────────

async function downloadMapJson() {
  const json = await bridge.getMapData()
  if (!json) return
  const blob = new Blob([JSON.stringify(json, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'map.json'
  a.click()
  URL.revokeObjectURL(url)
}

const MAX_IMPORT_SIZE = 10 * 1024 * 1024

function validateTiledJson(json: unknown): json is TiledMapJson {
  if (!json || typeof json !== 'object') return false
  const j = json as Record<string, unknown>
  if (!Array.isArray(j.layers)) return false
  if (typeof j.width !== 'number' || typeof j.height !== 'number') return false
  if (j.width < 1 || j.width > 500 || j.height < 1 || j.height > 500) return false
  if (!Array.isArray(j.tilesets)) return false
  return true
}

function uploadMapJson() {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.json'
  input.onchange = () => {
    const file = input.files?.[0]
    if (!file) return
    if (file.size > MAX_IMPORT_SIZE) { alert('檔案過大，上限 10MB'); return }
    const reader = new FileReader()
    reader.onload = (e) => {
      try {
        const json = JSON.parse(e.target?.result as string)
        if (!validateTiledJson(json)) {
          alert('無效的 Tiled JSON 格式（需包含 layers、tilesets、width、height）')
          return
        }
        localStorage.setItem(BACKUP_KEY, JSON.stringify(json))
        emit('cancel')
        alert('已匯入，請重新進入編輯模式')
      } catch { alert('JSON 解析失敗') }
    }
    reader.readAsText(file)
  }
  input.click()
}

const isSaving = ref(false)

async function handleSave() {
  if (!bridge.isBound || isSaving.value) return
  isSaving.value = true
  try {
    const mapData = await bridge.getMapData()
    if (!mapData) return
    localStorage.removeItem(BACKUP_KEY)
    emit('save', mapData)
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 bg-gray-900">
    <!-- Phaser Canvas -->
    <div id="editor-canvas" class="absolute inset-0" />

    <!-- ====== 頂部選單列 ====== -->
    <div class="absolute top-0 left-0 right-0 z-[61] flex items-center gap-2 px-3 py-1 bg-gray-800/90 backdrop-blur-sm border-b border-gray-700 text-xs">
      <!-- Undo / Redo (SVG) -->
      <button class="p-1 rounded hover:bg-gray-700" title="復原 (Ctrl+Z)" @click="handleUndo">
        <svg class="w-4 h-4 text-gray-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path :d="ICONS.undo" /></svg>
      </button>
      <button class="p-1 rounded hover:bg-gray-700" title="重做 (Ctrl+Shift+Z)" @click="handleRedo">
        <svg class="w-4 h-4 text-gray-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path :d="ICONS.redo" /></svg>
      </button>

      <div class="w-px h-4 bg-gray-600" />

      <span class="text-gray-500">
        {{ activeLayer }} · GID {{ selectedGid }}
      </span>

      <div class="flex-1" />

      <span class="text-gray-600">左鍵操作 · 右鍵平移 · 滾輪縮放</span>

      <div class="w-px h-4 bg-gray-600" />

      <button class="px-2 py-0.5 rounded bg-gray-700 text-gray-300 hover:bg-gray-600" @click="downloadMapJson">匯出</button>
      <button class="px-2 py-0.5 rounded bg-gray-700 text-gray-300 hover:bg-gray-600" @click="uploadMapJson">匯入</button>
      <button
        :disabled="isSaving"
        :class="['px-3 py-0.5 rounded font-medium text-white', isSaving ? 'bg-green-800' : 'bg-green-600 hover:bg-green-500']"
        @click="handleSave"
      >{{ isSaving ? '儲存中...' : '儲存' }}</button>
      <button class="px-3 py-0.5 rounded bg-gray-700 text-gray-300 hover:bg-gray-600" @click="emit('cancel')">退出</button>
    </div>

    <!-- ====== 浮動工具箱 ====== -->
    <div class="absolute left-3 top-12 z-[62] flex flex-col gap-0.5 bg-gray-800/95 backdrop-blur-sm rounded-lg border border-gray-600 p-1 shadow-xl">
      <button
        v-for="t in toolbox"
        :key="t.key"
        :class="[
          'w-8 h-8 rounded flex items-center justify-center transition-colors',
          activeTool === t.key
            ? 'bg-blue-600 text-white'
            : 'text-gray-400 hover:bg-gray-700 hover:text-gray-200',
        ]"
        :title="`${t.label} (${t.shortcut})`"
        @click="setTool(t.key)"
      >
        <svg class="w-4.5 h-4.5" viewBox="0 0 24 24" fill="currentColor"><path :d="ICONS[t.icon]" /></svg>
      </button>
    </div>

    <!-- ====== 浮動素材庫 ====== -->
    <FloatingPanel
      title="素材庫"
      :initial-x="56"
      :initial-y="44"
      width="260px"
    >
      <ObjectPalette
        :scene="sceneRef"
        :tileset-infos="tilesetInfos"
        @select="handlePaletteSelect"
        @select-composite="handleCompositeSelect"
      />
    </FloatingPanel>

    <!-- ====== 浮動圖層面板 ====== -->
    <FloatingPanel
      title="圖層"
      :initial-x="layerPanelX"
      :initial-y="44"
      width="180px"
    >
      <LayerPanel
        :active-layer="activeLayer"
        :show-collision="showCollision"
        @select-layer="handleLayerSelect"
        @toggle-visibility="handleToggleVisibility"
        @toggle-collision="handleToggleCollision"
      />
    </FloatingPanel>

    <!-- ====== 浮動屬性面板 ====== -->
    <FloatingPanel
      v-if="selection"
      title="屬性"
      :initial-x="propPanelX"
      :initial-y="340"
      width="180px"
    >
      <PropertyPanel
        :selection="selection"
        @update-position="handleUpdatePosition"
        @delete="handleDeleteFromPanel"
      />
    </FloatingPanel>
  </div>
</template>
