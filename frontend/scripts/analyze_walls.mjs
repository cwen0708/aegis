import fs from 'fs'
import { PNG } from 'pngjs'

const src = fs.readFileSync('../public/assets/office/tiles/room_builder.png')
const png = PNG.sync.read(src)
const { width, height, data } = png // data is RGBA buffer

const TILE = 16
const COLS = width / TILE  // 16
const ROWS = height / TILE // 14

// Analyze rows 0-3 (structural walls), 64 tiles
// For each tile, check which edges and corners have non-transparent dark pixels

function analyzeTile(frameIdx) {
  const tileCol = frameIdx % COLS
  const tileRow = Math.floor(frameIdx / COLS)
  const ox = tileCol * TILE
  const oy = tileRow * TILE

  // Get pixel at (x, y) relative to tile
  function px(x, y) {
    const idx = ((oy + y) * width + (ox + x)) * 4
    return { r: data[idx], g: data[idx+1], b: data[idx+2], a: data[idx+3] }
  }

  // Check if pixel is "wall" (dark, non-transparent)
  function isWallPx(x, y) {
    const p = px(x, y)
    if (p.a < 128) return false // transparent
    const brightness = (p.r + p.g + p.b) / 3
    return brightness < 140 // dark pixel = wall
  }

  // Check regions (3px border on each edge)
  const edges = { N: 0, S: 0, E: 0, W: 0 }
  const corners = { NW: 0, NE: 0, SW: 0, SE: 0 }
  const center = { count: 0 }
  let totalWall = 0
  let totalTransparent = 0

  for (let y = 0; y < TILE; y++) {
    for (let x = 0; x < TILE; x++) {
      const p = px(x, y)
      if (p.a < 128) { totalTransparent++; continue }

      const brightness = (p.r + p.g + p.b) / 3
      const isDark = brightness < 140
      if (!isDark) continue

      totalWall++

      // Edge detection (3px borders)
      if (y < 4) edges.N++
      if (y >= 12) edges.S++
      if (x < 4) edges.W++
      if (x >= 12) edges.E++

      // Corner detection (4x4 corners)
      if (x < 5 && y < 5) corners.NW++
      if (x >= 11 && y < 5) corners.NE++
      if (x < 5 && y >= 11) corners.SW++
      if (x >= 11 && y >= 11) corners.SE++

      // Center
      if (x >= 4 && x < 12 && y >= 4 && y < 12) center.count++
    }
  }

  // Determine edge presence (threshold: at least 8 dark pixels in the border region)
  const threshold = 6
  const hasN = edges.N >= threshold
  const hasS = edges.S >= threshold
  const hasE = edges.E >= threshold
  const hasW = edges.W >= threshold

  const cornerThresh = 4
  const hasNW = corners.NW >= cornerThresh
  const hasNE = corners.NE >= cornerThresh
  const hasSW = corners.SW >= cornerThresh
  const hasSE = corners.SE >= cornerThresh

  // Check transparency
  const isTransparent = totalTransparent > 200 // mostly transparent
  const isEmpty = totalWall < 5

  return {
    frame: frameIdx,
    totalWall,
    totalTransparent,
    isEmpty,
    edges: { N: hasN, S: hasS, E: hasE, W: hasW },
    corners: { NW: hasNW, NE: hasNE, SW: hasSW, SE: hasSE },
    center: center.count,
    edgeCounts: edges,
    cornerCounts: corners,
  }
}

// Analyze rows 0-3 (frames 0-63)
console.log('=== Structural Wall Tiles Analysis (Rows 0-3) ===\n')

for (let row = 0; row < 4; row++) {
  console.log(`--- Row ${row} (frames ${row*16}-${row*16+15}) ---`)
  for (let col = 0; col < 16; col++) {
    const idx = row * 16 + col
    const a = analyzeTile(idx)

    if (a.isEmpty) {
      console.log(`  #${String(idx).padStart(3)}: [empty]`)
      continue
    }

    const eStr = [
      a.edges.N ? 'N' : '.',
      a.edges.E ? 'E' : '.',
      a.edges.S ? 'S' : '.',
      a.edges.W ? 'W' : '.',
    ].join('')

    const cStr = [
      a.corners.NW ? 'NW' : '..',
      a.corners.NE ? 'NE' : '..',
      a.corners.SW ? 'SW' : '..',
      a.corners.SE ? 'SE' : '..',
    ].join(' ')

    // Describe the shape
    let shape = ''
    if (a.edges.N && a.edges.S && a.edges.E && a.edges.W) shape = '▮ filled/cross'
    else if (a.edges.N && a.edges.S && !a.edges.E && !a.edges.W) shape = '│ vertical'
    else if (!a.edges.N && !a.edges.S && a.edges.E && a.edges.W) shape = '─ horizontal'
    else if (a.edges.N && a.edges.S) shape = '│+ vertical+'
    else if (a.edges.E && a.edges.W) shape = '─+ horizontal+'
    else if (a.edges.N && a.edges.E) shape = '└ corner NE'
    else if (a.edges.N && a.edges.W) shape = '┘ corner NW'
    else if (a.edges.S && a.edges.E) shape = '┌ corner SE'
    else if (a.edges.S && a.edges.W) shape = '┐ corner SW'
    else if (a.edges.N) shape = '╵ cap N'
    else if (a.edges.S) shape = '╷ cap S'
    else if (a.edges.E) shape = '╶ cap E'
    else if (a.edges.W) shape = '╴ cap W'
    else shape = '? other'

    console.log(`  #${String(idx).padStart(3)}: edges=${eStr}  corners=${cStr}  center=${a.center}  wall=${a.totalWall}  trans=${a.totalTransparent}  → ${shape}`)
  }
  console.log()
}
