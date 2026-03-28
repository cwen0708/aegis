<script setup lang="ts">
import { ref, watch } from 'vue'
import { EDITOR_LAYERS, type EditorLayerDef } from '../../game2/Room2EditorScene'

const props = defineProps<{
  activeLayer: string
}>()

const emit = defineEmits<{
  (e: 'select-layer', layerName: string): void
  (e: 'toggle-visibility', layerName: string, visible: boolean): void
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

const typeIcons: Record<string, string> = {
  tile: '▦',
  object: '◆',
}
</script>

<template>
  <div class="flex flex-col bg-gray-800 text-sm">
    <div class="px-2 py-1.5 text-xs text-gray-400 font-medium border-b border-gray-700">
      圖層
    </div>
    <div class="flex-1 overflow-y-auto">
      <div
        v-for="layer in EDITOR_LAYERS"
        :key="layer.name"
        :class="[
          'flex items-center gap-1.5 px-2 py-1.5 cursor-pointer border-l-2 transition-colors',
          currentLayer === layer.name
            ? 'bg-gray-700 border-blue-400'
            : 'border-transparent hover:bg-gray-750',
          !layer.editable && 'opacity-50',
        ]"
        @click="selectLayer(layer)"
      >
        <input
          type="checkbox"
          :checked="visibility[layer.name]"
          class="w-3.5 h-3.5 rounded border-gray-600 bg-gray-900 text-blue-500 cursor-pointer"
          @click.stop="toggleVisibility(layer.name)"
        />
        <span class="text-gray-500 text-xs w-4 text-center">{{ typeIcons[layer.type] }}</span>
        <span :class="['flex-1 truncate', currentLayer === layer.name ? 'text-white' : 'text-gray-300']">
          {{ layer.label }}
        </span>
        <span v-if="!layer.editable" class="text-[10px] text-gray-600">🔒</span>
      </div>
    </div>
  </div>
</template>
