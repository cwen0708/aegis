/**
 * compositeObjects — 多 tile 組合物件 + 原生大尺寸物件統一註冊表
 * 每個 tile 可指定不同的 layer（上方裝飾 Objects，底部碰撞 ObjectsOnCollide）
 * 原生物件（椅子/電腦/白板/販賣機）也納入管理，統一碰撞設定
 */

// ── Types ────────────────────────────────────────────────────────

export interface CompositeTile {
  gid: number
  col: number
  row: number
  layer: string
}

export interface CompositeObject {
  name: string
  tiles: CompositeTile[]
  /** 所屬素材分類 key */
  category: string
  /** 寬（格數） */
  cols: number
  /** 高（格數） */
  rows: number
}

/**
 * 原生大尺寸物件定義（tileset 本身 frame 就大於 32x32）
 * 不需要拆 tile，但需要知道碰撞設定
 */
export interface NativeObjectDef {
  gid: number
  name: string
  /** 預設放置的 layer */
  layer: string
  /** 是否為障礙物 */
  collides: boolean
}

// ── Helpers ──────────────────────────────────────────────────────

const OBJ = 'Objects'
const COLLIDE = 'ObjectsOnCollide'

/** 從二維 GID + per-tile layer 映射建立 CompositeObject */
function define(
  name: string,
  category: string,
  gidRows: number[][],
  layerMap: Record<number, string> = {},
  defaultLayer = OBJ,
): CompositeObject {
  const tiles: CompositeTile[] = []
  for (let r = 0; r < gidRows.length; r++) {
    const row = gidRows[r]!
    for (let c = 0; c < row.length; c++) {
      const gid = row[c]!
      tiles.push({
        gid,
        col: c,
        row: r,
        layer: layerMap[gid] ?? defaultLayer,
      })
    }
  }
  return {
    name,
    category,
    tiles,
    cols: Math.max(...gidRows.map(r => r.length)),
    rows: gidRows.length,
  }
}

// ── 組合物件（多 tile 拼接）─────────────────────────────────────
// Modern_Office_Black_Shadow: firstgid=2584, 16 cols
// Generic: firstgid=3432, 16 cols
// Basement: firstgid=4688, 16 cols

export const COMPOSITE_OBJECTS: CompositeObject[] = [
  // ── 桌椅 (tiles_office) ───────────────────────────────────────

  define('小盆栽', 'tiles_office',
    [[2782], [2798], [2814]]),

  define('掛畫A', 'tiles_office',
    [[2751], [2761]]),

  define('掛畫B', 'tiles_office',
    [[2752], [2768]]),

  define('掛畫C', 'tiles_office',
    [[2599], [2615]]),

  define('冷氣機', 'tiles_office',
    [[2771, 2772]]),

  define('大掛畫A', 'tiles_office',
    [[2776, 2777], [2792, 2793]]),

  define('置物架', 'tiles_office',
    [[2783, 2784], [2799, 2800], [2815, 2816]],
    { 2815: COLLIDE, 2816: COLLIDE }),

  define('書架', 'tiles_office',
    [[2831, 2832], [2847, 2848], [2863, 2864]],
    { 2863: COLLIDE, 2864: COLLIDE }),

  define('印表機', 'tiles_office',
    [[2880, 2881], [2896, 2897]],
    { 2896: COLLIDE, 2897: COLLIDE }),

  define('飲水機', 'tiles_office',
    [[2836], [2852], [2868]],
    { 2868: COLLIDE }),

  // ── 裝飾 (tiles_generic) ──────────────────────────────────────

  define('大掛畫B', 'tiles_generic',
    [[3644, 3645], [3660, 3661]]),

  define('窗戶', 'tiles_generic',
    [[4130, 4131], [4146, 4147]]),

  define('一堆錢', 'tiles_generic',
    [[4388], [4404]]),

  // ── 其他 (tiles_basement) ─────────────────────────────────────
  // 撞球桌 4x3，全部碰撞
  define('撞球桌', 'tiles_basement',
    [[5092, 5093, 5094, 5095], [5108, 5109, 5110, 5111], [5124, 5125, 5126, 5127]],
    {}, COLLIDE),

  // 會議桌 2x3，底部碰撞
  define('會議桌A', 'tiles_basement',
    [[5053, 5054], [5061, 5062], [5077, 5078]],
    { 5077: COLLIDE, 5078: COLLIDE }),
]

// ── 原生大尺寸物件 ──────────────────────────────────────────────
// tileset 本身 frame 就大於 32x32，不需要組合

export const NATIVE_OBJECTS: NativeObjectDef[] = [
  // chair: firstgid=2561, 32x64, 23 種
  { gid: 2562, name: '辦公椅(下)', layer: 'Chair', collides: false },
  { gid: 2563, name: '辦公椅(下左)', layer: 'Chair', collides: false },
  { gid: 2564, name: '辦公椅(下右)', layer: 'Chair', collides: false },
  { gid: 2566, name: '辦公椅(上)', layer: 'Chair', collides: false },
  { gid: 2568, name: '高背椅(上)', layer: 'Chair', collides: false },
  { gid: 2569, name: '高背椅(下)', layer: 'Chair', collides: false },
  { gid: 2572, name: '辦公椅B(上)', layer: 'Chair', collides: false },
  { gid: 2573, name: '辦公椅(左)', layer: 'Chair', collides: false },
  { gid: 2574, name: '辦公椅(右)', layer: 'Chair', collides: false },
  { gid: 2580, name: '會議椅A', layer: 'Chair', collides: false },
  { gid: 2581, name: '會議椅B', layer: 'Chair', collides: false },
  { gid: 2582, name: '會議椅C', layer: 'Chair', collides: false },
  { gid: 2583, name: '會議椅D', layer: 'Chair', collides: false },

  // computer: firstgid=4680, 96x64, 5 種
  { gid: 4680, name: '電腦A', layer: 'Computer', collides: false },
  { gid: 4681, name: '電腦B', layer: 'Computer', collides: false },
  { gid: 4682, name: '電腦C', layer: 'Computer', collides: false },
  { gid: 4683, name: '電腦D', layer: 'Computer', collides: false },
  { gid: 4684, name: '電腦E', layer: 'Computer', collides: false },

  // whiteboard: firstgid=4685, 64x64, 3 種
  { gid: 4685, name: '白板A', layer: 'Whiteboard', collides: false },
  { gid: 4686, name: '白板B', layer: 'Whiteboard', collides: false },
  { gid: 4687, name: '白板C', layer: 'Whiteboard', collides: false },

  // vendingmachine: firstgid=5488, 48x72
  { gid: 5488, name: '販賣機', layer: 'VendingMachine', collides: true },
]

// ── Query helpers ───────────────────────────────────────────────

/** 取得所有屬於組合物件的 GID */
export function getCompositeGidSet(): Set<number> {
  const set = new Set<number>()
  for (const comp of COMPOSITE_OBJECTS) {
    for (const tile of comp.tiles) {
      set.add(tile.gid)
    }
  }
  return set
}

/** 取得指定分類的組合物件 */
export function getCompositesByCategory(category: string): CompositeObject[] {
  return COMPOSITE_OBJECTS.filter(c => c.category === category)
}

/** 查詢原生物件定義 */
export function getNativeObjectDef(gid: number): NativeObjectDef | undefined {
  return NATIVE_OBJECTS.find(n => n.gid === gid)
}

/** 原生物件的 GID 集合 */
export function getNativeGidSet(): Set<number> {
  return new Set(NATIVE_OBJECTS.map(n => n.gid))
}
