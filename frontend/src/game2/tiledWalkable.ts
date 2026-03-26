/**
 * tiledWalkable — 從 Tiled 地圖計算可行走格子
 */
import Phaser from 'phaser'

/**
 * 從 Ground layer 提取可行走的 tile 座標。
 * 排除有 `collides` 屬性的 tile，以及被 collision object layer 覆蓋的格子。
 */
export function computeTiledWalkable(
  map: Phaser.Tilemaps.Tilemap,
): Array<{ col: number; row: number }> {
  const blocked = new Set<string>()

  // 收集 collision object layers 覆蓋的格子
  for (const name of ['ObjectsOnCollide', 'GenericObjectsOnCollide']) {
    const layer = map.getObjectLayer(name)
    if (!layer) continue
    for (const obj of layer.objects) {
      if (!obj.x || !obj.y) continue
      const w = obj.width || 32
      const h = obj.height || 32
      // object 的 y 是底部，往上算
      const startCol = Math.floor(obj.x / 32)
      const startRow = Math.floor((obj.y - h) / 32)
      const endCol = Math.ceil((obj.x + w) / 32)
      const endRow = Math.ceil(obj.y / 32)
      for (let r = startRow; r < endRow; r++) {
        for (let c = startCol; c < endCol; c++) {
          blocked.add(`${c},${r}`)
        }
      }
    }
  }

  // 也排除 Wall object layer
  const wallLayer = map.getObjectLayer('Wall')
  if (wallLayer) {
    for (const obj of wallLayer.objects) {
      if (!obj.x || !obj.y) continue
      const col = Math.floor(obj.x / 32)
      const row = Math.floor((obj.y - (obj.height || 32)) / 32)
      blocked.add(`${col},${row}`)
    }
  }

  const walkable: Array<{ col: number; row: number }> = []
  const groundLayer = map.getLayer('Ground')
  if (!groundLayer) return walkable

  for (let row = 0; row < groundLayer.height; row++) {
    for (let col = 0; col < groundLayer.width; col++) {
      const tile = groundLayer.data[row]?.[col]
      if (!tile || tile.index < 0) continue // 空格
      // 跳過有 collides 屬性的 tile
      if (tile.properties?.collides) continue
      // 跳過被物件擋住的格子
      if (blocked.has(`${col},${row}`)) continue
      walkable.push({ col, row })
    }
  }

  return walkable
}
