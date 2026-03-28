/**
 * mapSerializer — Tiled JSON 匯出/匯入
 * Phase 4: 從編輯器狀態匯出完整 Tiled JSON，或從 JSON 匯入
 */
import type { PlacedObject } from './Room2EditorScene'
import { ASSET_BASE } from './tilesetRegistry'

// ── Tiled JSON types ─────────────────────────────────────────────

interface TiledTileLayer {
  id: number
  name: string
  type: 'tilelayer'
  data: number[]
  width: number
  height: number
  x: number
  y: number
  opacity: number
  visible: boolean
}

interface TiledObject {
  id: number
  gid: number
  x: number
  y: number
  width: number
  height: number
  rotation: number
  visible: boolean
}

interface TiledObjectLayer {
  id: number
  name: string
  type: 'objectgroup'
  objects: TiledObject[]
  x: number
  y: number
  opacity: number
  visible: boolean
  draworder: string
}

interface TiledTilesetRef {
  firstgid: number
  source?: string
  // inline fields (if not using external .tsx)
  name?: string
  columns?: number
  image?: string
  imageheight?: number
  imagewidth?: number
  margin?: number
  spacing?: number
  tilecount?: number
  tileheight?: number
  tilewidth?: number
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  tiles?: any[]
}

export interface TiledMapJson {
  compressionlevel: number
  height: number
  width: number
  tileheight: number
  tilewidth: number
  type: string
  version: string
  tiledversion: string
  orientation: string
  renderorder: string
  infinite: boolean
  nextlayerid: number
  nextobjectid: number
  layers: (TiledTileLayer | TiledObjectLayer)[]
  tilesets: TiledTilesetRef[]
}

// ── Layer ordering (must match map.json) ─────────────────────────

const OBJECT_LAYER_ORDER = [
  'Wall', 'Chair', 'Objects', 'ObjectsOnCollide',
  'GenericObjects', 'GenericObjectsOnCollide',
  'Computer', 'Whiteboard', 'Basement', 'VendingMachine',
]

// ── Export ────────────────────────────────────────────────────────

export function exportMapJson(
  map: Phaser.Tilemaps.Tilemap,
  objectLayers: Map<string, PlacedObject[]>,
  originalTilesets: TiledTilesetRef[],
): TiledMapJson {
  // Ground tile layer data (use public API getTileAt for stability)
  const groundData: number[] = []
  for (let row = 0; row < map.height; row++) {
    for (let col = 0; col < map.width; col++) {
      const tile = map.getTileAt(col, row, true, 'Ground')
      groundData.push(tile?.index ?? 0)
    }
  }

  let layerId = 1
  let maxObjId = 0

  const layers: (TiledTileLayer | TiledObjectLayer)[] = []

  // Ground layer
  layers.push({
    id: layerId++,
    name: 'Ground',
    type: 'tilelayer',
    data: groundData,
    width: map.width,
    height: map.height,
    x: 0,
    y: 0,
    opacity: 1,
    visible: true,
  })

  // Object layers — all objects are now in objectLayers (original + placed)
  for (const name of OBJECT_LAYER_ORDER) {
    const objects = objectLayers.get(name) || []

    const tiledObjects: TiledObject[] = objects.map(p => ({
      id: p.id,
      gid: p.gid,
      x: p.x,
      y: p.y,
      width: p.width,
      height: p.height,
      rotation: 0,
      visible: true,
    }))

    for (const obj of tiledObjects) {
      if (obj.id > maxObjId) maxObjId = obj.id
    }

    layers.push({
      id: layerId++,
      name,
      type: 'objectgroup',
      objects: tiledObjects,
      x: 0,
      y: 0,
      opacity: 1,
      visible: true,
      draworder: 'topdown',
    })
  }

  return {
    compressionlevel: -1,
    height: map.height,
    width: map.width,
    tileheight: 32,
    tilewidth: 32,
    type: 'map',
    version: '1.6',
    tiledversion: '1.7.0',
    orientation: 'orthogonal',
    renderorder: 'right-down',
    infinite: false,
    nextlayerid: layerId,
    nextobjectid: maxObjId + 1,
    layers,
    tilesets: originalTilesets,
  }
}

// ── Fetch default tilesets from original map.json ────────────────

let cachedTilesets: TiledTilesetRef[] | null = null

export async function fetchDefaultTilesets(): Promise<TiledTilesetRef[]> {
  if (cachedTilesets) return cachedTilesets
  const res = await fetch(`${ASSET_BASE}/map.json`)
  const json = await res.json() as TiledMapJson
  cachedTilesets = json.tilesets
  return cachedTilesets
}
