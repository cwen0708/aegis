# Wall Auto-Tile System — Complete Reference

> This document contains enough detail for another developer (human or AI) to understand, modify, or extend the wall auto-tile system without reading the source code first.

## Project Context

**Aegis** is an office simulation with a Phaser 3 game engine (Vue 3 frontend). The office is rendered on a tile-based grid where each cell is 16×16 pixels, displayed at 3× zoom (48×48 on screen).

### Key Files

| File | Role |
|------|------|
| `frontend/src/game/types.ts` | `GroundType` enum, `isWall()`, `getWallAutoTileFrames()`, asset catalogs |
| `frontend/src/game/renderUtils.ts` | `renderFloor()`, `renderWalls()` — creates Phaser Image objects |
| `frontend/src/game/EditorScene.ts` | Editor Phaser scene — handles paint/erase, delegates rendering |
| `frontend/src/game/OfficeScene.ts` | Gameplay Phaser scene — characters, animations |
| `frontend/src/game/layoutManager.ts` | Layout data: `buildDefaultLayout()`, serialization, workstation detection |
| `frontend/src/components/OfficeEditor.vue` | Vue component wrapping EditorScene with palette UI |

### Constants

```typescript
const TILE = 16   // pixels per tile
const ZOOM = 3    // display scale
const SS_COLS = 16 // spritesheet columns (256px / 16px)
```

---

## GroundType Enum

```typescript
export const GroundType = {
  VOID: 0,          // 空白 — empty/dark, not walkable
  WALL: 1,          // 牆壁 — structural wall (white/gray, no colored variant)
  FLOOR: 2,         // 地板
  WOOD: 3,          // 木地板
  DARK: 4,          // 深色地板
  MARBLE: 5,        // 大理石 (floor)
  STONE: 6,         // 石磚
  BEIGE: 7,         // 米磚
  BAMBOO: 8,        // 竹地板
  CHECKER: 9,       // 格子磚
  CARPET: 10,       // 地毯
  RED: 11,          // 紅磚
  LAVENDER: 12,     // 薰衣草
  // ── Colored wall types (13–16) ──
  WALL_MARBLE: 13,  // 大理石牆 — rows 5+6
  WALL_GRAY: 14,    // 灰牆     — rows 7+8
  WALL_BRICK: 15,   // 磚牆     — rows 9+10
  WALL_PINK: 16,    // 粉牆     — rows 11+12
} as const
```

**`isWall(gt)`** returns `true` when `gt === 1` OR `13 <= gt <= 16`.

Floor types (2–12) are rendered by `renderFloor()` using `GROUND_TILE_FRAMES` (spritesheet frame indices).
Wall types (1, 13–16) are rendered by `renderWalls()` using `getWallAutoTileFrames()`.

---

## Spritesheet: `room_builder.png`

**Path**: `frontend/public/assets/office/tiles/room_builder.png`
**Size**: 256×224 pixels = **16 columns × 14 rows** of 16×16 tiles.
**Frame index formula**: `frameIdx = row * 16 + col`

### Complete Frame Map

```
        Col:  0    1    2    3    4    5    6    7    8    9   10   11   12   13   14   15
Row  0:    [  0] [  1] [  2] [  3] [  4] [  5] [  6] [  7] [  8] [  9] [ 10] [ 11] [ 12] [ 13] [ 14] [ 15]
Row  1:    [ 16] [ 17] [ 18] [ 19] [ 20] [ 21] [ 22] [ 23] [ 24] [ 25] [ 26] [ 27] [ 28] [ 29] [ 30] [ 31]
Row  2:    [ 32] [ 33] [ 34] [ 35] [ 36] [ 37] [ 38] [ 39] [ 40] [ 41] [ 42] [ 43] [ 44] [ 45] [ 46] [ 47]
Row  3:    [ 48] [ 49] [ 50] [ 51] [ 52] [ 53] [ 54] [ 55] [ 56] [ 57] [ 58] [ 59] [ 60] [ 61] [ 62] [ 63]
Row  4:    [ 64] [ 65] [ 66] [ 67] [ 68] [ 69] [ 70] [ 71] [ 72] [ 73] [ 74] [ 75] [ 76] [ 77] [ 78] [ 79]
─── Colored wall rows ───
Row  5:    [ 80] [ 81] [ 82] [ 83] [ 84] [ 85] [ 86] [ 87] [ 88] [ 89] [ 90] [ 91] [ 92] ...floor tiles
Row  6:    [ 96] [ 97] [ 98] [ 99] [100] [101] [102] [103] [104] [105] [106] [107] [108] ...floor tiles
Row  7:    [112] [113] [114] [115] [116] [117] [118] [119] [120] [121] [122] [123] [124] ...floor tiles
Row  8:    [128] [129] [130] [131] [132] [133] [134] [135] [136] [137] [138] [139] [140] ...floor tiles
Row  9:    [144] [145] [146] [147] [148] [149] [150] [151] [152] [153] [154] [155] [156] ...floor tiles
Row 10:    [160] [161] [162] [163] [164] [165] [166] [167] [168] [169] [170] [171] [172] ...floor tiles
Row 11:    [176] [177] [178] [179] [180] [181] [182] [183] [184] [185] [186] [187] [188] ...floor tiles
Row 12:    [192] [193] [194] [195] [196] [197] [198] [199] [200] [201] [202] [203] [204] ...floor tiles
Row 13:    ...floor tiles only
```

