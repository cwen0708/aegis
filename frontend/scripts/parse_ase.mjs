import { readFileSync } from 'fs'
import Aseprite from 'ase-parser'

const buf = readFileSync('../../examples/6_Office_Designs/Office_Design_2.aseprite')
const ase = new Aseprite(buf, 'Office_Design_2.aseprite')
ase.parse()

console.log('=== Aseprite File Info ===')
console.log(`Size: ${ase.width} x ${ase.height}`)
console.log(`Frames: ${ase.numFrames}`)
console.log(`Layers: ${ase.layers.length}`)
console.log()

for (const layer of ase.layers) {
  console.log(`Layer: "${layer.name}" (type: ${layer.type}, visible: ${!(layer.flags & 2)})`)
}

console.log()
console.log('=== Tilesets ===')
if (ase.tilesets && ase.tilesets.length > 0) {
  for (const ts of ase.tilesets) {
    console.log(`Tileset: id=${ts.id}, name="${ts.name}", tileW=${ts.tileW}, tileH=${ts.tileH}, count=${ts.tileCount}`)
  }
} else {
  console.log('No tilesets found')
}

// Check for tilemap data in cels
console.log()
console.log('=== Cels (frame 0) ===')
for (const frame of ase.frames) {
  for (const cel of frame.cels) {
    const layer = ase.layers[cel.layerIndex]
    console.log(`  Cel: layer="${layer?.name}", type=${cel.celType}, pos=(${cel.xpos},${cel.ypos}), size=${cel.w}x${cel.h}`)
    if (cel.celType === 3) {
      // Tilemap cel
      console.log(`    Tilemap: tilesetId=${cel.tilesetId || 'N/A'}`)
      if (cel.tilemapData) {
        console.log(`    Tilemap data length: ${cel.tilemapData.length}`)
        // Print first few tile IDs
        const preview = Array.from(cel.tilemapData.slice(0, 40))
        console.log(`    First bytes: ${preview.join(', ')}`)
      }
    }
  }
  break // only first frame
}
