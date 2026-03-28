<script setup lang="ts">
import { ref, watch } from 'vue'
import { TILE_SIZE } from '../../game2/tilesetRegistry'
import type { SelectionInfo } from '../../game2/Room2EditorScene'

const props = defineProps<{
  selection: SelectionInfo | null
}>()

const emit = defineEmits<{
  (e: 'update-position', layerName: string, objId: number, x: number, y: number): void
  (e: 'delete', layerName: string, objId: number): void
}>()

const editX = ref(0)
const editY = ref(0)

watch(() => props.selection, (sel) => {
  if (sel) {
    editX.value = sel.obj.x
    editY.value = sel.obj.y
  }
}, { immediate: true })

function applyPosition() {
  if (!props.selection) return
  const x = Math.round(editX.value / TILE_SIZE) * TILE_SIZE
  const y = Math.round(editY.value / TILE_SIZE) * TILE_SIZE
  editX.value = x
  editY.value = y
  emit('update-position', props.selection.layerName, props.selection.obj.id, x, y)
}

function handleDelete() {
  if (!props.selection) return
  emit('delete', props.selection.layerName, props.selection.obj.id)
}
</script>

<template>
  <div class="bg-gray-800 text-sm p-3">
    <div class="text-xs text-gray-400 font-medium mb-2">屬性</div>

    <template v-if="selection">
      <div class="space-y-2">
        <!-- GID -->
        <div class="flex items-center gap-2">
          <span class="text-gray-500 w-12">GID</span>
          <span class="text-gray-300">{{ selection.obj.gid }}</span>
        </div>

        <!-- Layer -->
        <div class="flex items-center gap-2">
          <span class="text-gray-500 w-12">Layer</span>
          <span class="text-gray-300 text-xs">{{ selection.layerName }}</span>
        </div>

        <!-- Size -->
        <div class="flex items-center gap-2">
          <span class="text-gray-500 w-12">Size</span>
          <span class="text-gray-300 text-xs">{{ selection.obj.width }}×{{ selection.obj.height }}</span>
        </div>

        <!-- X -->
        <div class="flex items-center gap-2">
          <label class="text-gray-500 w-12">X</label>
          <input
            v-model.number="editX"
            type="number"
            :step="TILE_SIZE"
            class="w-full bg-gray-900 border border-gray-600 rounded px-2 py-1 text-gray-300 text-xs"
            @change="applyPosition"
          />
        </div>

        <!-- Y -->
        <div class="flex items-center gap-2">
          <label class="text-gray-500 w-12">Y</label>
          <input
            v-model.number="editY"
            type="number"
            :step="TILE_SIZE"
            class="w-full bg-gray-900 border border-gray-600 rounded px-2 py-1 text-gray-300 text-xs"
            @change="applyPosition"
          />
        </div>

        <!-- Delete -->
        <button
          class="w-full mt-2 px-3 py-1.5 rounded text-xs font-medium bg-red-700 text-white hover:bg-red-600"
          @click="handleDelete"
        >
          刪除物件
        </button>
      </div>
    </template>

    <p v-else class="text-gray-600 text-xs">
      選取模式下點擊物件查看屬性
    </p>
  </div>
</template>