### Structural Tiles (Rows 0–4)

White/gray tiles used for **all wall types** when the shape requires corners, T-junctions, vertical segments, or thin interior walls. These are used regardless of the wall's color.

| Frame | Col,Row | Visual | Used When |
|-------|---------|--------|-----------|
| **3** | 3,0 | Default vertical | N+S wall, no floor on either side, no E/W neighbors |
| **8** | 8,0 | Isolated/solid | Completely isolated wall cell |
| **17** | 1,1 | Outer corner SE ╝ | `n && w && !s && !e` |
| **18** | 2,1 | Outer corner SW ╚ | `n && e && !s && !w` |
| **19** | 3,1 | T-junction ┬ open N | `e && s && w && !n` |
| **21** | 5,1 | T-junction ├ open W | `n && e && s && !w` |
| **22** | 6,1 | T-junction ┤ open E | `n && s && w && !e` |
| **23** | 7,1 | North-facing L (left inner corner) | Structural N-facing, `!swFloor && seFloor` |
| **24** | 8,1 | North-facing M (middle) | Structural N-facing, both diagonal floors |
| **25** | 9,1 | North-facing R (right inner corner) | Structural N-facing, `swFloor && !seFloor` |
| **27** | 11,1 | Thin wall fill | Interior divider, both E+W walls, no upper diagonal walls |
| **28** | 12,1 | Thin wall capped | Interior divider, both upper diagonals are walls |
| **33** | 1,2 | Outer corner NE ╗ | `s && w && !n && !e` |
| **34** | 2,2 | Outer corner NW ╔ | `e && s && !n && !w` |
| **39** | 7,2 | Vertical W-face │ | Wall with floor to east |
| **41** | 9,2 | Vertical E-face │ | Wall with floor to west |
| **42** | 10,2 | Thin wall left junction | Interior divider left end, or upper-left wall junction |
| **43** | 11,2 | End cap (N or S) | Only one cardinal neighbor (N or S) |
| **44** | 12,2 | Thin wall right junction | Interior divider right end, or upper-right wall junction |
| **49** | 1,3 | N-facing end cap R | N-facing structural, `!e && w` |
| **50** | 2,3 | N-facing end cap L | N-facing structural, `e && !w` |
| **55** | 7,3 | South-facing L | Structural S-facing, left inner corner |
| **56** | 8,3 | South-facing M / T-junction ┴ | Structural S-facing middle, OR `n && e && w && !s` |
| **57** | 9,3 | South-facing R | Structural S-facing, right inner corner |
| **58** | 10,3 | End cap W ← | `w && !n && !s && !e` |
| **60** | 12,3 | End cap E → | `e && !n && !s && !w` |

### Colored Wall Groups (Rows 5–12)

Each colored wall type uses **2 spritesheet rows**:

| Wall Type | Value | S-facing Row (front/decorative) | N-facing Row (back/cap) |
|-----------|-------|:-------------------------------:|:----------------------:|
| Marble 大理石 | 13 | Row 5 (frames 80–89) | Row 6 (frames 96–105) |
| Gray 灰 | 14 | Row 7 (frames 112–121) | Row 8 (frames 128–137) |
| Brick 磚 | 15 | Row 9 (frames 144–153) | Row 10 (frames 160–169) |
| Pink 粉 | 16 | Row 11 (frames 176–185) | Row 12 (frames 192–201) |

```typescript
// WALL_GROUP maps wall type → [north-facing row, south-facing row]
const WALL_GROUP: Partial<Record<number, [number, number]>> = {
  [GroundType.WALL_MARBLE]: [6, 5],   // N-facing = row 6, S-facing = row 5
  [GroundType.WALL_GRAY]:   [8, 7],
  [GroundType.WALL_BRICK]:  [10, 9],
  [GroundType.WALL_PINK]:   [12, 11],
}
```

