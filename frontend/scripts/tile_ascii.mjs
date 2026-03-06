import fs from 'fs'
import { PNG } from 'pngjs'

const src = fs.readFileSync('../public/assets/office/tiles/room_builder.png')
const png = PNG.sync.read(src)
const { width, data } = png

const TILE = 16
const COLS = width / TILE

function printTile(frameIdx) {
  const tileCol = frameIdx % COLS
  const tileRow = Math.floor(frameIdx / COLS)
  const ox = tileCol * TILE
  const oy = tileRow * TILE

  console.log(`\n#${frameIdx}:`)
  for (let y = 0; y < TILE; y++) {
    let line = ''
    for (let x = 0; x < TILE; x++) {
      const idx = ((oy + y) * width + (ox + x)) * 4
      const r = data[idx], g = data[idx+1], b = data[idx+2], a = data[idx+3]
      if (a < 30) {
        line += '·'  // transparent
      } else {
        const brightness = (r + g + b) / 3
        if (brightness < 80) line += '█'       // very dark (wall line)
        else if (brightness < 140) line += '▓' // dark
        else if (brightness < 190) line += '▒' // medium
        else line += '░'                        // light
      }
    }
    console.log('  ' + line)
  }
}

// Colored wall tiles: marble (row 5), gray (row 6)
const tiles = []
// Row 5: WALL_MARBLE (frames 80-89, cols 0-9)
for (let i = 80; i <= 89; i++) tiles.push(i)
// Row 6: WALL_GRAY (frames 96-105, cols 0-9)
for (let i = 96; i <= 105; i++) tiles.push(i)
// Also compare with structural inner 9-grid
tiles.push(23, 24, 25, 39, 41, 49, 50, 55, 56, 57)

for (const t of tiles) {
  printTile(t)
}
