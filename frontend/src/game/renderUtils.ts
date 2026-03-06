import Phaser from 'phaser'
import {
  GroundType, isWall,
  type OfficeLayout, type FurnitureItem,
} from './types'
import { GROUND_COLORS, GROUND_TILE_FRAMES, getWallAutoTileFrames } from './groundData'
import { FURNITURE_ASSETS } from './furnitureData'

export const TILE = 16
export const ZOOM = 3

/** Preload shared office assets (floor spritesheet + furniture images) */
export function preloadOfficeAssets(scene: Phaser.Scene) {
  if (!scene.textures.exists('floor_tiles')) {
    scene.load.spritesheet('floor_tiles', '/assets/office/tiles/room_builder.png', {
      frameWidth: 16, frameHeight: 16,
    })
  }
  for (const [, filename] of Object.entries(FURNITURE_ASSETS)) {
    if (!scene.textures.exists(`furn_${filename}`)) {
      scene.load.image(`furn_${filename}`, `/assets/office/furniture/${filename}.png`)
    }
  }
}

/** Render floor tiles. Returns created GameObjects for cleanup. */
export function renderFloor(
  scene: Phaser.Scene, layout: OfficeLayout,
): Phaser.GameObjects.GameObject[] {
  const objects: Phaser.GameObjects.GameObject[] = []
  const { cols, rows, ground } = layout
  const ts = TILE * ZOOM

  const voidGfx = scene.add.graphics().setDepth(0)
  objects.push(voidGfx)

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const x = c * ts, y = r * ts
      const gt = ground[r * cols + c] as GroundType
      if (gt === GroundType.VOID) {
        voidGfx.fillStyle(GROUND_COLORS[GroundType.VOID])
        voidGfx.fillRect(x, y, ts, ts)
      } else if (isWall(gt)) {
        // Skip — rendered by renderWalls
      } else {
        const frames = GROUND_TILE_FRAMES[gt]
        if (frames && frames.length > 0) {
          const frameIdx = frames[(r * cols + c) % frames.length]
          const img = scene.add.image(x, y, 'floor_tiles', frameIdx)
            .setOrigin(0, 0).setScale(ZOOM).setDepth(0)
          objects.push(img)
        } else {
          voidGfx.fillStyle(GROUND_COLORS[gt] ?? GROUND_COLORS[GroundType.FLOOR])
          voidGfx.fillRect(x, y, ts, ts)
        }
      }
    }
  }
  return objects
}

/** Render wall tiles with auto-tile frame selection. Returns created GameObjects. */
export function renderWalls(
  scene: Phaser.Scene, layout: OfficeLayout,
): Phaser.GameObjects.GameObject[] {
  const objects: Phaser.GameObjects.GameObject[] = []
  const { cols, rows, ground } = layout
  const ts = TILE * ZOOM

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const gt = ground[r * cols + c] as GroundType
      if (!isWall(gt)) continue
      const x = c * ts, y = r * ts
      const depth = (r + 1) * TILE
      const [primary, secondary] = getWallAutoTileFrames(ground, cols, rows, r, c)
      objects.push(
        scene.add.image(x, y, 'floor_tiles', primary)
          .setOrigin(0, 0).setScale(ZOOM).setDepth(depth),
      )
      if (secondary !== undefined) {
        objects.push(
          scene.add.image(x, y, 'floor_tiles', secondary)
            .setOrigin(0, 0).setScale(ZOOM).setDepth(depth),
        )
      }
    }
  }
  return objects
}

/** Render a single furniture/prop item. Returns the Image or null. */
export function renderItemImage(
  scene: Phaser.Scene, f: FurnitureItem,
): Phaser.GameObjects.Image | null {
  const filename = FURNITURE_ASSETS[f.type]
  if (!filename) return null
  const texKey = `furn_${filename}`
  if (!scene.textures.exists(texKey)) return null

  const x = f.col * TILE * ZOOM
  const y = f.row * TILE * ZOOM
  const img = scene.add.image(x, y, texKey).setOrigin(0, 0).setScale(ZOOM)

  const spriteH = scene.textures.get(texKey).get().height
  const bottomRow = f.row + Math.ceil(spriteH / TILE)
  img.setDepth(bottomRow * TILE)
  return img
}
