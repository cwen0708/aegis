/**
 * compositeObjects — 多 tile 組合物件註冊表
 * 定義哪些 GID 組合成一個完整物件，用於素材庫顯示合併縮圖 + 一次放置
 */

export interface CompositeObject {
  name: string
  /** 二維 GID 陣列，[row][col]，左上角開始 */
  gids: number[][]
  /** 放置到哪個 layer */
  targetLayer: string
  /** 所屬素材分類 key */
  category: string
}

// Modern_Office_Black_Shadow: firstgid=2584, 16 cols
// Generic: firstgid=3432, 16 cols
// Basement: firstgid=4688, 16 cols

export const COMPOSITE_OBJECTS: CompositeObject[] = [
  // ── 桌椅 (tiles_office → Objects) ─────────────────────────────
  {
    name: '小盆栽',
    gids: [[2782], [2798], [2814]],
    targetLayer: 'Objects',
    category: 'tiles_office',
  },
  {
    name: '掛畫A',
    gids: [[2751], [2761]],
    targetLayer: 'Objects',
    category: 'tiles_office',
  },
  {
    name: '掛畫B',
    gids: [[2752], [2768]],
    targetLayer: 'Objects',
    category: 'tiles_office',
  },
  {
    name: '掛畫C',
    gids: [[2599], [2615]],
    targetLayer: 'Objects',
    category: 'tiles_office',
  },
  {
    name: '冷氣機',
    gids: [[2771, 2772]],
    targetLayer: 'Objects',
    category: 'tiles_office',
  },
  {
    name: '大掛畫A',
    gids: [[2776, 2777], [2792, 2793]],
    targetLayer: 'Objects',
    category: 'tiles_office',
  },
  {
    name: '置物架',
    gids: [[2783, 2784], [2799, 2800], [2815, 2816]],
    targetLayer: 'Objects',
    category: 'tiles_office',
  },
  {
    name: '書架',
    gids: [[2831, 2832], [2847, 2848], [2863, 2864]],
    targetLayer: 'Objects',
    category: 'tiles_office',
  },
  {
    name: '印表機',
    gids: [[2880, 2881], [2896, 2897]],
    targetLayer: 'Objects',
    category: 'tiles_office',
  },

  // ── 障礙物 (tiles_office → ObjectsOnCollide) ─────────────────
  {
    name: '飲水機',
    gids: [[2836], [2852], [2868]],
    targetLayer: 'ObjectsOnCollide',
    category: 'tiles_office',
  },

  // ── 裝飾 (tiles_generic → GenericObjects) ─────────────────────
  {
    name: '大掛畫B',
    gids: [[3644, 3645], [3660, 3661]],
    targetLayer: 'GenericObjects',
    category: 'tiles_generic',
  },
  {
    name: '窗戶',
    gids: [[4130, 4131], [4146, 4147]],
    targetLayer: 'GenericObjects',
    category: 'tiles_generic',
  },
  {
    name: '一堆錢',
    gids: [[4388], [4404]],
    targetLayer: 'GenericObjects',
    category: 'tiles_generic',
  },

  // ── 其他 (tiles_basement → Basement) ──────────────────────────
  {
    name: '撞球桌',
    gids: [[5092, 5093, 5094, 5095], [5108, 5109, 5110, 5111], [5124, 5125, 5126, 5127]],
    targetLayer: 'ObjectsOnCollide',
    category: 'tiles_basement',
  },
  {
    name: '會議桌A',
    gids: [[5053, 5054], [5061, 5062], [5077, 5078]],
    targetLayer: 'ObjectsOnCollide',
    category: 'tiles_basement',
  },
]

/** 取得所有屬於組合物件的 GID（用來從單 tile 列表中過濾掉） */
export function getCompositeGidSet(): Set<number> {
  const set = new Set<number>()
  for (const comp of COMPOSITE_OBJECTS) {
    for (const row of comp.gids) {
      for (const gid of row) {
        set.add(gid)
      }
    }
  }
  return set
}

/** 取得指定分類的組合物件 */
export function getCompositesByCategory(category: string): CompositeObject[] {
  return COMPOSITE_OBJECTS.filter(c => c.category === category)
}
