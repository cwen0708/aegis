import { GroundType, isWall } from './types'

// ── Ground Labels & Colors ──────────────────────────────────
export const GROUND_LABELS: Record<GroundType, string> = {
  [GroundType.VOID]: '空白',
  [GroundType.WALL]: '牆壁',
  [GroundType.FLOOR]: '地板',
  [GroundType.WOOD]: '木地板',
  [GroundType.DARK]: '深色地板',
  [GroundType.MARBLE]: '大理石',
  [GroundType.STONE]: '石磚',
  [GroundType.BEIGE]: '米磚',
  [GroundType.BAMBOO]: '竹地板',
  [GroundType.CHECKER]: '格子磚',
  [GroundType.CARPET]: '地毯',
  [GroundType.RED]: '紅磚',
  [GroundType.LAVENDER]: '薰衣草',
  [GroundType.WALL_MARBLE]: '大理石牆',
  [GroundType.WALL_GRAY]: '灰牆',
  [GroundType.WALL_BRICK]: '磚牆',
  [GroundType.WALL_PINK]: '粉牆',
}

export const GROUND_COLORS: Record<GroundType, number> = {
  [GroundType.VOID]: 0x1a1510,
  [GroundType.WALL]: 0x6B5B4F,
  [GroundType.FLOOR]: 0xC8C4D0,
  [GroundType.WOOD]: 0xC4A86A,
  [GroundType.DARK]: 0x3A3540,
  [GroundType.MARBLE]: 0xB8B0C8,
  [GroundType.STONE]: 0x9A9A9A,
  [GroundType.BEIGE]: 0xC8B89A,
  [GroundType.BAMBOO]: 0xA09060,
  [GroundType.CHECKER]: 0x8A8A7A,
  [GroundType.CARPET]: 0x7A6A5A,
  [GroundType.RED]: 0x8A4A4A,
  [GroundType.LAVENDER]: 0xC0B0D0,
  [GroundType.WALL_MARBLE]: 0xB8B0C8,
  [GroundType.WALL_GRAY]: 0x9A9A9A,
  [GroundType.WALL_BRICK]: 0xC8A080,
  [GroundType.WALL_PINK]: 0xD0B8C8,
}

// ── Ground Tile Frames (room_builder.png spritesheet, 16x16 per frame, 16 cols) ──
// Only "floor" tagged frames (cols 10-15 of rows 5-12)
export const GROUND_TILE_FRAMES: Partial<Record<GroundType, number[]>> = {
  [GroundType.FLOOR]:    [157, 158, 159],                          // tile_gray
  [GroundType.WOOD]:     [125, 126, 127],                          // wood
  [GroundType.DARK]:     [90, 91, 92],                             // dark_gray
  [GroundType.MARBLE]:   [170, 171, 172, 173, 174, 175],          // row 10
  [GroundType.STONE]:    [138, 139, 140, 141, 142, 143],          // row 8
  [GroundType.BEIGE]:    [154, 155, 156],                          // tan
  [GroundType.BAMBOO]:   [93, 94, 95],                             // bamboo
  [GroundType.CHECKER]:  [122, 123, 124],                          // checker
  [GroundType.CARPET]:   [186, 187, 188, 189, 190, 191],          // carpet
  [GroundType.RED]:      [106, 107, 108, 109, 110, 111],          // brick
  [GroundType.LAVENDER]: [202, 203, 204, 205, 206, 207],          // row 12
}

// ── Wall Auto-Tile (structural frame selection based on 8 neighbors) ──
const SS_COLS = 16 // spritesheet columns

/**
 * Wall groups: each colored wall uses a PAIR of spritesheet rows.
 *   Row A (primary, 10-frame): decorative front face — north-facing
 *     cols 0-2: outer L/M/R (with top bar, no wall above)
 *     col 3:    enclosed
 *     cols 4-6: south-facing decorative L/M/R
 *     cols 7-9: inner L/M/R (no top bar, wall continues above)
 *   Row B (secondary, 7-frame): exterior back face — south-facing
 *     cols 0-2: south-facing L/M/R (face top + base bottom + bar)
 *     col 3:    enclosed
 *     cols 7-9: north-facing L/M/R (back view)
 */
