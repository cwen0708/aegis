<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import type { TilesetInfo } from '../../game2/tilesetRegistry'
import { extractThumbnailsBatched, type ThumbnailItem } from '../../game2/thumbnailExtractor'

const props = defineProps<{
  scene: Phaser.Scene | null
  tilesetInfos: TilesetInfo[]
}>()

const emit = defineEmits<{
  (e: 'select', gid: number, layerName: string): void
}>()

interface TilesetCategory {
  label: string
  key: string
  targetLayer: string
}

const CATEGORIES: TilesetCategory[] = [
  { label: '桌椅', key: 'tiles_office', targetLayer: 'Objects' },
  { label: '椅子', key: 'chairs', targetLayer: 'Chair' },
  { label: '電腦', key: 'computers', targetLayer: 'Computer' },
  { label: '白板', key: 'whiteboards', targetLayer: 'Whiteboard' },
  { label: '通用裝飾', key: 'tiles_generic', targetLayer: 'GenericObjects' },
  { label: '地下室', key: 'tiles_basement', targetLayer: 'Basement' },
  { label: '販賣機', key: 'vendingmachines', targetLayer: 'VendingMachine' },
]

const activeCategory = ref(CATEGORIES[0]?.key ?? 'tiles_office')
const thumbnails = ref<Map<string, ThumbnailItem[]>>(new Map())

const currentThumbnails = computed(() => {
  return thumbnails.value.get(activeCategory.value) || []
})

const currentTargetLayer = computed(() => {
  return CATEGORIES.find(c => c.key === activeCategory.value)?.targetLayer || 'Objects'
})

async function generateThumbnails() {
  if (!props.scene) return

  const keys = CATEGORIES.map(c => c.key)
  const result = await extractThumbnailsBatched(
    props.scene.textures, props.tilesetInfos, keys, 80,
  )
  thumbnails.value = result
}

function handleSelect(gid: number) {
  emit('select', gid, currentTargetLayer.value)
}

watch(() => props.scene, (scene) => {
  if (scene) generateThumbnails()
})

onMounted(() => {
  if (props.scene) generateThumbnails()
})
</script>

<template>
  <div class="flex flex-col h-full bg-gray-800">
    <!-- 分類 Tabs -->
    <div class="flex flex-wrap gap-1 p-2 border-b border-gray-700">
      <button
        v-for="cat in CATEGORIES"
        :key="cat.key"
        :class="[
          'px-2 py-1 rounded text-xs font-medium transition-colors',
          activeCategory === cat.key
            ? 'bg-blue-600 text-white'
            : 'bg-gray-700 text-gray-300 hover:bg-gray-600',
        ]"
        @click="activeCategory = cat.key"
      >
        {{ cat.label }}
      </button>
    </div>

    <!-- 物件縮圖網格 -->
    <div class="flex-1 overflow-y-auto p-2">
      <div class="grid grid-cols-4 gap-1">
        <button
          v-for="item in currentThumbnails"
          :key="item.gid"
          class="relative group border border-gray-600 rounded hover:border-blue-400 bg-gray-900 p-0.5"
          :title="`GID ${item.gid}`"
          @click="handleSelect(item.gid)"
        >
          <img
            :src="item.dataUrl"
            class="w-full h-auto"
            style="image-rendering: pixelated"
            :alt="`tile ${item.gid}`"
          />
          <span class="absolute bottom-0 right-0 text-[9px] text-gray-500 bg-gray-900/80 px-0.5">
            {{ item.gid }}
          </span>
        </button>
      </div>
      <p v-if="currentThumbnails.length === 0" class="text-gray-500 text-xs text-center mt-4">
        載入中...
      </p>
    </div>
  </div>
</template>