> **IMPORTANT**: The row numbers are **counter-intuitive**. The even row (e.g. 6) contains the north-facing (back/cap) view, while the odd row (e.g. 5) contains the south-facing (decorative front) view. The `WALL_GROUP` tuple is `[north-facing row, south-facing row]`.

#### Column Layout Per Colored Row

**South-facing row** (decorative front face, what you see when looking at a wall from above):
```
Col 0: Outer Left   — has top decoration bar (no wall above)
Col 1: Outer Middle  — has top decoration bar
Col 2: Outer Right   — has top decoration bar
Col 3: Standalone    — fully enclosed
Col 4-6: (reserved / unused by auto-tile)
Col 7: Inner Left   — no top bar (wall continues above)
Col 8: Inner Middle  — no top bar
Col 9: Inner Right   — no top bar
```

**North-facing row** (back/cap view, what you see when looking at a wall from below):
```
Col 0: Left
Col 1: Middle
Col 2: Right
Col 3: Standalone
Col 4-6: (unused)
Col 7: Inner Left
Col 8: Inner Middle
Col 9: Inner Right
```

Frame index formula: `row * SS_COLS + col` (SS_COLS = 16)

Example: Marble north-facing middle = row 6 × 16 + 1 = **97**
Example: Marble south-facing outer left = row 5 × 16 + 0 = **80**

---

## Auto-Tile Algorithm

### Function Signature

```typescript
export function getWallAutoTileFrames(
  ground: number[],  // flat row-major ground array
  cols: number,      // grid width
  rows: number,      // grid height
  r: number,         // current row
  c: number,         // current column
): [number, number | undefined]
// Returns [primaryFrame, secondaryFrame?]
// secondary is set only for double-sided vertical walls (renders both faces)
```

### Helper Functions (internal)

```typescript
wallAt(row, col)  → true if cell is any wall type (isWall), false if OOB
floorAt(row, col) → true if cell is non-VOID and non-wall, false if OOB
```

### Variables Computed

```typescript
const gt = ground[r * cols + c]           // this cell's type
const group = WALL_GROUP[gt]              // colored group or undefined (structural)
const n = wallAt(r-1, c)                  // north neighbor is wall
const e = wallAt(r, c+1)                  // east neighbor is wall
const s = wallAt(r+1, c)                  // south neighbor is wall
const w = wallAt(r, c-1)                  // west neighbor is wall
const sFloor = floorAt(r+1, c)           // south neighbor is floor
const nFloor = floorAt(r-1, c)           // north neighbor is floor
```

### Priority Order (checked top to bottom, first match wins)

#### 1. Interior Horizontal Wall

**Condition**: `sFloor && !s && nFloor && !n` (floor on both N and S sides)

This creates thin structural room dividers. **Always uses structural frames regardless of wall color.**

```
if (e && w):
  nwWall = wallAt(r-1, c-1)
  neWall = wallAt(r-1, c+1)
  if nwWall && neWall → frame 28  (top-capped, wall from both above-left and above-right)
  if nwWall only     → frame 42  (left junction)
  if neWall only     → frame 44  (right junction)
  else               → frame 27  (plain thin fill)
if (e && !w)  → frame 42  (left end cap)
if (!e && w)  → frame 44  (right end cap)
else          → frame 28  (isolated thin wall)
```

> **Note**: If a wall has wall directly above (`n` is true), it does NOT match this case — it falls through to the north-facing case below. This handles "pillar through the divider" scenarios.

#### 2. North-Facing Wall

**Condition**: `sFloor && !s` (floor to south, no wall to south)

This is the **back/cap** view — what you see when a room's wall is at the top edge.

**If colored** (`group` exists):
```
row = group[0]  // north-facing row
if (e && w):
  swFloor = floorAt(r+1, c-1)
  seFloor = floorAt(r+1, c+1)
  if (n):  // wall above → inner variant (cols 7-9)
    !swFloor && seFloor  → row*16 + 7  (inner left corner)
    swFloor && !seFloor  → row*16 + 9  (inner right corner)
    else                 → row*16 + 8  (inner middle)
  else:    // no wall above → outer variant (cols 0-2)
    !swFloor && seFloor  → row*16 + 0  (outer left corner)
    swFloor && !seFloor  → row*16 + 2  (outer right corner)
    else                 → row*16 + 1  (outer middle)
if (e && !w) → row*16 + (n ? 7 : 0)   (left end, inner or outer)
if (!e && w) → row*16 + (n ? 9 : 2)   (right end, inner or outer)
else         → row*16 + 3              (standalone)
```

