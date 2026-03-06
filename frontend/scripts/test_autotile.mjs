import fs from 'fs'
import { PNG } from 'pngjs'

// Load room_builder.png
const src = fs.readFileSync('../public/assets/office/tiles/room_builder.png')
const tileset = PNG.sync.read(src)

const TILE = 16
const TS_COLS = tileset.width / TILE  // 16

// Extract a tile from the tileset
function getTilePixels(frameIdx) {
  const tc = frameIdx % TS_COLS
  const tr = Math.floor(frameIdx / TS_COLS)
  const pixels = Buffer.alloc(TILE * TILE * 4)
  for (let y = 0; y < TILE; y++) {
    for (let x = 0; x < TILE; x++) {
      const srcIdx = ((tr * TILE + y) * tileset.width + (tc * TILE + x)) * 4
      const dstIdx = (y * TILE + x) * 4
      pixels[dstIdx]   = tileset.data[srcIdx]
      pixels[dstIdx+1] = tileset.data[srcIdx+1]
      pixels[dstIdx+2] = tileset.data[srcIdx+2]
      pixels[dstIdx+3] = tileset.data[srcIdx+3]
    }
  }
  return pixels
}

// Place a tile onto the output PNG
function placeTile(out, col, row, frameIdx) {
  const pixels = getTilePixels(frameIdx)
  for (let y = 0; y < TILE; y++) {
    for (let x = 0; x < TILE; x++) {
      const srcIdx = (y * TILE + x) * 4
      const a = pixels[srcIdx+3]
      if (a === 0) continue // skip transparent
      const dstIdx = ((row * TILE + y) * out.width + (col * TILE + x)) * 4
      // Alpha blend
      const sa = a / 255
      const da = 1 - sa
      out.data[dstIdx]   = Math.round(pixels[srcIdx] * sa + out.data[dstIdx] * da)
      out.data[dstIdx+1] = Math.round(pixels[srcIdx+1] * sa + out.data[dstIdx+1] * da)
      out.data[dstIdx+2] = Math.round(pixels[srcIdx+2] * sa + out.data[dstIdx+2] * da)
      out.data[dstIdx+3] = 255
    }
  }
}

// ── Test room layout ──
// 12 cols x 10 rows
// W=wall, F=floor, V=void
const W = 1, F = 2, V = 0
const layout = [
  // row 0
  [V, V, V, V, V, V, V, V, V, V, V, V],
  // row 1
  [V, W, W, W, W, W, W, W, W, W, W, V],
  // row 2
  [V, W, F, F, F, F, F, F, F, F, W, V],
  // row 3
  [V, W, F, F, F, F, F, F, F, F, W, V],
  // row 4
  [V, W, F, F, F, F, F, F, F, F, W, V],
  // row 5
  [V, W, F, F, F, W, W, W, F, F, W, V],
  // row 6
  [V, W, F, F, F, W, V, W, F, F, W, V],
  // row 7
  [V, W, F, F, F, W, W, W, F, F, W, V],
  // row 8
  [V, W, W, W, W, W, W, W, W, W, W, V],
  // row 9
  [V, V, V, V, V, V, V, V, V, V, V, V],
]
const ROWS = layout.length
const COLS = layout[0].length

function isWallAt(r, c) {
  if (r < 0 || r >= ROWS || c < 0 || c >= COLS) return false
  return layout[r][c] === W
}
function isFloorAt(r, c) {
  if (r < 0 || r >= ROWS || c < 0 || c >= COLS) return false
  return layout[r][c] === F
}

// ── Auto-tile logic ──
// For each wall cell, determine which structural frame to use
// Based on 8 neighbors (N, NE, E, SE, S, SW, W, NW)

