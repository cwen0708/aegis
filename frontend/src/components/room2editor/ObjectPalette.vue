<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import type { TilesetInfo } from '../../game2/tilesetRegistry'
import { TILESET_PRELOAD_CONFIG } from '../../game2/tilesetRegistry'
import type { ThumbnailItem } from '../../game2/thumbnailExtractor'
import {
  loadCompositeConfig, getCompositeGidSet,
  getCompositesByCategory, getNativeObjectDef,
  type CompositeObject, type PaletteCategory,
} from '../../game2/compositeObjects'

const props = defineProps<{
  scene: Phaser.Scene | null
  tilesetInfos: TilesetInfo[]
}>()

const emit = defineEmits<{
  (e: 'select', gid: number, layerName: string): void
  (e: 'select-composite', composite: CompositeObject): void
}>()

const categories = ref<PaletteCategory[]>([])
const activeCategory = ref('tiles_floor')
const thumbnails = ref<Map<string, ThumbnailItem[]>>(new Map())
const compositeThumbs = ref<Map<string, { comp: CompositeObject; dataUrl: string }[]>>(new Map())

const currentThumbnails = computed(() => {
  return thumbnails.value.get(activeCategory.value) || []
})

const currentComposites = computed(() => {
  return compositeThumbs.value.get(activeCategory.value) || []
})

const currentTargetLayer = computed(() => {
  return categories.value.find(c => c.key === activeCategory.value)?.targetLayer || 'Objects'
})

async function generateThumbnails() {
  if (!props.scene) return

  // 從 JSON 載入所有配置
  const config = await loadCompositeConfig()
  categories.value = config.categories
  if (categories.value.length > 0) {
    activeCategory.value = categories.value[0]!.key
  }

  const textures = props.scene.textures
  const compositeGidSet = getCompositeGidSet()

  for (const cat of categories.value) {
    // 單 tile 縮圖（過濾掉組合物件的 GID）
    const { extractThumbnailsForKey } = await import('../../game2/thumbnailExtractor')
    const allItems = extractThumbnailsForKey(
      textures, props.tilesetInfos, cat.key, cat.maxCount ?? 80,
    )
    const filtered = allItems.filter(item => !compositeGidSet.has(item.gid))
    thumbnails.value.set(cat.key, filtered)

    // 組合物件縮圖
    const composites = getCompositesByCategory(cat.key)
    const compThumbs: { comp: CompositeObject; dataUrl: string }[] = []
    for (const comp of composites) {
      const dataUrl = renderCompositeThumbnail(textures, comp)
      if (dataUrl) compThumbs.push({ comp, dataUrl })
    }
    compositeThumbs.value.set(cat.key, compThumbs)

    await new Promise<void>(r => requestAnimationFrame(() => r()))
  }
  thumbnails.value = new Map(thumbnails.value)
  compositeThumbs.value = new Map(compositeThumbs.value)
}

function renderCompositeThumbnail(
  textures: Phaser.Textures.TextureManager,
  comp: CompositeObject,
): string | null {
  if (comp.tiles.length === 0) return null

  const firstTile = comp.tiles[0]!
  const info = props.tilesetInfos.find(i => firstTile.gid >= i.firstgid && firstTile.gid <= i.lastgid)
  if (!info) return null

  const cfg = TILESET_PRELOAD_CONFIG.find(c => c.key === info.spriteKey)
  if (!cfg) return null

  const tex = textures.get(cfg.key)
  if (!tex) return null
  const source = tex.source[0]?.image as HTMLImageElement | undefined
  if (!source) return null

  const fw = cfg.frameWidth
  const fh = cfg.frameHeight
  const imgCols = Math.floor(source.width / fw)

  const canvas = document.createElement('canvas')
  canvas.width = comp.cols * fw
  canvas.height = comp.rows * fh
  const ctx = canvas.getContext('2d')!

  for (const tile of comp.tiles) {
    const frame = tile.gid - info.firstgid
    const sx = (frame % imgCols) * fw
    const sy = Math.floor(frame / imgCols) * fh
    ctx.drawImage(source, sx, sy, fw, fh, tile.col * fw, tile.row * fh, fw, fh)
  }

  return canvas.toDataURL()
}

function handleSelect(gid: number) {
  // 原生物件用 JSON 定義的 layer，其餘用 category 預設值
  const native = getNativeObjectDef(gid)
  const layer = native ? native.layer : currentTargetLayer.value
  emit('select', gid, layer)
}

function handleCompositeSelect(comp: CompositeObject) {
  emit('select-composite', comp)
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
    <!-- 分類橫排（從 JSON 載入） -->
    <div class="flex overflow-x-auto gap-0 border-b border-gray-700 flex-shrink-0">
      <button
        v-for="cat in categories"
        :key="cat.key"
        :class="[
          'px-2.5 py-1.5 text-xs font-medium whitespace-nowrap border-b-2 transition-colors',
          activeCategory === cat.key
            ? 'border-blue-400 text-white bg-gray-700/50'
            : 'border-transparent text-gray-400 hover:text-gray-200 hover:bg-gray-700/30',
        ]"
        @click="activeCategory = cat.key"
      >
        {{ cat.label }}
      </button>
    </div>

    <!-- 瀑布式佈局：組合物件 + 單 tile 混排，按實際格數大小 -->
    <div class="flex-1 overflow-y-auto p-1.5">
      <div class="flex flex-wrap gap-1 palette-flow">
        <!-- 組合物件 -->
        <button
          v-for="(item, idx) in currentComposites"
          :key="'comp-' + idx"
          class="relative border border-gray-600 rounded hover:border-blue-400 bg-gray-900 overflow-hidden flex-shrink-0"
          :style="{ width: item.comp.cols * 32 + 'px', height: item.comp.rows * 32 + 'px' }"
          :title="item.comp.name"
          @click="handleCompositeSelect(item.comp)"
        >
          <img
            :src="item.dataUrl"
            class="w-full h-full"
            style="image-rendering: pixelated"
            :alt="item.comp.name"
          />
          <span class="absolute bottom-0 left-0 right-0 text-[7px] text-gray-400 bg-gray-900/80 px-0.5 text-center truncate leading-tight">
            {{ item.comp.name }}
          </span>
        </button>
        <!-- 單 tile -->
        <button
          v-for="item in currentThumbnails"
          :key="item.gid"
          class="relative border border-gray-600 rounded hover:border-blue-400 bg-gray-900 overflow-hidden flex-shrink-0"
          style="width: 32px; height: 32px"
          :title="`GID ${item.gid}`"
          @click="handleSelect(item.gid)"
        >
          <img
            :src="item.dataUrl"
            class="w-full h-full"
            style="image-rendering: pixelated"
            :alt="`tile ${item.gid}`"
          />
        </button>
      </div>
      <p v-if="currentThumbnails.length === 0 && currentComposites.length === 0" class="text-gray-500 text-xs text-center mt-4">
        載入中...
      </p>
    </div>
  </div>
</template>