**If structural** (no `group`, i.e. `GroundType.WALL = 1`):
```
if (e && w):
  swFloor = floorAt(r+1, c-1)
  seFloor = floorAt(r+1, c+1)
  !swFloor && seFloor  → 23  (left inner corner)
  swFloor && !seFloor  → 25  (right inner corner)
  else                 → 24  (middle)
if (e && !w) → 50  (left end cap)
if (!e && w) → 49  (right end cap)
else         → 24  (isolated horizontal)
```

#### 3. South-Facing Wall

**Condition**: `floorAt(r-1, c) && !n` (floor to north, no wall to north)

This is the **decorative front face** — what you see when a room's wall is at the bottom edge.

**If colored**:
```
row = group[1]  // south-facing row
if (e && w):
  nwFloor = floorAt(r-1, c-1)
  neFloor = floorAt(r-1, c+1)
  !nwFloor && neFloor  → row*16 + 0  (left inner corner)
  nwFloor && !neFloor  → row*16 + 2  (right inner corner)
  else                 → row*16 + 1  (middle)
if (e && !w) → row*16 + 0  (left end)
if (!e && w) → row*16 + 2  (right end)
else         → row*16 + 1  (standalone)
```

**If structural**:
```
if (e && w):
  nwFloor = floorAt(r-1, c-1)
  neFloor = floorAt(r-1, c+1)
  !nwFloor && neFloor  → 55  (left inner corner)
  nwFloor && !neFloor  → 57  (right inner corner)
  else                 → 56  (middle)
if (e && !w) → 55
if (!e && w) → 57
else         → 56
```

#### 4. Vertical Wall

**Condition**: `n && s` (wall above AND below)

```
eFloor = floorAt(r, c+1)
wFloor = floorAt(r, c-1)

if eFloor && wFloor → [39, 41]  // ← DUAL FRAME (both faces, secondary set!)
if eFloor           → [39]      // west-face only
if wFloor           → [41]      // east-face only

if (e && w):  // thick wall interior — check diagonals for inner corners
  if floor at SE → 23
  if floor at SW → 25
  if floor at NE → 55
  if floor at NW → 57
  else           → 27  (thick wall fill)

if e → 39
if w → 41
else → 3  (default vertical, no visible face)
```

#### 5. Outer Corners (exactly 2 adjacent cardinals)

```
e && s && !n && !w → 34  (NW corner ╔)
s && w && !n && !e → 33  (NE corner ╗)
n && e && !s && !w → 18  (SW corner ╚)
n && w && !s && !e → 17  (SE corner ╝)
```

#### 6. T-Junctions (exactly 3 cardinals)

```
n && e && s && !w → 21  (├ open west)
n && s && w && !e → 22  (┤ open east)
e && s && w && !n → 19  (┬ open north)
n && e && w && !s → 56  (┴ open south)
```

#### 7. End Caps (exactly 1 cardinal)

```
s && !n && !e && !w → 43  (cap, wall goes down)
n && !s && !e && !w → 43  (cap, wall goes up)
e && !n && !s && !w → 60  (cap east →)
w && !n && !s && !e → 58  (cap west ←)
```

#### 8. Isolated Fallback

```
→ 8  (solid fill)
```

---

## Rendering Pipeline

### `renderFloor(scene, layout)` → `Phaser.GameObjects.GameObject[]`

1. Creates a Graphics object for VOID fills (dark background)
2. Iterates every cell:
   - VOID → fillRect with dark color
   - Wall → skip (handled separately)
   - Floor → `scene.add.image(x, y, 'floor_tiles', frameIdx)` using `GROUND_TILE_FRAMES`
   - Frame variant cycling: `frames[(r * cols + c) % frames.length]`
3. Returns all created objects (caller stores for cleanup on re-render)

### `renderWalls(scene, layout)` → `Phaser.GameObjects.GameObject[]`

1. Iterates every cell; skips non-wall cells
2. For each wall: calls `getWallAutoTileFrames(ground, cols, rows, r, c)`
3. Creates `scene.add.image(x, y, 'floor_tiles', primaryFrame)` at depth `(r + 1) * TILE`
4. If `secondaryFrame` is set (dual-face vertical wall), creates second image at same position and depth
5. Returns all created objects

### `renderItemImage(scene, item)` → `Phaser.GameObjects.Image | null`

1. Looks up `FURNITURE_ASSETS[item.type]` → filename
2. Uses texture key `furn_${filename}`
3. Depth = `bottomRow * TILE` where `bottomRow = item.row + ceil(spriteH / TILE)`

### Depth Sorting

