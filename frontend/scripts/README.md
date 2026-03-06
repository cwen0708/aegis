# Tile / Auto-Tile Dev Scripts

Development-only scripts for analyzing and testing the `room_builder.png` spritesheet.
Run from this directory: `cd frontend/scripts && node <script>.mjs`

## Scripts

| Script | Purpose | Output |
|--------|---------|--------|
| `test_autotile.mjs` | Renders structural auto-tile for a test room layout | `../public/test_autotile.png` |
| `test_colored_walls.mjs` | Renders colored (marble) wall auto-tile for a two-room layout | `../public/test_colored_walls.png` |
| `tile_ascii.mjs` | Prints any tile frame as ASCII art to console | stdout |
| `analyze_walls.mjs` | Analyzes edge/corner patterns of structural wall tiles (rows 0-3) | stdout |
| `parse_ase.mjs` | Parses Aseprite `.aseprite` files from examples folder | stdout |

## Dependencies

All scripts use `pngjs` (already in devDependencies).
`parse_ase.mjs` additionally requires `ase-parser`.
