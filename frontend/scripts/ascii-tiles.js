import fs from 'fs';
import { PNG } from 'pngjs';

const ROWS = 4;
const COLS = 16;

try {
    const buffer = fs.readFileSync('./public/assets/office/tiles/room_builder.png');
    const png = PNG.sync.read(buffer);

    let output = '=== Structural Walls (Tiles 0-63) ===\n\n';
    for (let r = 0; r < ROWS; r++) {
        let header = '';
        for (let c = 0; c < COLS; c++) {
            header += `  ${String(r * COLS + c).padStart(2, '0')}  |`;
        }
        output += header + '\n';

        for (let tileY = 0; tileY < 16; tileY += 2) {
            let line = '';
            for (let c = 0; c < COLS; c++) {
                for (let tileX = 0; tileX < 16; tileX += 2) {
                    const pxX = c * 16 + tileX;
                    const pxY = r * 16 + tileY;
                    const idx = (png.width * pxY + pxX) << 2;
                    const alpha = png.data[idx + 3];
                    const rgb = png.data[idx] + png.data[idx+1] + png.data[idx+2];
                    
                    if (alpha < 128) {
                        line += ' '; // 透明
                    } else if (rgb < 150) {
                        line += '#'; // 暗色邊緣/陰影
                    } else if (rgb < 450) {
                        line += '+'; // 牆體顏色
                    } else {
                        line += '.'; // 亮色/頂部收邊
                    }
                }
                line += '|';
            }
            output += line + '\n';
        }
        output += '-'.repeat(COLS * 7) + '\n';
    }
    console.log(output);
} catch (err) {
    console.error(err);
}
