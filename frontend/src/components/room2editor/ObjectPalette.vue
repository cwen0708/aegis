<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import type { TilesetInfo } from '../../game2/tilesetRegistry'
import { TILESET_PRELOAD_CONFIG } from '../../game2/tilesetRegistry'
import type { ThumbnailItem } from '../../game2/thumbnailExtractor'
import {
  getCompositeGidSet, getCompositesByCategory,
  type CompositeObject,
} from '../../game2/compositeObjects'

const props = defineProps<{
  scene: Phaser.Scene | null
  tilesetInfos: TilesetInfo[]
}>()

const emit = defineEmits<{
  (e: 'select', gid: number, layerName: string): void
  (e: 'select-composite', composite: CompositeObject): void
}>()

interface PaletteCategory {
  label: string
  key: string
  targetLayer: string
  maxCount?: number
}

const CATEGORIES: PaletteCategory[] = [
  { label: '地板', key: 'tiles_floor', targetLayer: 'Ground', maxCount: 120 },
  { label: '桌椅', key: 'tiles_office', targetLayer: 'Objects' },
  { label: '椅子', key: 'chairs', targetLayer: 'Chair' },
  { label: '電腦', key: 'computers', targetLayer: 'Computer' },
  { label: '白板', key: 'whiteboards', targetLayer: 'Whiteboard' },
  { label: '裝飾', key: 'tiles_generic', targetLayer: 'GenericObjects' },
  { label: '其他', key: 'tiles_basement', targetLayer: 'Basement' },
  { label: '販賣機', key: 'vendingmachines', targetLayer: 'VendingMachine' },
]

const activeCategory = ref(CATEGORIES[0]?.key ?? 'tiles_floor')
const thumbnails = ref<Map<string, ThumbnailItem[]>>(new Map())
const compositeThumbs = ref<Map<string, { comp: CompositeObject; dataUrl: string }[]>>(new Map())

// 組合物件包含的 GID，用於過濾單 tile 列表
const compositeGids = getCompositeGidSet()

const currentThumbnails = computed(() => {
  return thumbnails.value.get(activeCategory.value) || []
})

const currentComposites = computed(() => {
  return compositeThumbs.value.get(activeCategory.value) || []
})

const currentTargetLayer = computed(() => {
  return CATEGORIES.find(c => c.key === activeCategory.value)?.targetLayer || 'Objects'
})

async function generateThumbnails() {
  if (!props.scene) return
  const textures = props.scene.textures

  for (const cat of CATEGORIES) {
    // 單 tile 縮圖（過濾掉組合物件的 GID）
    const { extractThumbnailsForKey } = await import('../../game2/thumbnailExtractor')
    const allItems = extractThumbnailsForKey(
      textures, props.tilesetInfos, cat.key, cat.maxCount ?? 80,
    )
    const filtered = allItems.filter(item => !compositeGids.has(item.gid))
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
  const rows = comp.gids.length
  const cols = Math.max(...comp.gids.map(r => r.length))

  // 找到第一個 GID 所屬的 tileset config
  const firstGid = comp.gids[0]?.[0]
  if (!firstGid) return null

  const info = props.tilesetInfos.find(i => firstGid >= i.firstgid && firstGid <= i.lastgid)
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
  canvas.width = cols * fw
  canvas.height = rows * fh
  const ctx = canvas.getContext('2d')!

  for (let r = 0; r < rows; r++) {
    const rowGids = comp.gids[r]
    if (!rowGids) continue
    for (let c = 0; c < rowGids.length; c++) {
      const gid = rowGids[c]
      if (!gid) continue
      const frame = gid - info.firstgid
      const sx = (frame % imgCols) * fw
      const sy = Math.floor(frame / imgCols) * fh
      ctx.drawImage(source, sx, sy, fw, fh, c * fw, r * fh, fw, fh)
    }
  }

  return canvas.toDataURL()
}

function handleSelect(gid: number) {
  emit('select', gid, currentTargetLayer.value)
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
    <!-- 分類橫排 -->
    <div class="flex overflow-x-auto gap-0 border-b border-gray-700 flex-shrink-0">
      <button
        v-for="cat in CATEGORIES"
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

    <!-- 縮圖網格 -->
    <div class="flex-1 overflow-y-auto p-2">
      <!-- 組合物件（優先顯示在最上方） -->
      <div v-if="currentComposites.length > 0" class="mb-2">
        <div class="text-[10px] text-gray-500 mb-1">組合物件</div>
        <div class="grid grid-cols-3 gap-1">
          <button
            v-for="(item, idx) in currentComposites"
            :key="'comp-' + idx"
            class="relative border border-gray-600 rounded hover:border-blue-400 bg-gray-900 p-0.5 overflow-hidden"
            :title="item.comp.name"
            @click="handleCompositeSelect(item.comp)"
          >
            <img
              :src="item.dataUrl"
              class="w-full h-auto"
              style="image-rendering: pixelated"
              :alt="item.comp.name"
            />
            <span class="absolute bottom-0 left-0 right-0 text-[8px] text-gray-400 bg-gray-900/80 px-0.5 text-center truncate leading-tight">
              {{ item.comp.name }}
            </span>
          </button>
        </div>
      </div>

      <!-- 單 tile -->
      <div v-if="currentComposites.length > 0 && currentThumbnails.length > 0" class="text-[10px] text-gray-500 mb-1">
        單一物件
      </div>
      <div class="grid grid-cols-5 gap-1">
        <button
          v-for="item in currentThumbnails"
          :key="item.gid"
          class="relative border border-gray-600 rounded hover:border-blue-400 bg-gray-900 p-0 overflow-hidden"
          :title="`GID ${item.gid}`"
          @click="handleSelect(item.gid)"
        >
          <img
            :src="item.dataUrl"
            class="w-full h-auto"
            style="image-rendering: pixelated"
            :alt="`tile ${item.gid}`"
          />
          <span class="absolute bottom-0 right-0 text-[8px] text-gray-500 bg-gray-900/80 px-0.5 leading-tight">
            {{ item.gid }}
          </span>
        </button>
      </div>
      <p v-if="currentThumbnails.length === 0 && currentComposites.length === 0" class="text-gray-500 text-xs text-center mt-4">
        載入中...
      </p>
    </div>
  </div>
</template>
