<script setup lang="ts">
import { ref, shallowRef, onMounted, onUnmounted, nextTick, watch } from 'vue'
import Phaser from 'phaser'
import Room2EditorScene, { type EditorTool, type SelectionInfo } from '../game2/Room2EditorScene'
import type { TilesetInfo } from '../game2/tilesetRegistry'
import type { TiledMapJson } from '../game2/mapSerializer'
import { EditorBridge, EditorEvents } from '../game2/editorBridge'
import { extractThumbnailsForKey, type ThumbnailItem } from '../game2/thumbnailExtractor'
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

const activeTool = ref<EditorTool>('ground')
const selectedGid = ref(1)
const activeLayer = ref('Objects')
const selection = ref<SelectionInfo | null>(null)
const showCollision = ref(false)

let game: Phaser.Game | null = null
const bridge = new EditorBridge()
let backupInterval: number | null = null

const sceneRef = shallowRef<Phaser.Scene | null>(null)
const tilesetInfos = ref<TilesetInfo[]>([])

const tools: { key: EditorTool; label: string; icon: string }[] = [
  { key: 'ground', label: '地板', icon: '🏗' },
  { key: 'fill', label: '填充', icon: '🪣' },
  { key: 'object', label: '物件', icon: '📦' },
  { key: 'eraser', label: '橡皮擦', icon: '🧹' },
  { key: 'select', label: '選取', icon: '👆' },
]

// ── 地板 tile 縮圖 (#5) ─────────────────────────────────────────

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

  // 檢查 localStorage 備份
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

  // 自動備份 (30s)
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

function handleUndo() { bridge.undo() }
function handleRedo() { bridge.redo() }

function setTool(tool: EditorTool) {
  activeTool.value = tool
  bridge.setTool(tool)
}

function selectTile(gid: number) {
  selectedGid.value = gid
  bridge.setSelectedGid(gid)
  if (activeTool.value !== 'ground' && activeTool.value !== 'fill') setTool('ground')
}

function handleObjectSelect(gid: number, layerName: string) {
  selectedGid.value = gid
  bridge.setSelectedGid(gid)
  bridge.setTargetLayer(layerName)
  activeLayer.value = layerName
  if (activeTool.value !== 'object') setTool('object')
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

// ── 匯出 JSON 下載 ──────────────────────────────────────────────

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

// ── 匯入 JSON 上傳 ──────────────────────────────────────────────

const MAX_IMPORT_SIZE = 10 * 1024 * 1024 // 10MB

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
    if (file.size > MAX_IMPORT_SIZE) {
      alert('檔案過大，上限 10MB')
      return
    }
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
      } catch {
        alert('JSON 解析失敗')
      }
    }
    reader.readAsText(file)
  }
  input.click()
}

// ── 儲存 ────────────────────────────────────────────────────────

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

