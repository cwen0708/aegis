<script setup lang="ts">
import { ref, watch } from 'vue'
import { EDITOR_LAYERS, type EditorLayerDef } from '../../game2/Room2EditorScene'

const props = defineProps<{
  activeLayer: string
  showCollision?: boolean
}>()

const emit = defineEmits<{
  (e: 'select-layer', layerName: string): void
  (e: 'toggle-visibility', layerName: string, visible: boolean): void
  (e: 'toggle-collision'): void
}>()

const currentLayer = ref(props.activeLayer)
const visibility = ref<Record<string, boolean>>(
  Object.fromEntries(EDITOR_LAYERS.map(l => [l.name, true]))
)

watch(() => props.activeLayer, (v) => { currentLayer.value = v })

function selectLayer(layer: EditorLayerDef) {
  if (!layer.editable) return
  currentLayer.value = layer.name
  emit('select-layer', layer.name)
}

function toggleVisibility(layerName: string) {
  visibility.value[layerName] = !visibility.value[layerName]
  emit('toggle-visibility', layerName, visibility.value[layerName])
}
</script>

<template>
  <div class="flex flex-col bg-gray-800 text-sm">
    <div class="flex-1 overflow-y-auto">
      <div
        v-for="layer in EDITOR_LAYERS"
        :key="layer.name"
        :class="[
          'flex items-center gap-1.5 px-2 py-1 cursor-pointer border-l-2 transition-colors',
          currentLayer === layer.name
            ? 'bg-gray-700 border-blue-400'
            : 'border-transparent hover:bg-gray-700/50',
          !layer.editable && 'opacity-50',
        ]"
        @click="selectLayer(layer)"
      >
        <input
          type="checkbox"
          :checked="visibility[layer.name]"
          class="w-3 h-3 rounded border-gray-600 bg-gray-900 text-blue-500 cursor-pointer"
          @click.stop="toggleVisibility(layer.name)"
        />
        <span :class="['flex-1 truncate text-xs', currentLayer === layer.name ? 'text-white' : 'text-gray-300']">
          {{ layer.label }}
        </span>
        <span v-if="!layer.editable" class="text-[9px] text-gray-600">🔒</span>
      </div>

      <!-- 碰撞預覽虛擬圖層 -->
      <div
        :class="[
          'flex items-center gap-1.5 px-2 py-1 cursor-pointer border-l-2 transition-colors border-t border-gray-700/50 mt-0.5',
          'border-transparent hover:bg-gray-700/50',
        ]"
        @click="emit('toggle-collision')"
      >
        <input
          type="checkbox"
          :checked="showCollision"
          class="w-3 h-3 rounded border-gray-600 bg-gray-900 text-orange-500 cursor-pointer"
          @click.stop="emit('toggle-collision')"
        />
        <span class="flex-1 truncate text-xs text-orange-400/70">
          碰撞區域
        </span>
      </div>
    </div>
  </div>
</template>
