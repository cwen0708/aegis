/**
 * compositeObjects — 從 composites.json 統一載入所有物件配置
 * 包含：分類定義、組合物件、原生大尺寸物件
 * JSON 定義在 public/assets/office2/composites.json
 */
import { ASSET_BASE } from './tilesetRegistry'

// ── Types ────────────────────────────────────────────────────────

export interface PaletteCategory {
  label: string
  key: string
  targetLayer: string
  maxCount?: number
}

export interface CompositeTile {
  gid: number
  col: number
  row: number
  layer: string
}

export interface CompositeObject {
  name: string
  tiles: CompositeTile[]
  category: string
  cols: number
  rows: number
}

export interface NativeObjectDef {
  gid: number
  name: string
  layer: string
  collides: boolean
  category: string
}

// ── JSON schema ─────────────────────────────────────────────────

interface CompositeJsonEntry {
  name: string
  category: string
  gids: number[][]
  collides?: number[]
}

interface NativeJsonEntry {
  gid: number
  name: string
  layer: string
  category: string
  collides?: boolean
}

interface CompositeJsonFile {
  version: number
  collideLayer: string
  defaultLayer: string
  categories: PaletteCategory[]
  composites: CompositeJsonEntry[]
  nativeObjects: NativeJsonEntry[]
}

// ── Parsed cache ────────────────────────────────────────────────

let cachedCategories: PaletteCategory[] | null = null
let cachedComposites: CompositeObject[] | null = null
let cachedNatives: NativeObjectDef[] | null = null
let cachedCompositeGids: Set<number> | null = null

function parseCompositeEntry(
  entry: CompositeJsonEntry,
  collideLayer: string,
  defaultLayer: string,
): CompositeObject {
  const collideSet = new Set(entry.collides ?? [])
  const tiles: CompositeTile[] = []

  for (let r = 0; r < entry.gids.length; r++) {
    const row = entry.gids[r]!
    for (let c = 0; c < row.length; c++) {
      const gid = row[c]!
      tiles.push({
        gid,
        col: c,
        row: r,
        layer: collideSet.has(gid) ? collideLayer : defaultLayer,
      })
    }
  }

  return {
    name: entry.name,
    category: entry.category,
    tiles,
    cols: Math.max(...entry.gids.map(r => r.length)),
    rows: entry.gids.length,
  }
}

// ── Public API ───────────────────────────────────────────────────

export async function loadCompositeConfig(): Promise<{
  categories: PaletteCategory[]
  composites: CompositeObject[]
  natives: NativeObjectDef[]
}> {
  if (cachedCategories && cachedComposites && cachedNatives) {
    return { categories: cachedCategories, composites: cachedComposites, natives: cachedNatives }
  }

  const res = await fetch(`${ASSET_BASE}/composites.json`)
  const json = await res.json() as CompositeJsonFile

  cachedCategories = json.categories

  cachedComposites = json.composites.map(entry =>
    parseCompositeEntry(entry, json.collideLayer, json.defaultLayer),
  )

  cachedNatives = json.nativeObjects.map(n => ({
    gid: n.gid,
    name: n.name,
    layer: n.layer,
    collides: n.collides ?? false,
    category: n.category,
  }))

  cachedCompositeGids = new Set<number>()
  for (const comp of cachedComposites) {
    for (const tile of comp.tiles) {
      cachedCompositeGids.add(tile.gid)
    }
  }

  return { categories: cachedCategories, composites: cachedComposites, natives: cachedNatives }
}

export function getCategories(): PaletteCategory[] {
  return cachedCategories ?? []
}

export function getCompositeGidSet(): Set<number> {
  return cachedCompositeGids ?? new Set()
}

export function getCompositesByCategory(category: string): CompositeObject[] {
  return (cachedComposites ?? []).filter(c => c.category === category)
}

export function getNativeObjectDef(gid: number): NativeObjectDef | undefined {
  return cachedNatives?.find(n => n.gid === gid)
}

export function getNativeGidSet(): Set<number> {
  return new Set((cachedNatives ?? []).map(n => n.gid))
}