function handleCancel() {
  emit('cancel')
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex flex-col bg-gray-900">
    <!-- 頂部工具列 -->
    <div class="flex items-center gap-2 px-4 py-2 bg-gray-800 border-b border-gray-700">
      <div class="flex gap-1">
        <button
          v-for="t in tools"
          :key="t.key"
          :class="[
            'px-3 py-1.5 rounded text-sm font-medium transition-colors',
            activeTool === t.key
              ? 'bg-blue-600 text-white'
              : 'bg-gray-700 text-gray-300 hover:bg-gray-600',
          ]"
          @click="setTool(t.key)"
        >
          {{ t.icon }} {{ t.label }}
        </button>
      </div>

      <!-- Undo / Redo -->
      <div class="flex gap-0.5 ml-2">
        <button
          class="px-2 py-1.5 rounded text-sm bg-gray-700 text-gray-300 hover:bg-gray-600"
          title="復原 (Ctrl+Z)"
          @click="handleUndo"
        >
          ↩
        </button>
        <button
          class="px-2 py-1.5 rounded text-sm bg-gray-700 text-gray-300 hover:bg-gray-600"
          title="重做 (Ctrl+Shift+Z)"
          @click="handleRedo"
        >
          ↪
        </button>
      </div>

      <!-- 碰撞預覽 -->
      <button
        :class="[
          'px-2 py-1.5 rounded text-sm font-medium transition-colors ml-1',
          showCollision
            ? 'bg-orange-600 text-white'
            : 'bg-gray-700 text-gray-300 hover:bg-gray-600',
        ]"
        title="碰撞預覽 (C)"
        @click="toggleCollision"
      >
        碰撞
      </button>

      <div class="text-xs text-gray-500 ml-2">
        Layer: <span class="text-gray-300">{{ activeLayer }}</span>
        · GID: <span class="text-gray-300">{{ selectedGid }}</span>
      </div>

      <div class="flex-1" />

      <div class="text-xs text-gray-600 mr-2">
        左鍵操作 · 中鍵/Space 平移 · 滾輪縮放 · Del 刪除 · C 碰撞
      </div>

      <div class="flex gap-1">
        <button
          class="px-3 py-1.5 rounded text-xs font-medium bg-gray-700 text-gray-300 hover:bg-gray-600"
          title="匯出 JSON"
          @click="downloadMapJson"
        >
          匯出
        </button>
        <button
          class="px-3 py-1.5 rounded text-xs font-medium bg-gray-700 text-gray-300 hover:bg-gray-600"
          title="匯入 JSON"
          @click="uploadMapJson"
        >
          匯入
        </button>
        <button
          :disabled="isSaving"
          :class="[
            'px-4 py-1.5 rounded text-sm font-medium text-white',
            isSaving ? 'bg-green-800 cursor-wait' : 'bg-green-600 hover:bg-green-500',
          ]"
          @click="handleSave"
        >
          {{ isSaving ? '儲存中...' : '儲存' }}
        </button>
        <button
          class="px-4 py-1.5 rounded text-sm font-medium bg-gray-700 text-gray-300 hover:bg-gray-600"
          @click="handleCancel"
        >
          退出
        </button>
      </div>
    </div>

    <!-- 主體：左側面板 + 畫布 + 右側面板 -->
    <div class="flex flex-1 overflow-hidden">
      <!-- 左側：物件面板 -->
      <div
        v-if="activeTool === 'object'"
        class="w-56 border-r border-gray-700 flex-shrink-0 overflow-hidden"
      >
        <ObjectPalette
          :scene="sceneRef"
          :tileset-infos="tilesetInfos"
          @select="handleObjectSelect"
        />
      </div>

      <!-- Phaser Canvas -->
      <div id="editor-canvas" class="flex-1" />

      <!-- 右側：圖層面板 + 屬性面板 -->
      <div class="w-48 border-l border-gray-700 flex-shrink-0 overflow-hidden flex flex-col">
        <div class="flex-1 overflow-y-auto">
          <LayerPanel
            :active-layer="activeLayer"
            @select-layer="handleLayerSelect"
            @toggle-visibility="handleToggleVisibility"
          />
        </div>
        <div class="border-t border-gray-700">
          <PropertyPanel
            :selection="selection"
            @update-position="handleUpdatePosition"
            @delete="handleDeleteFromPanel"
          />
        </div>
      </div>
    </div>

    <!-- 底部面板：地板 tile 選擇（含縮圖） -->
    <div
      v-if="activeTool === 'ground' || activeTool === 'fill'"
      class="bg-gray-800 border-t border-gray-700 p-2"
    >
      <div class="flex gap-1 overflow-x-auto">
        <button
          v-for="item in groundThumbs"
          :key="item.gid"
          :class="[
            'w-10 h-10 rounded border-2 flex-shrink-0 p-0 overflow-hidden',
            selectedGid === item.gid
              ? 'border-blue-400'
              : 'border-gray-600 hover:border-gray-400',
          ]"
          :title="`Tile GID ${item.gid}`"
          @click="selectTile(item.gid)"
        >
          <img :src="item.dataUrl" class="w-full h-full" style="image-rendering: pixelated" />
        </button>
      </div>
    </div>
  </div>
</template>
