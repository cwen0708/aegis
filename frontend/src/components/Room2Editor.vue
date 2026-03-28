<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import Phaser from 'phaser'
import Room2EditorScene, { type EditorTool } from '../game2/Room2EditorScene'

const emit = defineEmits<{
  (e: 'save', mapJson: object): void
  (e: 'cancel'): void
}>()

const activeTool = ref<EditorTool>('ground')
const selectedGid = ref(1)

let game: Phaser.Game | null = null
let editorScene: Room2EditorScene | null = null

const tools: { key: EditorTool; label: string; icon: string }[] = [
  { key: 'ground', label: '地板', icon: '🏗' },
  { key: 'eraser', label: '橡皮擦', icon: '🧹' },
  { key: 'select', label: '選取', icon: '👆' },
]

onMounted(async () => {
  await document.fonts.ready
  await nextTick()

  const scene = new Room2EditorScene()

  game = new Phaser.Game({
    type: Phaser.AUTO,
    parent: 'editor-canvas',
    backgroundColor: '#1a1a2e',
    pixelArt: true,
    scale: { mode: Phaser.Scale.RESIZE, parent: 'editor-canvas' },
    scene: [],
  })

  game.scene.add('room2-editor', scene, true)

  game.events.once('editor-ready', () => {
    editorScene = scene
  })
})

onUnmounted(() => {
  game?.destroy(true)
  game = null
  editorScene = null
})

function setTool(tool: EditorTool) {
  activeTool.value = tool
  editorScene?.setTool(tool)
}

function selectTile(gid: number) {
  selectedGid.value = gid
  editorScene?.setSelectedGid(gid)
  if (activeTool.value !== 'ground') setTool('ground')
}

function handleSave() {
  if (!editorScene) return
  const mapData = editorScene.getMapData()
  emit('save', mapData)
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

      <div class="flex-1" />

      <div class="flex gap-2">
        <button
          class="px-4 py-1.5 rounded text-sm font-medium bg-green-600 text-white hover:bg-green-500"
          @click="handleSave"
        >
          儲存
        </button>
        <button
          class="px-4 py-1.5 rounded text-sm font-medium bg-gray-700 text-gray-300 hover:bg-gray-600"
          @click="handleCancel"
        >
          退出
        </button>
      </div>
    </div>

    <!-- 主體 -->
    <div class="flex flex-1 overflow-hidden">
      <!-- Phaser Canvas -->
      <div id="editor-canvas" class="flex-1" />
    </div>

    <!-- 底部面板：地板 tile 選擇 -->
    <div
      v-if="activeTool === 'ground'"
      class="bg-gray-800 border-t border-gray-700 p-2"
    >
      <div class="flex gap-1 overflow-x-auto">
        <button
          v-for="gid in 20"
          :key="gid"
          :class="[
            'w-10 h-10 rounded border-2 flex-shrink-0',
            selectedGid === gid
              ? 'border-blue-400'
              : 'border-gray-600 hover:border-gray-400',
          ]"
          :title="`Tile GID ${gid}`"
          @click="selectTile(gid)"
        >
          <span class="text-xs text-gray-400">{{ gid }}</span>
        </button>
      </div>
    </div>
  </div>
</template>
