<script setup lang="ts">
import { ref, shallowRef, onMounted, onUnmounted, nextTick, watch } from 'vue'
import Phaser from 'phaser'
import Room2EditorScene, { type EditorTool, type SelectionInfo } from '../game2/Room2EditorScene'
import type { TilesetInfo } from '../game2/tilesetRegistry'
import type { TiledMapJson } from '../game2/mapSerializer'
import { EditorBridge, EditorEvents } from '../game2/editorBridge'
import { extractThumbnailsForKey, type ThumbnailItem } from '../game2/thumbnailExtractor'
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
const paletteTab = ref<'ground' | 'object'>('ground')

let game: Phaser.Game | null = null
const bridge = new EditorBridge()
let backupInterval: number | null = null

const sceneRef = shallowRef<Phaser.Scene | null>(null)
const tilesetInfos = ref<TilesetInfo[]>([])

// 浮動面板初始位置
const layerPanelX = ref(800)
const propPanelX = ref(800)

// ── 工具定義 ────────────────────────────────────────────────────

interface ToolDef { key: EditorTool; label: string; icon: string; shortcut?: string }

const toolbox: ToolDef[] = [
  { key: 'select', label: '選取', icon: '⬆', shortcut: 'V' },
  { key: 'ground', label: '放置', icon: '✏', shortcut: 'B' },
  { key: 'fill', label: '填充', icon: '🪣', shortcut: 'G' },
  { key: 'eraser', label: '橡皮擦', icon: '⌫', shortcut: 'E' },
  { key: 'hand', label: '手掌', icon: '✋', shortcut: 'H' },
]

// ── 地板 tile 縮圖 ─────────────────────────────────────────────

const groundThumbs = ref<ThumbnailItem[]>([])

function generateGroundThumbnails() {
  const scene = sceneRef.value
  if (!scene) return
  groundThumbs.value = extractThumbnailsForKey(
    scene.textures, tilesetInfos.value, 'tiles_floor', 40,
  )
}

watch(sceneRef, (s) => { if (s) generateGroundThumbnails() })

// ── Lifecycle ───────────────────────────────────────────────────

