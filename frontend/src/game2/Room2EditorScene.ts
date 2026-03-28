/**
 * Room2EditorScene — Tiled 地圖視覺化編輯器
 * Phase 1: Ground layer 繪製 + 網格 + 攝影機
 */
import Phaser from 'phaser'
import {
  ASSET_BASE, TILE_SIZE,
  preloadTilesets, buildTilesetInfos, renderObjectLayer,
  type TilesetInfo,
} from './tilesetRegistry'

export type EditorTool = 'ground' | 'eraser' | 'select'

export default class Room2EditorScene extends Phaser.Scene {
  private map!: Phaser.Tilemaps.Tilemap
  private tilesetInfos: TilesetInfo[] = []
  private groundLayer!: Phaser.Tilemaps.TilemapLayer

  // Editor state
  private currentTool: EditorTool = 'ground'
  private selectedGid = 1  // 預設選第一個 FloorAndGround tile
  private gridGraphics!: Phaser.GameObjects.Graphics
  private hoverGraphics!: Phaser.GameObjects.Graphics

  // Camera
  private isPinching = false
  private pinchStartDist = 0
  private pinchStartZoom = 1

  constructor() {
    super('room2-editor')
  }

  preload() {
    this.load.tilemapTiledJSON('tilemap2_edit', `${ASSET_BASE}/map.json`)
    preloadTilesets(this)
  }

  create() {
    this.map = this.make.tilemap({ key: 'tilemap2_edit' })
    this.tilesetInfos = buildTilesetInfos(this.map)

    // 註冊 tilesets
    const floorTileset = this.map.addTilesetImage('FloorAndGround', 'tiles_floor')!
    const officeTileset = this.map.addTilesetImage('Modern_Office_Black_Shadow', 'tiles_office')!
    const genericTileset = this.map.addTilesetImage('Generic', 'tiles_generic')!
    const basementTileset = this.map.addTilesetImage('Basement', 'tiles_basement')!
    const allTilesets = [floorTileset, officeTileset, genericTileset, basementTileset]

    // Ground tile layer
    const layer = this.map.createLayer('Ground', allTilesets)
    if (layer) {
      this.groundLayer = layer
    }

    // 渲染所有 object layers（唯讀顯示）
    for (const name of ['Chair', 'Basement']) {
      renderObjectLayer(this, this.map, this.tilesetInfos, name, false)
    }
    for (const name of ['Wall', 'Objects', 'ObjectsOnCollide', 'GenericObjects', 'GenericObjectsOnCollide', 'Computer', 'Whiteboard', 'VendingMachine']) {
      renderObjectLayer(this, this.map, this.tilesetInfos, name, true)
    }

    // 網格
    this.gridGraphics = this.add.graphics().setDepth(900)
    this.drawGrid()

    // Hover 預覽
    this.hoverGraphics = this.add.graphics().setDepth(901)

    // 攝影機
    const mapWidth = this.map.widthInPixels
    const mapHeight = this.map.heightInPixels
    this.cameras.main.setBounds(0, 0, mapWidth, mapHeight)
    this.cameras.main.setZoom(1.5)
    this.cameras.main.centerOn(mapWidth / 2, mapHeight / 2)
    this.cameras.main.setRoundPixels(true)

    this.setupInput()

    // 通知 Vue 場景就緒
    this.game.events.emit('editor-ready')
  }

  // ── Input ──────────────────────────────────────────────────────

