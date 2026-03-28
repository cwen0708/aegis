/**
 * thumbnailExtractor — 從 Phaser spritesheet 擷取 tile 縮圖
 * 共用於 ObjectPalette 和 Room2Editor 的地板選擇面板
 */
import { TILESET_PRELOAD_CONFIG } from './tilesetRegistry'
import type { TilesetInfo } from './tilesetRegistry'

export interface ThumbnailItem {
  gid: number
  dataUrl: string
}

/**
 * 從已載入的 spritesheet 擷取非空 frame 的縮圖
 * @param textures Phaser TextureManager
 * @param spriteKey spritesheet key (e.g. 'tiles_floor')
 * @param firstgid tileset 的 firstgid
 * @param maxCount 最多擷取幾個（預設 80）
 */
export function extractThumbnails(
  textures: Phaser.Textures.TextureManager,
  spriteKey: string,
  firstgid: number,
  maxCount = 80,
): ThumbnailItem[] {
  const cfg = TILESET_PRELOAD_CONFIG.find(c => c.key === spriteKey)
  if (!cfg) return []

  const tex = textures.get(cfg.key)
  if (!tex) return []

  const source = tex.source[0]?.image as HTMLImageElement | undefined
  if (!source) return []

  const cols = Math.floor(source.width / cfg.frameWidth)
  const rows = Math.floor(source.height / cfg.frameHeight)
  const totalFrames = cols * rows
  // Scan entire tileset to find non-blank frames (large tilesets have sparse content)
  const scanLimit = totalFrames

  const items: ThumbnailItem[] = []

  for (let frame = 0; frame < scanLimit && items.length < maxCount; frame++) {
    const sx = (frame % cols) * cfg.frameWidth
    const sy = Math.floor(frame / cols) * cfg.frameHeight

    const canvas = document.createElement('canvas')
    canvas.width = cfg.frameWidth
    canvas.height = cfg.frameHeight
    const ctx = canvas.getContext('2d')!
    ctx.drawImage(source, sx, sy, cfg.frameWidth, cfg.frameHeight, 0, 0, cfg.frameWidth, cfg.frameHeight)

    // 跳過全透明 frame
    const imageData = ctx.getImageData(0, 0, cfg.frameWidth, cfg.frameHeight)
    let hasContent = false
    for (let i = 3; i < imageData.data.length; i += 4) {
      if ((imageData.data[i] ?? 0) > 10) { hasContent = true; break }
    }
    if (!hasContent) continue

    items.push({ gid: firstgid + frame, dataUrl: canvas.toDataURL() })
  }

  return items
}

/**
 * 便利函式：從 tilesetInfos 查 firstgid 後擷取縮圖
 */
export function extractThumbnailsForKey(
  textures: Phaser.Textures.TextureManager,
  tilesetInfos: TilesetInfo[],
  spriteKey: string,
  maxCount = 80,
): ThumbnailItem[] {
  const info = tilesetInfos.find(i => i.spriteKey === spriteKey)
  const firstgid = info?.firstgid ?? 1
  return extractThumbnails(textures, spriteKey, firstgid, maxCount)
}

/**
 * 分批擷取多個 tileset 的縮圖（每個 tileset 間讓出主線程一幀避免卡頓）
 */
export async function extractThumbnailsBatched(
  textures: Phaser.Textures.TextureManager,
  tilesetInfos: TilesetInfo[],
  keys: string[],
  maxCountPerKey = 80,
): Promise<Map<string, ThumbnailItem[]>> {
  const result = new Map<string, ThumbnailItem[]>()
  for (const key of keys) {
    const items = extractThumbnailsForKey(textures, tilesetInfos, key, maxCountPerKey)
    result.set(key, items)
    await new Promise<void>(r => requestAnimationFrame(() => r()))
  }
  return result
}