onMounted(async () => {
  await document.fonts.ready
  await nextTick()

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

  // 設定浮動面板初始 X 位置
  layerPanelX.value = window.innerWidth - 220
  propPanelX.value = window.innerWidth - 220

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
  // ground 和 object 是放置模式，用 paletteTab 決定實際行為
  if (tool === 'ground') {
    bridge.setTool(paletteTab.value === 'object' ? 'object' : 'ground')
  } else {
    bridge.setTool(tool)
  }
}

function switchPaletteTab(tab: 'ground' | 'object') {
  paletteTab.value = tab
  // 如果目前是放置工具，同步更新 scene 的 tool
  if (activeTool.value === 'ground') {
    bridge.setTool(tab === 'object' ? 'object' : 'ground')
  }
}

function selectTile(gid: number) {
  selectedGid.value = gid
  bridge.setSelectedGid(gid)
  paletteTab.value = 'ground'
  if (activeTool.value !== 'ground' && activeTool.value !== 'fill') setTool('ground')
}

function handleObjectSelect(gid: number, layerName: string) {
  selectedGid.value = gid
  bridge.setSelectedGid(gid)
  bridge.setTargetLayer(layerName)
  activeLayer.value = layerName
  paletteTab.value = 'object'
  if (activeTool.value !== 'ground') setTool('ground')
  bridge.setTool('object')
}

function handleLayerSelect(layerName: string) {
  activeLayer.value = layerName
  bridge.setTargetLayer(layerName)
}

function handleToggleVisibility(layerName: string, visible: boolean) {
  bridge.toggleLayerVisibility(layerName, visible)
}

function handleUpdatePosition(layerName: string, objId: number, x: number, y: number) {
  bridge.updateObjectPosition(layerName, objId, x, y)
}

function handleDeleteFromPanel() {
  bridge.deleteSelected()
}

function toggleCollision() {
  bridge.toggleCollisionPreview()
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
    <!-- ====== Phaser Canvas（全螢幕底層）====== -->
    <div id="editor-canvas" class="absolute inset-0" />

    <!-- ====== 頂部選單列 ====== -->
    <div class="absolute top-0 left-0 right-0 z-[61] flex items-center gap-2 px-3 py-1.5 bg-gray-800/90 backdrop-blur-sm border-b border-gray-700 text-xs">
      <!-- Undo / Redo -->
      <button class="px-1.5 py-1 rounded bg-gray-700 text-gray-300 hover:bg-gray-600" title="復原 (Ctrl+Z)" @click="handleUndo">↩</button>
      <button class="px-1.5 py-1 rounded bg-gray-700 text-gray-300 hover:bg-gray-600" title="重做 (Ctrl+Shift+Z)" @click="handleRedo">↪</button>

      <div class="w-px h-4 bg-gray-600" />

      <!-- 碰撞 -->
      <button
        :class="['px-2 py-1 rounded font-medium', showCollision ? 'bg-orange-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600']"
        title="碰撞預覽 (C)"
        @click="toggleCollision"
      >碰撞</button>

      <!-- 狀態 -->
      <span class="text-gray-500 ml-1">
        {{ activeLayer }} · GID {{ selectedGid }}
      </span>

      <div class="flex-1" />

      <span class="text-gray-600">左鍵操作 · 右鍵平移 · 滾輪縮放</span>

      <div class="w-px h-4 bg-gray-600" />

      <button class="px-2 py-1 rounded bg-gray-700 text-gray-300 hover:bg-gray-600" @click="downloadMapJson">匯出</button>
      <button class="px-2 py-1 rounded bg-gray-700 text-gray-300 hover:bg-gray-600" @click="uploadMapJson">匯入</button>
      <button
        :disabled="isSaving"
        :class="['px-3 py-1 rounded font-medium text-white', isSaving ? 'bg-green-800' : 'bg-green-600 hover:bg-green-500']"
        @click="handleSave"
      >{{ isSaving ? '儲存中...' : '儲存' }}</button>
      <button class="px-3 py-1 rounded bg-gray-700 text-gray-300 hover:bg-gray-600" @click="emit('cancel')">退出</button>
    </div>

    <!-- ====== 浮動工具箱（左側垂直）====== -->
    <div class="absolute left-3 top-14 z-[62] flex flex-col gap-0.5 bg-gray-800/95 backdrop-blur-sm rounded-lg border border-gray-600 p-1 shadow-xl">
      <button
        v-for="t in toolbox"
        :key="t.key"
        :class="[
          'w-9 h-9 rounded flex items-center justify-center text-lg transition-colors',
          activeTool === t.key
            ? 'bg-blue-600 text-white'
            : 'text-gray-300 hover:bg-gray-700',
        ]"
        :title="`${t.label} (${t.shortcut})`"
        @click="setTool(t.key)"
      >
        {{ t.icon }}
      </button>
    </div>

    <!-- ====== 浮動素材面板（地板 + 物件 Tab 切換）====== -->
    <FloatingPanel
      title="素材"
      :initial-x="60"
      :initial-y="56"
      width="240px"
    >
      <!-- Tab 切換 -->
      <div class="flex border-b border-gray-700">
        <button
          :class="['flex-1 px-3 py-1.5 text-xs font-medium', paletteTab === 'ground' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200']"
          @click="switchPaletteTab('ground')"
        >
          地板
        </button>
        <button
          :class="['flex-1 px-3 py-1.5 text-xs font-medium', paletteTab === 'object' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200']"
          @click="switchPaletteTab('object')"
        >
          物件
        </button>
      </div>

      <!-- 地板面板 -->
      <div v-if="paletteTab === 'ground'" class="p-2 max-h-64 overflow-y-auto">
        <div class="grid grid-cols-5 gap-1">
          <button
            v-for="item in groundThumbs"
            :key="item.gid"
            :class="[
              'w-full aspect-square rounded border-2 p-0 overflow-hidden',
              selectedGid === item.gid ? 'border-blue-400' : 'border-gray-600 hover:border-gray-400',
            ]"
            :title="`GID ${item.gid}`"
            @click="selectTile(item.gid)"
          >
            <img :src="item.dataUrl" class="w-full h-full" style="image-rendering: pixelated" />
          </button>
        </div>
      </div>

      <!-- 物件面板 -->
      <div v-else class="max-h-80 overflow-hidden">
        <ObjectPalette
          :scene="sceneRef"
          :tileset-infos="tilesetInfos"
          @select="handleObjectSelect"
        />
      </div>
    </FloatingPanel>

    <!-- ====== 浮動圖層面板 ====== -->
    <FloatingPanel
      title="圖層"
      :initial-x="layerPanelX"
      :initial-y="56"
      width="200px"
    >
      <LayerPanel
        :active-layer="activeLayer"
        @select-layer="handleLayerSelect"
        @toggle-visibility="handleToggleVisibility"
      />
    </FloatingPanel>

    <!-- ====== 浮動屬性面板（選取物件時顯示）====== -->
    <FloatingPanel
      v-if="selection"
      title="屬性"
      :initial-x="propPanelX"
      :initial-y="380"
      width="200px"
    >
      <PropertyPanel
        :selection="selection"
        @update-position="handleUpdatePosition"
        @delete="handleDeleteFromPanel"
      />
    </FloatingPanel>
  </div>
</template>