  private setupInput() {
    // 拖曳平移（左鍵/中鍵）
    this.input.on('pointermove', (pointer: Phaser.Input.Pointer) => {
      // pinch zoom
      if (this.input.pointer1.isDown && this.input.pointer2.isDown) {
        this.handlePinchMove()
        return
      }
      if (this.isPinching) return

      // 拖曳
      if (pointer.isDown && !pointer.rightButtonDown()) {
        this.cameras.main.scrollX -= (pointer.x - pointer.prevPosition.x) / this.cameras.main.zoom
        this.cameras.main.scrollY -= (pointer.y - pointer.prevPosition.y) / this.cameras.main.zoom
      }

      // hover 預覽
      this.updateHover(pointer)
    })

    this.input.on('pointerup', () => {
      if (!this.input.pointer1.isDown || !this.input.pointer2.isDown) {
        this.isPinching = false
      }
    })

    // 多點觸控
    this.input.addPointer(1)

    // 滾輪縮放
    this.input.on('wheel', (_p: unknown, _g: unknown, _dx: number, _dy: number, dz: number) => {
      this.applyZoom(this.cameras.main.zoom - dz * 0.001)
    })

    // 右鍵繪製
    this.input.on('pointerdown', (pointer: Phaser.Input.Pointer) => {
      if (pointer.rightButtonDown()) {
        this.handlePaint(pointer)
      }
    })

    // 右鍵拖曳繪製
    this.input.on('pointermove', (pointer: Phaser.Input.Pointer) => {
      if (pointer.rightButtonDown() && !this.isPinching) {
        this.handlePaint(pointer)
      }
    })

    // 停用右鍵選單
    this.input.mouse?.disableContextMenu()
  }

  private applyZoom(raw: number) {
    const snapped = Math.round(raw * 2) / 2
    this.cameras.main.setZoom(Phaser.Math.Clamp(snapped, 0.5, 4))
  }

  private handlePinchMove() {
    const p1 = this.input.pointer1
    const p2 = this.input.pointer2
    const dist = Phaser.Math.Distance.Between(p1.x, p1.y, p2.x, p2.y)

    if (!this.isPinching) {
      this.isPinching = true
      this.pinchStartDist = dist
      this.pinchStartZoom = this.cameras.main.zoom
    } else {
      this.applyZoom(this.pinchStartZoom * (dist / this.pinchStartDist))
    }
  }

  // ── Grid ───────────────────────────────────────────────────────

  private drawGrid() {
    const g = this.gridGraphics
    g.clear()
    g.lineStyle(1, 0xffffff, 0.15)

    const w = this.map.widthInPixels
    const h = this.map.heightInPixels

    for (let x = 0; x <= w; x += TILE_SIZE) {
      g.lineBetween(x, 0, x, h)
    }
    for (let y = 0; y <= h; y += TILE_SIZE) {
      g.lineBetween(0, y, w, y)
    }
  }

  // ── Hover preview ──────────────────────────────────────────────

  private updateHover(pointer: Phaser.Input.Pointer) {
    this.hoverGraphics.clear()
    if (this.currentTool !== 'ground' && this.currentTool !== 'eraser') return

    const worldPoint = this.cameras.main.getWorldPoint(pointer.x, pointer.y)
    const col = Math.floor(worldPoint.x / TILE_SIZE)
    const row = Math.floor(worldPoint.y / TILE_SIZE)

    if (col < 0 || col >= this.map.width || row < 0 || row >= this.map.height) return

    const color = this.currentTool === 'eraser' ? 0xff4444 : 0x44ff44
    this.hoverGraphics.fillStyle(color, 0.3)
    this.hoverGraphics.fillRect(col * TILE_SIZE, row * TILE_SIZE, TILE_SIZE, TILE_SIZE)
  }

  // ── Paint ──────────────────────────────────────────────────────

  private handlePaint(pointer: Phaser.Input.Pointer) {
    if (this.currentTool !== 'ground' && this.currentTool !== 'eraser') return
    if (!this.groundLayer) return

    const worldPoint = this.cameras.main.getWorldPoint(pointer.x, pointer.y)
    const col = Math.floor(worldPoint.x / TILE_SIZE)
    const row = Math.floor(worldPoint.y / TILE_SIZE)

    if (col < 0 || col >= this.map.width || row < 0 || row >= this.map.height) return

    if (this.currentTool === 'eraser') {
      this.map.putTileAt(-1, col, row, true, 'Ground')
    } else {
      this.map.putTileAt(this.selectedGid, col, row, true, 'Ground')
    }
  }

  // ── Public API (Vue → Phaser) ──────────────────────────────────

  setTool(tool: EditorTool) {
    this.currentTool = tool
  }

  setSelectedGid(gid: number) {
    this.selectedGid = gid
  }

  getMapData(): object {
    // Phase 4 實作完整 export
    return this.map.tilesets
  }
}