const WALL_GROUP: Partial<Record<number, [number, number]>> = {
  [GroundType.WALL_MARBLE]: [6, 5],   // 大理石: [north-facing row, south-facing row]
  [GroundType.WALL_GRAY]:   [8, 7],   // 灰
  [GroundType.WALL_BRICK]:  [10, 9],  // 磚
  [GroundType.WALL_PINK]:   [12, 11], // 粉
}

/**
 * Get the auto-tile frame(s) for a wall cell based on its 8 neighbors.
 * Returns [primary, secondary?] — secondary is set for double-sided walls.
 */
export function getWallAutoTileFrames(
  ground: number[], cols: number, rows: number,
  r: number, c: number,
): [number, number | undefined] {
  const gt = ground[r * cols + c]
  const group = WALL_GROUP[gt]

  const wallAt = (row: number, col: number): boolean => {
    if (row < 0 || row >= rows || col < 0 || col >= cols) return false
    return isWall(ground[row * cols + col])
  }
  const floorAt = (row: number, col: number): boolean => {
    if (row < 0 || row >= rows || col < 0 || col >= cols) return false
    const g = ground[row * cols + col]
    return g !== GroundType.VOID && !isWall(g)
  }

  const n = wallAt(r - 1, c)
  const e = wallAt(r, c + 1)
  const s = wallAt(r + 1, c)
  const w = wallAt(r, c - 1)
  const sFloor = floorAt(r + 1, c)
  const nFloor = floorAt(r - 1, c)

  // ── Crossroads (all 4 cardinals are wall) — check FIRST ──
  if (n && e && s && w) {
    const neFloor = floorAt(r - 1, c + 1)
    const nwFloor = floorAt(r - 1, c - 1)
    const seFloor = floorAt(r + 1, c + 1)
    const swFloor = floorAt(r + 1, c - 1)
    const floorCount = [neFloor, nwFloor, seFloor, swFloor].filter(Boolean).length
    // Single diagonal floor → outer corner, not crossroads
    if (floorCount === 1) {
      const nwVoid = !nwFloor && !wallAt(r - 1, c - 1)
      const neVoid = !neFloor && !wallAt(r - 1, c + 1)
      const swVoid = !swFloor && !wallAt(r + 1, c - 1)
      const seVoid = !seFloor && !wallAt(r + 1, c + 1)
      // Void opposite to floor → interior fill
      if (seFloor && nwVoid) return [27, undefined]
      if (swFloor && neVoid) return [27, undefined]
      if (neFloor && swVoid) return [27, undefined]
      if (nwFloor && seVoid) return [27, undefined]
      if (swFloor) return [34, undefined]  // outer corner SW
      if (seFloor) return [33, undefined]  // outer corner SE
      if (neFloor) return [17, undefined]  // outer corner NE
      if (nwFloor) return [18, undefined]  // outer corner NW
    }
    // Multiple diagonal floors → true crossroads intersection
    if (floorCount >= 2) return [20, undefined]
    // Fully enclosed by walls on all sides → interior fill
    return [27, undefined]
  }

  // ── Interior horizontal wall (floor both N and S) → thin structural divider ──
  if (sFloor && !s && nFloor && !n) {
    if (e && w) {
      const nwWall = wallAt(r - 1, c - 1)
      const neWall = wallAt(r - 1, c + 1)
      if (nwWall && neWall) return [28, undefined]  // both upper diags → top-capped
      if (nwWall) return [42, undefined]             // upper-left junction
      if (neWall) return [44, undefined]             // upper-right junction
      return [27, undefined]                          // plain thin wall fill
    }
    if (e && !w) return [42, undefined]  // left end
    if (!e && w) return [44, undefined]  // right end
    return [28, undefined]               // isolated
  }

  // ── North-facing wall (south = floor) ──
  if (sFloor && !s) {
    if (group) {
      // ── Colored north-facing: use primary row (Row A) ──
      const row = group[0]
      if (e && w) {
        const swFloor = floorAt(r + 1, c - 1)
        const seFloor = floorAt(r + 1, c + 1)
        if (n) {
          // Wall above → inner face (cols 7,8,9) — no top bar
          const seWall = wallAt(r + 1, c + 1)
          const swWall = wallAt(r + 1, c - 1)
          // Only use end pieces if diagonal is void/floor, not wall
          if (!swFloor && seFloor && !swWall) return [row * SS_COLS + 7, undefined]
          if (swFloor && !seFloor && !seWall) return [row * SS_COLS + 9, undefined]
          return [row * SS_COLS + 8, undefined]
        }
        // No wall above → outer face (cols 0,1,2) — has top bar
        if (!swFloor && seFloor) return [row * SS_COLS + 0, undefined]
        if (swFloor && !seFloor) return [row * SS_COLS + 2, undefined]
        return [row * SS_COLS + 1, undefined]
      }
      // End caps
      if (e && !w) return [row * SS_COLS + (n ? 7 : 0), undefined]
      if (!e && w) return [row * SS_COLS + (n ? 9 : 2), undefined]
      // Isolated
      return [row * SS_COLS + 3, undefined]
    }

    // ── Structural north-facing ──
    if (e && w) {
      const swFloor = floorAt(r + 1, c - 1)
      const seFloor = floorAt(r + 1, c + 1)
      if (!swFloor && seFloor) return [23, undefined]
      if (swFloor && !seFloor) return [25, undefined]
      return [24, undefined]
    }
    if (e && !w) return [50, undefined]
    if (!e && w) return [49, undefined]
    return [24, undefined]
  }

  // ── South-facing wall (north = floor) ──
  if (floorAt(r - 1, c) && !n) {
    // ── Top cap: floor north, wall south → structural cap frame 28 ──
    if (s && !e && !w) return [28, undefined]

    // ── Outer corner with void diagonal → structural corner ──
    const seVoid = !floorAt(r + 1, c + 1) && !wallAt(r + 1, c + 1)
    const swVoid = !floorAt(r + 1, c - 1) && !wallAt(r + 1, c - 1)
    const sVoid = !sFloor && !s
    if (e && s && !w && seVoid) return [22, undefined]
    if (s && w && !e && swVoid) return [21, undefined]
    // South is void → structural south-facing
    if (e && w && sVoid) return [24, undefined]

    if (group) {
      // ── Colored south-facing: use secondary row (Row B) cols 0-2 ──
      const row = group[1]
      if (e && w) {
        const nwFloor = floorAt(r - 1, c - 1)
        const neFloor = floorAt(r - 1, c + 1)
        const nwWall = wallAt(r - 1, c - 1)
        const neWall = wallAt(r - 1, c + 1)
        // Only use end pieces if diagonal is void/floor, not wall
        if (!nwFloor && neFloor && !nwWall) return [row * SS_COLS + 0, undefined]
        if (nwFloor && !neFloor && !neWall) return [row * SS_COLS + 2, undefined]
        return [row * SS_COLS + 1, undefined]
      }
      if (e && !w) return [row * SS_COLS + 0, undefined]
      if (!e && w) return [row * SS_COLS + 2, undefined]
      return [row * SS_COLS + 1, undefined]
    }

    // ── Structural south-facing ──
    if (e && w) {
      const nwFloor = floorAt(r - 1, c - 1)
      const neFloor = floorAt(r - 1, c + 1)
      if (!nwFloor && neFloor) return [55, undefined]
      if (nwFloor && !neFloor) return [57, undefined]
      return [56, undefined]
    }
    if (e && !w) return [55, undefined]
    if (!e && w) return [57, undefined]
    return [56, undefined]
  }

  // ── Vertical walls (N and S both wall) ──
  if (n && s) {
    const eFloor = floorAt(r, c + 1)
    const wFloor = floorAt(r, c - 1)
    // Floor on both sides
    if (eFloor && wFloor) {
      const neWall = wallAt(r - 1, c + 1)
      const nwWall = wallAt(r - 1, c - 1)
      const seWall = wallAt(r + 1, c + 1)
      const swWall = wallAt(r + 1, c - 1)
      // Diagonal wall → interior junction
      if (neWall || nwWall || seWall || swWall) return [27, undefined]
      // Pure thin vertical wall → frame 83
      return [83, undefined]
    }
    // 3-wall interior: wall on 3 cardinals → interior fill
    if (eFloor && w) return [27, undefined]
    if (wFloor && e) return [27, undefined]
    if (eFloor) return [39, undefined]
    if (wFloor) return [41, undefined]
    if (e && w) {
      // Thick wall interior — check diagonals for inner corners
      if (!wallAt(r + 1, c + 1) && floorAt(r + 1, c + 1)) return [23, undefined]
      if (!wallAt(r + 1, c - 1) && floorAt(r + 1, c - 1)) return [25, undefined]
      if (!wallAt(r - 1, c + 1) && floorAt(r - 1, c + 1)) return [55, undefined]
      if (!wallAt(r - 1, c - 1) && floorAt(r - 1, c - 1)) return [57, undefined]
      return [27, undefined]
    }
    // West is void with floor diagonal → structural corner
    // Structural corners only when opposite side is void AND diagonal neighbor is floor (not wall)
    const wVoid = !wFloor && !w
    const eVoid = !eFloor && !e
    // Only apply when there are exactly 2 wall cardinals (not 3)
    if (!e && wVoid && floorAt(r - 1, c + 1)) return [23, undefined]
    if (!e && wVoid && floorAt(r + 1, c + 1)) return [55, undefined]
    if (!w && eVoid && floorAt(r - 1, c - 1)) return [25, undefined]
    if (!w && eVoid && floorAt(r + 1, c - 1)) return [57, undefined]
    if (e) return [39, undefined]
    if (w) return [41, undefined]
    return [3, undefined]
  }

  // ── Outer corners (2 adjacent cardinals) ──
  // Top edge of map (row=0) → special frames
  if (r === 0 && e && s && !w) return [12, undefined]
  if (r === 0 && s && w && !e) return [25, undefined]
  // Void on both missing sides → structural corner
  if (e && s && !n && !w && !nFloor && !floorAt(r, c - 1)) return [23, undefined]
  if (s && w && !n && !e && !nFloor && !floorAt(r, c + 1)) return [25, undefined]
  if (e && s && !n && !w) return [34, undefined]
  if (s && w && !n && !e) return [33, undefined]
  // Void on both missing sides → structural corner (unless floor diagonal with wall opposite)
  if (n && e && !s && !w && !sFloor && !floorAt(r, c - 1) && !floorAt(r - 1, c + 1)) return [55, undefined]
  if (n && e && !s && !w && floorAt(r - 1, c + 1) && wallAt(r - 1, c - 1)) return [20, undefined]
  if (n && e && !s && !w && floorAt(r - 1, c + 1)) return [55, undefined]
  if (n && w && !s && !e && !sFloor && !floorAt(r, c + 1) && !floorAt(r - 1, c - 1)) return [57, undefined]
  if (n && w && !s && !e && floorAt(r - 1, c - 1) && wallAt(r - 1, c + 1)) return [20, undefined]
  if (n && w && !s && !e && floorAt(r - 1, c - 1)) return [57, undefined]
  if (n && e && !s && !w) return [18, undefined]
  if (n && w && !s && !e) return [57, undefined]

  // ── T-junctions (3 cardinals) ──
  if (n && e && s && !w) return [21, undefined]
  if (n && s && w && !e) return [22, undefined]
  // Top edge of map or void north → frame 81
  if (r === 0 && e && s && w) return [81, undefined]
  if (e && s && w && !n && !nFloor) return [81, undefined]
  if (e && s && w && !n) return [19, undefined]
  if (n && e && w && !s) return [56, undefined]

  // ── End caps (1 cardinal) ──
  // Bottom edge with floor to side → structural corner
  if (n && !s && !e && !w && floorAt(r, c - 1)) return [57, undefined]
  if (n && !s && !e && !w && floorAt(r, c + 1)) return [55, undefined]
  if (s && !n && !e && !w) return [43, undefined]
  if (n && !s && !e && !w) return [43, undefined]
  if (e && !n && !s && !w) return [60, undefined]
  if (w && !n && !s && !e) return [58, undefined]

  // ── Isolated / fallback ──
  return [8, undefined]
}

// ── Wall Tile Frames (room_builder.png) ──
// Each colored wall group uses Row A (front) + Row B (back)
export const WALL_TILE_FRAMES: Partial<Record<GroundType, number[]>> = {
  [GroundType.WALL_MARBLE]: [80, 81, 82, 83, 84, 85, 86, 87, 88, 89,   // row 5 front
                              96, 97, 98, 99, 103, 104, 105],            // row 6 back
  [GroundType.WALL_GRAY]:   [112, 113, 114, 115, 116, 117, 118, 119, 120, 121,
                              128, 129, 130, 131, 135, 136, 137],
  [GroundType.WALL_BRICK]:  [144, 145, 146, 147, 148, 149, 150, 151, 152, 153,
                              160, 161, 162, 163, 167, 168, 169],
  [GroundType.WALL_PINK]:   [176, 177, 178, 179, 180, 181, 182, 183, 184, 185,
                              192, 193, 194, 195, 199, 200, 201],
}