```
Floor tiles:     depth = 0
Wall tiles:      depth = (r + 1) * TILE  (so lower walls render on top of upper walls)
Furniture/props: depth = bottomRow * TILE (based on sprite bottom edge)
Characters:      depth = tileRow * TILE + TILE/2
```

---

## Editor Integration

### Layers

```typescript
type EditorLayer = 'ground' | 'wall' | 'furniture' | 'props'
```

- **Ground layer**: palette shows floor types (2–12), excludes wall types
- **Wall layer**: palette shows 4 colored wall styles from `WALL_TILE_FRAMES`; placing sets `GroundType.WALL_MARBLE` (or selected) at cell
- **Furniture/Props**: places items from `FURNITURE_CATALOG` / `PROPS_CATALOG`

### Ground/Wall Placement

When user right-clicks on the canvas:
1. `EditorScene.handlePlace()` is called
2. For ground layer: `setGround(layout, row, col, selectedGroundType)` then re-render floor + walls
3. For wall layer: `setGround(layout, row, col, selectedWallType)` then re-render floor + walls
4. Re-rendering walls triggers `getWallAutoTileFrames()` for all wall cells, so neighbors update automatically

### Wall Palette Display

`WALL_TILE_FRAMES` contains frame indices for each colored wall type, used as thumbnail previews:

```typescript
export const WALL_TILE_FRAMES: Partial<Record<GroundType, number[]>> = {
  [GroundType.WALL_MARBLE]: [80,81,82,83,...,96,97,98,99,103,104,105],
  [GroundType.WALL_GRAY]:   [112,...,128,129,130,131,135,136,137],
  [GroundType.WALL_BRICK]:  [144,...,160,161,162,163,167,168,169],
  [GroundType.WALL_PINK]:   [176,...,192,193,194,195,199,200,201],
}
```

---

## Data Format

### OfficeLayout

```typescript
interface OfficeLayout {
  version: 1
  cols: number              // grid width (default 32)
  rows: number              // grid height (default 22)
  ground: number[]          // flat row-major array, length = cols * rows
  furniture: FurnitureItem[]
  props: FurnitureItem[]
  rooms: RoomDef[]
  workstations: WorkstationDef[]
}
```

`ground[r * cols + c]` = GroundType value at row `r`, column `c`.

### Coordinate System

```
(0,0) ──────── col+ ──────→
  │
  │     N (r-1)
  │   W ■ E
 row+   S (r+1)
  │
  ▼
```

- Row increases downward (south)
- Column increases rightward (east)
- "North-facing wall" = wall that faces the camera from the north side of a room (floor is to the south of the wall)
- "South-facing wall" = wall at the bottom of a room (floor is to the north)

---

## Dev Scripts

Located in `frontend/scripts/`. Run with `cd frontend/scripts && node <script>.mjs`.

Requires `pngjs` (in devDependencies).

| Script | Purpose | Output |
|--------|---------|--------|
| `test_autotile.mjs` | Renders structural auto-tile for a test room (12×10) | `test_autotile.png` (3× scaled) |
| `test_colored_walls.mjs` | Renders colored marble wall for a two-room layout (16×12) | `test_colored_walls.png` (3× scaled) |
| `tile_ascii.mjs` | Prints any tile frame as ASCII art to stdout | stdout |
| `analyze_walls.mjs` | Analyzes edge/corner patterns of structural wall tiles (rows 0–3) | stdout |
| `parse_ase.mjs` | Parses Aseprite `.aseprite` files from examples folder | stdout |

Both test scripts contain their own copy of the auto-tile logic (simplified, without TypeScript types). When modifying `getWallAutoTileFrames()` in `types.ts`, the test scripts should be updated to match.

---

## Known Edge Cases

1. **Pillar through divider**: When an interior horizontal wall has a wall directly above (`n` is true), the interior case does NOT match. The cell falls through to the north-facing case and uses colored inner tiles (cols 7-9). This is intentional.

2. **Dual-frame vertical walls**: When a vertical wall has floor on **both** east and west sides, `getWallAutoTileFrames()` returns `[39, 41]` — both frames are rendered at the same position, overlapping. This creates a dual-sided wall appearance.

3. **Structural vs colored**: The structural wall type (`GroundType.WALL = 1`) uses only structural frames (rows 0-4). The 4 colored types (13-16) use their colored row frames for north/south-facing cases, but fall back to structural frames for corners, T-junctions, end caps, vertical segments, and interior dividers.

4. **Mixed wall colors**: Adjacent walls of different colored types will each use their own color group for north/south faces, but share the same structural tiles for corners. This can create visual seams at junctions between different wall colors.
