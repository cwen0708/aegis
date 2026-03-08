import {
  GroundType, isWall,
  type OfficeLayout, type FurnitureItem, type WorkstationDef,
} from './types'

// ── Compute walkable tiles per room ──────────────────────────
export function computeWalkableByRoom(
  layout: OfficeLayout,
): Array<Array<{ col: number; row: number }>> {
  const { cols, ground, furniture, props, rooms } = layout
  const allItems = [...furniture, ...props]

  return rooms.map(room => {
    const tiles: Array<{ col: number; row: number }> = []
    for (let r = room.rMin; r <= room.rMax; r++) {
      for (let c = room.cMin; c <= room.cMax; c++) {
        const g = ground[r * cols + c]!
        if (isWall(g) || g === GroundType.VOID) continue

        const blocked = allItems.some(f => {
          const fw = 2, fh = 3
          return c >= f.col && c < f.col + fw && r >= f.row && r < f.row + fh
        })
        if (!blocked) tiles.push({ col: c, row: r })
      }
    }
    return tiles
  })
}

// ── Compute all walkable tiles (floor, no furniture, no wall) ──
export function computeAllWalkable(
  layout: OfficeLayout,
): Array<{ col: number; row: number }> {
  const { cols, rows, ground, furniture, props } = layout
  const allItems = [...furniture, ...props]
  const tiles: Array<{ col: number; row: number }> = []

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const g = ground[r * cols + c]!
      // Skip walls and void
      if (isWall(g) || g === GroundType.VOID) continue

      // Check if blocked by furniture/props
      const blocked = allItems.some(f => {
        const fw = 2, fh = 3
        return c >= f.col && c < f.col + fw && r >= f.row && r < f.row + fh
      })
      if (!blocked) tiles.push({ col: c, row: r })
    }
  }
  return tiles
}

// ── Serialization ────────────────────────────────────────────
export function serializeLayout(layout: OfficeLayout): string {
  return JSON.stringify(layout)
}

export function deserializeLayout(json: string): OfficeLayout | null {
  try {
    const obj = JSON.parse(json)
    if (obj.version === 1 && Array.isArray(obj.ground)) return obj as OfficeLayout
  } catch {}
  return null
}

// ── Get ground at (r, c) ────────────────────────────────────
export function getGround(layout: OfficeLayout, r: number, c: number): GroundType {
  return layout.ground[r * layout.cols + c] as GroundType
}

export function setGround(layout: OfficeLayout, r: number, c: number, type: GroundType) {
  layout.ground[r * layout.cols + c] = type
}

// ── Wall bitmask (for rendering) ─────────────────────────────
export function getWallBitmask(layout: OfficeLayout, row: number, col: number): number {
  const { cols, rows, ground } = layout
  let mask = 0
  if (row > 0 && isWall(ground[(row - 1) * cols + col]!)) mask |= 1
  if (col < cols - 1 && isWall(ground[row * cols + col + 1]!)) mask |= 2
  if (row < rows - 1 && isWall(ground[(row + 1) * cols + col]!)) mask |= 4
  if (col > 0 && isWall(ground[row * cols + col - 1]!)) mask |= 8
  return mask
}

// ── ID generation ────────────────────────────────────────────
export function nextFurnitureId(layout: OfficeLayout): string {
  const maxNum = layout.furniture.reduce((max, f) => {
    const n = parseInt(f.id.replace('f_', ''))
    return isNaN(n) ? max : Math.max(max, n)
  }, -1)
  return `f_${String(maxNum + 1).padStart(3, '0')}`
}

export function nextPropsId(layout: OfficeLayout): string {
  const maxNum = layout.props.reduce((max, p) => {
    const n = parseInt(p.id.replace('p_', ''))
    return isNaN(n) ? max : Math.max(max, n)
  }, -1)
  return `p_${String(maxNum + 1).padStart(3, '0')}`
}

// ── Auto-detect workstations ─────────────────────────────────
// Scans chairs, finds nearest desk within range, optionally pairs a monitor/laptop on that desk.
const DESK_TYPES = new Set([
  'desk', 'desk_r', 'desk_gray', 'desk_gray_l', 'desk_gray_single', 'desk_gray_wide',
  'desk_long_l', 'desk_long_m', 'desk_long_r', 'desk_long_l2',
])
const CHAIR_TYPES = new Set([
  'chair', 'chair_back', 'chair_side', 'chair_side_l', 'chair_exec', 'chair_exec_back',
])
const MONITOR_TYPES = new Set(['monitor', 'monitor_on', 'monitor_angled', 'laptop', 'laptop_side'])

function tileDist(a: FurnitureItem, b: FurnitureItem): number {
  return Math.abs(a.col - b.col) + Math.abs(a.row - b.row)
}

export function autoDetectWorkstations(layout: OfficeLayout): WorkstationDef[] {
  const chairs = layout.furniture.filter(f => CHAIR_TYPES.has(f.type))
  const desks = layout.furniture.filter(f => DESK_TYPES.has(f.type))
  const monitors = layout.props.filter(f => MONITOR_TYPES.has(f.type))

  const usedDesks = new Set<string>()
  const usedMonitors = new Set<string>()
  const result: WorkstationDef[] = []

  for (const chair of chairs) {
    // Find closest unused desk within 5 tiles
    let bestDesk: FurnitureItem | null = null
    let bestDist = Infinity
    for (const desk of desks) {
      if (usedDesks.has(desk.id)) continue
      const d = tileDist(chair, desk)
      if (d <= 5 && d < bestDist) {
        bestDist = d
        bestDesk = desk
      }
    }
    if (!bestDesk) continue

    usedDesks.add(bestDesk.id)

    // Find monitor/laptop sitting on the desk (same col/row)
    let monitorId: string | undefined
    for (const mon of monitors) {
      if (usedMonitors.has(mon.id)) continue
      if (mon.col === bestDesk.col && mon.row === bestDesk.row) {
        monitorId = mon.id
        usedMonitors.add(mon.id)
        break
      }
    }

    result.push({ deskId: bestDesk.id, chairId: chair.id, monitorId })
  }

  return result
}
