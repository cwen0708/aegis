import fs from 'fs'
import { PNG } from 'pngjs'

const src = fs.readFileSync('../public/assets/office/tiles/room_builder.png')
const tileset = PNG.sync.read(src)
const TILE = 16
const TS_COLS = tileset.width / TILE

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

function placeTile(out, col, row, frameIdx) {
  const pixels = getTilePixels(frameIdx)
  for (let y = 0; y < TILE; y++) {
    for (let x = 0; x < TILE; x++) {
      const srcIdx = (y * TILE + x) * 4
      const a = pixels[srcIdx+3]
      if (a === 0) continue
      const dstIdx = ((row * TILE + y) * out.width + (col * TILE + x)) * 4
      const sa = a / 255, da = 1 - sa
      out.data[dstIdx]   = Math.round(pixels[srcIdx] * sa + out.data[dstIdx] * da)
      out.data[dstIdx+1] = Math.round(pixels[srcIdx+1] * sa + out.data[dstIdx+1] * da)
      out.data[dstIdx+2] = Math.round(pixels[srcIdx+2] * sa + out.data[dstIdx+2] * da)
      out.data[dstIdx+3] = 255
    }
  }
}

// ── Types (matching updated types.ts) ──
const V = 0, W = 1, F = 2, M = 13 // WALL_MARBLE
const SS_COLS = 16

function isWall(gt) { return gt === 1 || (gt >= 13 && gt <= 16) }

// Wall groups: [north-facing row, south-facing row]
const WALL_GROUP = { 13: [6, 5], 14: [8, 7], 15: [10, 9], 16: [12, 11] }

function getFrames(ground, cols, rows, r, c) {
  const gt = ground[r * cols + c]
  const group = WALL_GROUP[gt]

  const wallAt = (row, col) => {
    if (row < 0 || row >= rows || col < 0 || col >= cols) return false
    return isWall(ground[row * cols + col])
  }
  const floorAt = (row, col) => {
    if (row < 0 || row >= rows || col < 0 || col >= cols) return false
    const g = ground[row * cols + col]
    return g !== 0 && !isWall(g)
  }

  const n = wallAt(r-1,c), e = wallAt(r,c+1), s = wallAt(r+1,c), w = wallAt(r,c-1)
  const sFloor = floorAt(r+1,c)
  const nFloor = floorAt(r-1,c)

  // Interior horizontal wall (floor both N and S) → thin structural divider
  if (sFloor && !s && nFloor && !n) {
    if (e && w) {
      const nwW = wallAt(r-1,c-1), neW = wallAt(r-1,c+1)
      if (nwW && neW) return [28]
      if (nwW) return [42]
      if (neW) return [44]
      return [27]
    }
    if (e && !w) return [42]
    if (!e && w) return [44]
    return [28]
  }

  // North-facing
  if (sFloor && !s) {
    if (group) {
      const row = group[0]
      if (e && w) {
        const swF = floorAt(r+1,c-1), seF = floorAt(r+1,c+1)
        if (n) {
          if (!swF && seF) return [row*16+7]
          if (swF && !seF) return [row*16+9]
          return [row*16+8]
        }
        if (!swF && seF) return [row*16+0]
        if (swF && !seF) return [row*16+2]
        return [row*16+1]
      }
      if (e && !w) return [row*16+(n?7:0)]
      if (!e && w) return [row*16+(n?9:2)]
      return [row*16+3]
    }
    if (e && w) {
      const swF = floorAt(r+1,c-1), seF = floorAt(r+1,c+1)
      if (!swF && seF) return [23]
      if (swF && !seF) return [25]
      return [24]
    }
    if (e && !w) return [50]
    if (!e && w) return [49]
    return [24]
  }

  // South-facing
  if (floorAt(r-1,c) && !n) {
    if (group) {
      const row = group[1]  // secondary row
      if (e && w) {
        const nwF = floorAt(r-1,c-1), neF = floorAt(r-1,c+1)
        if (!nwF && neF) return [row*16+0]
        if (nwF && !neF) return [row*16+2]
        return [row*16+1]
      }
      if (e && !w) return [row*16+0]
      if (!e && w) return [row*16+2]
      return [row*16+1]
    }
    if (e && w) {
      const nwF = floorAt(r-1,c-1), neF = floorAt(r-1,c+1)
      if (!nwF && neF) return [55]
      if (nwF && !neF) return [57]
      return [56]
    }
    if (e && !w) return [55]
    if (!e && w) return [57]
    return [56]
  }

  // Vertical
  if (n && s) {
    const eF = floorAt(r,c+1), wF = floorAt(r,c-1)
    if (eF && wF) return [39, 41]
    if (eF) return [39]
    if (wF) return [41]
    if (e && w) {
      if (!wallAt(r+1,c+1) && floorAt(r+1,c+1)) return [23]
      if (!wallAt(r+1,c-1) && floorAt(r+1,c-1)) return [25]
      if (!wallAt(r-1,c+1) && floorAt(r-1,c+1)) return [55]
      if (!wallAt(r-1,c-1) && floorAt(r-1,c-1)) return [57]
      return [27]
    }
    if (e) return [39]
    if (w) return [41]
    return [3]
  }

  if (e && s && !n && !w) return [34]
  if (s && w && !n && !e) return [33]
  if (n && e && !s && !w) return [18]
  if (n && w && !s && !e) return [17]
  if (n && e && s && !w) return [21]
  if (n && s && w && !e) return [22]
  if (e && s && w && !n) return [19]
  if (n && e && w && !s) return [56]
  if (s && !n && !e && !w) return [43]
  if (n && !s && !e && !w) return [43]
  if (e && !n && !s && !w) return [60]
  if (w && !n && !s && !e) return [58]
  return [8]
}

