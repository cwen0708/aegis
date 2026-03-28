/**
 * editorConstants — Room2 Editor 共用常數
 */

// ── Depth layers ─────────────────────────────────────────────────
export const DEPTH_BASE_LAYER = 0
export const DEPTH_GRID = 900
export const DEPTH_HOVER = 901
export const DEPTH_COLLISION = 905
export const DEPTH_SELECTION = 910
export const DEPTH_HOVER_SPRITE = 950

// ── Depth sort ──────────────────────────────────────────────────
/** Object layer Y-sort 係數：sprite.depth = obj.y + height * DEPTH_SORT_FACTOR */
export const DEPTH_SORT_FACTOR = 0.27

// ── Camera ──────────────────────────────────────────────────────
export const ZOOM_MIN = 0.5
export const ZOOM_MAX = 4
export const ZOOM_INITIAL = 1.5

// ── Object ID ───────────────────────────────────────────────────
export const INITIAL_OBJECT_ID = 10000

// ── Layers without depth sort ───────────────────────────────────
export const FLAT_LAYERS = new Set(['Chair', 'Basement'])

export function isDepthSorted(layerName: string): boolean {
  return !FLAT_LAYERS.has(layerName)
}
