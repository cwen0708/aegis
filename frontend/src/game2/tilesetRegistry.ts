/**
 * tilesetRegistry — Room2 tileset 共用載入/GID 解析
 * Room2Scene 和 Room2EditorScene 共用
 */
import Phaser from 'phaser'

export const ASSET_BASE = '/assets/office2'
export const TILE_SIZE = 32

// tileset name → spritesheet key 映射
export const TILESET_KEY_MAP: Record<string, string> = {
  'FloorAndGround': 'tiles_floor',
  'Modern_Office_Black_Shadow': 'tiles_office',
  'Generic': 'tiles_generic',
  'Basement': 'tiles_basement',
  'chair': 'chairs',
  'computer': 'computers',
  'whiteboard': 'whiteboards',
  'vendingmachine': 'vendingmachines',
}

// 每個 tileset 的 preload 設定
export const TILESET_PRELOAD_CONFIG = [
  { key: 'tiles_floor', path: 'FloorAndGround.png', frameWidth: 32, frameHeight: 32 },
  { key: 'tiles_office', path: 'tileset/Modern_Office_Black_Shadow.png', frameWidth: 32, frameHeight: 32 },
  { key: 'tiles_generic', path: 'tileset/Generic.png', frameWidth: 32, frameHeight: 32 },
  { key: 'tiles_basement', path: 'tileset/Basement.png', frameWidth: 32, frameHeight: 32 },
  { key: 'chairs', path: 'items/chair.png', frameWidth: 32, frameHeight: 64 },
  { key: 'computers', path: 'items/computer.png', frameWidth: 96, frameHeight: 64 },
  { key: 'whiteboards', path: 'items/whiteboard.png', frameWidth: 64, frameHeight: 64 },
  { key: 'vendingmachines', path: 'items/vendingmachine.png', frameWidth: 48, frameHeight: 72 },
] as const

export interface TilesetInfo {
  name: string
  firstgid: number
  lastgid: number
  spriteKey: string
}

/** Preload 所有 tileset spritesheet */
export function preloadTilesets(scene: Phaser.Scene) {
  for (const cfg of TILESET_PRELOAD_CONFIG) {
    scene.load.spritesheet(cfg.key, `${ASSET_BASE}/${cfg.path}`, {
      frameWidth: cfg.frameWidth, frameHeight: cfg.frameHeight,
    })
  }
}

/** 從 Phaser tilemap 建立 gid 查找表（按 firstgid 降序） */
export function buildTilesetInfos(map: Phaser.Tilemaps.Tilemap): TilesetInfo[] {
  const infos = map.tilesets.map((ts) => ({
    name: ts.name,
    firstgid: ts.firstgid,
    lastgid: ts.firstgid + ts.total - 1,
    spriteKey: TILESET_KEY_MAP[ts.name] || ts.name,
  }))
  infos.sort((a, b) => b.firstgid - a.firstgid)
  return infos
}

/** 根據 gid 找到對應的 spritesheet key + frame index */
export function resolveGid(gid: number, infos: TilesetInfo[]): { key: string; frame: number } | null {
  for (const info of infos) {
    if (gid >= info.firstgid && gid <= info.lastgid) {
      return { key: info.spriteKey, frame: gid - info.firstgid }
    }
  }
  return null
}

/** 渲染一個 object layer 裡的所有物件 */
export function renderObjectLayer(
  scene: Phaser.Scene,
  map: Phaser.Tilemaps.Tilemap,
  infos: TilesetInfo[],
  layerName: string,
  useDepthSort: boolean,
): Phaser.GameObjects.Sprite[] {
  const layer = map.getObjectLayer(layerName)
  if (!layer) return []

  const sprites: Phaser.GameObjects.Sprite[] = []
  layer.objects.forEach((obj) => {
    if (!obj.gid) return
    const resolved = resolveGid(obj.gid, infos)
    if (!resolved) return

    const sprite = scene.add.sprite(
      obj.x! + (obj.width || 0) / 2,
      obj.y! - (obj.height || 0) / 2,
      resolved.key,
      resolved.frame,
    )

    if (useDepthSort) {
      sprite.setDepth(obj.y! + (obj.height || 0) * 0.27)
    } else {
      sprite.setDepth(0)
    }
    sprites.push(sprite)
  })
  return sprites
}