function getAutoTileFrame(r, c) {
  const n  = isWallAt(r-1, c)
  const ne = isWallAt(r-1, c+1)
  const e  = isWallAt(r, c+1)
  const se = isWallAt(r+1, c+1)
  const s  = isWallAt(r+1, c)
  const sw = isWallAt(r+1, c-1)
  const w  = isWallAt(r, c-1)
  const nw = isWallAt(r-1, c-1)

  const sFloor = isFloorAt(r+1, c)  // south is floor (north-facing wall)

  // Count cardinal wall neighbors
  const cardinals = (n?1:0) + (e?1:0) + (s?1:0) + (w?1:0)

  // ── North-facing wall (south = floor): use horizontal wall ──
  if (sFloor && !s) {
    if (e && w) {
      // Inner corner = where the wall stretch starts/ends
      // Check if neighbor's south is also floor (= same stretch) or not (= corner)
      const swFloor = isFloorAt(r+1, c-1)
      const seFloor = isFloorAt(r+1, c+1)
      if (!swFloor && seFloor) return 23  // inner NW corner (left end of stretch)
      if (swFloor && !seFloor) return 25  // inner NE corner (right end of stretch)
      return 24  // plain horizontal
    }
    if (e && !w) {
      // Wall ends on left, continues right
      return 50  // outer NW corner (H + V-left below)
    }
    if (!e && w) {
      // Wall ends on right, continues left
      return 49  // outer NE corner (H + V-right below)
    }
    // Isolated horizontal
    return 24
  }

  // ── South-facing wall (north = floor): bottom edge ──
  if (isFloorAt(r-1, c) && !n) {
    if (e && w) {
      const nwFloor = isFloorAt(r-1, c-1)
      const neFloor = isFloorAt(r-1, c+1)
      if (!nwFloor && neFloor) return 55  // inner SW corner (left end)
      if (nwFloor && !neFloor) return 57  // inner SE corner (right end)
      return 56  // plain bottom horizontal
    }
    if (e && !w) return 55  // SW corner-ish
    if (!e && w) return 57  // SE corner-ish
    return 56
  }

  // ── Vertical walls ──
  if (n && s) {
    if (isFloorAt(r, c+1)) return 39  // W edge (vertical on right, floor to east)
    if (isFloorAt(r, c-1)) return 41  // E edge (vertical on left, floor to west)

    // Wall surrounded by walls on N and S, check E/W
    if (e && w) {
      // Fully surrounded - check diagonals for inner corners
      if (!se && isFloorAt(r+1, c+1)) return 23
      if (!sw && isFloorAt(r+1, c-1)) return 25
      if (!ne && isFloorAt(r-1, c+1)) return 55
      if (!nw && isFloorAt(r-1, c-1)) return 57
      return 27  // thick vertical (both sides)
    }
    if (e) return 39
    if (w) return 41
    return 3  // default vertical
  }

  // ── Corner-only walls (only 2 adjacent cardinal neighbors) ──
  if (e && s && !n && !w) return 34  // outer NW (wall goes S and E)
  if (s && w && !n && !e) return 33  // outer NE (wall goes S and W)
  if (n && e && !s && !w) return 18  // outer SW (wall goes N and E)
  if (n && w && !s && !e) return 17  // outer SE (wall goes N and W)

  // ── T-junctions ──
  if (n && e && s && !w) return 21  // T open west
  if (n && s && w && !e) return 22  // T open east
  if (e && s && w && !n) return 19  // T open north (horizontal + down)
  if (n && e && w && !s) return 56  // T open south

  // ── End caps ──
  if (s && !n && !e && !w) return 43  // cap, wall goes down
  if (n && !s && !e && !w) return 43  // cap, wall goes up
  if (e && !n && !s && !w) return 60  // cap east
  if (w && !n && !s && !e) return 58  // cap west

  // ── Isolated ──
  return 8  // solid fill fallback
}

// ── Render ──
const SCALE = 3
const outW = COLS * TILE * SCALE
const outH = ROWS * TILE * SCALE
const out = new PNG({ width: COLS * TILE, height: ROWS * TILE })

// Fill background (void = dark)
for (let i = 0; i < out.data.length; i += 4) {
  out.data[i] = 0x1a; out.data[i+1] = 0x15; out.data[i+2] = 0x10; out.data[i+3] = 255
}

// Place floor tiles
const FLOOR_FRAMES = [157, 158, 159]  // gray floor
for (let r = 0; r < ROWS; r++) {
  for (let c = 0; c < COLS; c++) {
    if (layout[r][c] === F) {
      const frame = FLOOR_FRAMES[(r * COLS + c) % FLOOR_FRAMES.length]
      placeTile(out, c, r, frame)
    }
  }
}

// Place wall tiles (structural auto-tile)
for (let r = 0; r < ROWS; r++) {
  for (let c = 0; c < COLS; c++) {
    if (layout[r][c] !== W) continue
    const frame = getAutoTileFrame(r, c)
    placeTile(out, c, r, frame)
  }
}

// Scale up 3x for visibility
const scaled = new PNG({ width: outW, height: outH })
for (let y = 0; y < out.height; y++) {
  for (let x = 0; x < out.width; x++) {
    const si = (y * out.width + x) * 4
    for (let sy = 0; sy < SCALE; sy++) {
      for (let sx = 0; sx < SCALE; sx++) {
        const di = ((y * SCALE + sy) * outW + (x * SCALE + sx)) * 4
        scaled.data[di]   = out.data[si]
        scaled.data[di+1] = out.data[si+1]
        scaled.data[di+2] = out.data[si+2]
        scaled.data[di+3] = out.data[si+3]
      }
    }
  }
}

fs.writeFileSync('test_autotile.png', PNG.sync.write(scaled))
console.log(`Wrote test_autotile.png (${outW}x${outH})`)
console.log()

// Print which frame was used for each wall cell
console.log('Frame map:')
for (let r = 0; r < ROWS; r++) {
  let line = ''
  for (let c = 0; c < COLS; c++) {
    if (layout[r][c] === V) line += '  · '
    else if (layout[r][c] === F) line += '  F '
    else line += `#${String(getAutoTileFrame(r, c)).padStart(2)} `
  }
  console.log(line)
}