// ── Test layout: Marble room with inner room + doorway ──
const layout = [
  [V,V,V,V,V,V,V,V,V,V,V,V,V,V,V,V],
  [V,M,M,M,M,M,M,M,M,M,M,M,M,M,M,V],
  [V,M,F,F,F,F,F,M,F,F,F,F,F,F,M,V],
  [V,M,F,F,F,F,F,M,F,F,F,F,F,F,M,V],
  [V,M,F,F,F,F,F,F,F,F,F,F,F,F,M,V], // doorway col 7
  [V,M,F,F,F,F,F,M,F,F,F,F,F,F,M,V],
  [V,M,M,M,M,M,M,M,M,M,M,M,M,M,M,V],
  [V,M,F,F,F,F,F,F,F,F,F,F,F,F,M,V],
  [V,M,F,F,F,F,F,F,F,F,F,F,F,F,M,V],
  [V,M,F,F,F,F,F,F,F,F,F,F,F,F,M,V],
  [V,M,M,M,M,M,M,M,M,M,M,M,M,M,M,V],
  [V,V,V,V,V,V,V,V,V,V,V,V,V,V,V,V],
]
const ROWS = layout.length, COLS = layout[0].length
const ground = layout.flat()

// Render
const out = new PNG({ width: COLS * TILE, height: ROWS * TILE })
for (let i = 0; i < out.data.length; i += 4) {
  out.data[i]=0x1a; out.data[i+1]=0x15; out.data[i+2]=0x10; out.data[i+3]=255
}

const FLOOR_FRAMES = [157, 158, 159]
for (let r = 0; r < ROWS; r++)
  for (let c = 0; c < COLS; c++)
    if (ground[r*COLS+c] === F) placeTile(out, c, r, FLOOR_FRAMES[(r*COLS+c)%3])

console.log('Frame map:')
for (let r = 0; r < ROWS; r++) {
  let line = ''
  for (let c = 0; c < COLS; c++) {
    const gt = ground[r*COLS+c]
    if (gt === V) { line += '   · '; continue }
    if (gt === F) { line += '   F '; continue }
    const frames = getFrames(ground, COLS, ROWS, r, c)
    for (const f of frames) placeTile(out, c, r, f)
    line += `#${String(frames[0]).padStart(3)}${frames.length>1?'+':' '}`
  }
  console.log(line)
}

// Scale 3x
const S = 3, sW = COLS*TILE*S, sH = ROWS*TILE*S
const scaled = new PNG({ width: sW, height: sH })
for (let y = 0; y < ROWS*TILE; y++)
  for (let x = 0; x < COLS*TILE; x++) {
    const si = (y*COLS*TILE+x)*4
    for (let sy = 0; sy < S; sy++)
      for (let sx = 0; sx < S; sx++) {
        const di = ((y*S+sy)*sW+(x*S+sx))*4
        scaled.data[di]=out.data[si]; scaled.data[di+1]=out.data[si+1]
        scaled.data[di+2]=out.data[si+2]; scaled.data[di+3]=out.data[si+3]
      }
  }

fs.writeFileSync('test_colored_walls.png', PNG.sync.write(scaled))
console.log(`\nWrote test_colored_walls.png (${sW}x${sH})`)
