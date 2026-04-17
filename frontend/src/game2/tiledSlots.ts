/**
 * tiledSlots — 從 Tiled 地圖的 Chair object layer 推導工位位置
 */
import Phaser from 'phaser'

export type Dir = 'down' | 'left' | 'right' | 'up'

export interface TiledWorkSlot {
  col: number
  row: number
  dir: Dir
  pixelX: number
  pixelY: number
}

// Chair tileset firstgid = 2561, tilecount = 23
// 根據 SkyOffice chair spritesheet 佈局推導方向：
// local 1 (gid 2562): 面朝下
// local 2 (gid 2563): 面朝下（左側扶手）
// local 3 (gid 2564): 面朝下（右側扶手）
// local 5 (gid 2566): 面朝上
// local 7 (gid 2568): 面朝上（高背椅）
// local 8 (gid 2569): 面朝下（高背椅）
// local 11 (gid 2572): 面朝上
// local 12 (gid 2573): 面朝左
// local 13 (gid 2574): 面朝右
// local 19-22 (gid 2580-2583): 會議椅（各方向混合，預設朝下）
const CHAIR_GID_DIR: Record<number, Dir> = {
  2562: 'down',
  2563: 'down',
  2564: 'down',
  2566: 'up',
  2568: 'up',
  2569: 'down',
  2572: 'up',
  2573: 'left',
  2574: 'right',
  // 會議椅
  2580: 'down',
  2581: 'down',
  2582: 'down',
  2583: 'down',
}

/**
 * 從 Chair object layer 提取工位資訊
 */
export function extractWorkSlots(map: Phaser.Tilemaps.Tilemap): TiledWorkSlot[] {
  const layer = map.getObjectLayer('Chair')
  if (!layer) return []

  const slots: TiledWorkSlot[] = []

  for (const obj of layer.objects) {
    if (!obj.gid || obj.x == null || obj.y == null) continue

    const w = obj.width || 32
    const h = obj.height || 64
    // 椅子 y 是底邊（Tiled 慣例），座位在下半格（第二格）
    // pixelY = 底邊往上 1/4 高度（座位中心，不是椅子正中間）
    const pixelX = obj.x + w / 2
    const pixelY = obj.y - h * 0.25
    const col = Math.floor(obj.x / 32)
    const row = Math.floor((obj.y - h) / 32)
    const dir = CHAIR_GID_DIR[obj.gid] || 'down'

    slots.push({ col, row, dir, pixelX, pixelY })
  }

  return slots
}
