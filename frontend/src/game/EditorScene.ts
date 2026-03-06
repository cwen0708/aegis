import Phaser from 'phaser'
import {
  GroundType, isWall,
  type OfficeLayout, type FurnitureItem, type EditorLayer,
} from './types'
import { GROUND_COLORS } from './groundData'
import { FURNITURE_ASSETS } from './furnitureData'
import {
  setGround,
  nextFurnitureId, nextPropsId, autoDetectWorkstations,
} from './layoutManager'
import {
  TILE, ZOOM, preloadOfficeAssets,
  renderFloor as sharedRenderFloor,
  renderWalls as sharedRenderWalls,
  renderItemImage,
} from './renderUtils'


export class EditorScene extends Phaser.Scene {
  private layout!: OfficeLayout
  private activeLayer: EditorLayer = 'ground'
  private selectedTool: string | null = null
  private isDeleteMode = false
  private layerVisibility: Record<EditorLayer, boolean> = { ground: true, wall: true, furniture: true, props: true, slots: true }
  private slotMarkers: Phaser.GameObjects.Graphics[] = []
  private slotDirection: 'down' | 'left' | 'right' | 'up' = 'up'

  // Camera drag
  private isDragging = false
  private didDrag = false
  private dragStartX = 0
  private dragStartY = 0
  private camStartX = 0
  private camStartY = 0
  private pointerDownButton = -1

  // Hover preview
  private hoverPreview: Phaser.GameObjects.Image | Phaser.GameObjects.Graphics | null = null
  private hoverOutline: Phaser.GameObjects.Graphics | null = null
  private hoverCol = -1
  private hoverRow = -1

  // Render groups
  private floorObjects: Phaser.GameObjects.GameObject[] = []
  private wallObjects: Phaser.GameObjects.GameObject[] = []
  private furnitureImages: Map<string, Phaser.GameObjects.Image> = new Map()
  private propsImages: Map<string, Phaser.GameObjects.Image> = new Map()
  private gridGraphics!: Phaser.GameObjects.Graphics

  constructor() {
    super({ key: 'EditorScene' })
  }

  init(data: { layout: OfficeLayout }) {
    this.layout = JSON.parse(JSON.stringify(data.layout))
  }

  preload() {
    preloadOfficeAssets(this)
  }

  create() {
    const worldW = this.layout.cols * TILE * ZOOM
    const worldH = this.layout.rows * TILE * ZOOM
    this.cameras.main.setBounds(0, 0, worldW, worldH)
    this.cameras.main.centerOn(worldW / 2, worldH / 2)

    this.gridGraphics = this.add.graphics().setDepth(1000)

    this.renderAll()
    this.renderGrid()
    this.setupInput()

    // Refresh scale manager so pointer offset matches canvas position in DOM
    this.scale.refresh()
    this.time.delayedCall(100, () => this.scale.refresh())

    this.scale.on('resize', () => {
      this.cameras.main.setBounds(0, 0, worldW, worldH)
    })

    this.events.emit('editor-ready')
  }

  // ── Public API (called from Vue) ──────────────────────────────
  setActiveLayer(layer: EditorLayer) {
    this.activeLayer = layer
    this.clearHoverPreview()
  }

  setSelectedTool(tool: string | null) {
    this.selectedTool = tool
    this.isDeleteMode = false
    this.clearHoverPreview()
  }

  setDeleteMode(on: boolean) {
    this.isDeleteMode = on
    this.selectedTool = null
    this.clearHoverPreview()
  }

  setSlotDirection(dir: 'down' | 'left' | 'right' | 'up') {
    this.slotDirection = dir
    this.clearHoverPreview()  // Redraw with new direction on next move
  }

  setLayerVisibility(layer: EditorLayer, visible: boolean) {
    this.layerVisibility[layer] = visible
    this.renderAll()
  }

  getLayout(): OfficeLayout {
    const layout: OfficeLayout = JSON.parse(JSON.stringify(this.layout))
    layout.workstations = autoDetectWorkstations(layout)
    return layout
  }

  // ── Input ─────────────────────────────────────────────────────
  private setupInput() {
    this.game.canvas.addEventListener('contextmenu', (e) => e.preventDefault())

    this.input.on('pointerdown', (p: Phaser.Input.Pointer) => {
      this.pointerDownButton = p.button
      this.dragStartX = p.x
      this.dragStartY = p.y
      this.camStartX = this.cameras.main.scrollX
      this.camStartY = this.cameras.main.scrollY
      this.isDragging = false
      this.didDrag = false
    })

    this.input.on('pointermove', (p: Phaser.Input.Pointer) => {
      if (!p.isDown) {
        this.updateHoverPreview(p)
        return
      }

      const dx = p.x - this.dragStartX
      const dy = p.y - this.dragStartY

      // Left or middle button — pan
      if (this.pointerDownButton === 0 || this.pointerDownButton === 1) {
        this.isDragging = true
        this.didDrag = true
        this.cameras.main.scrollX = this.camStartX - dx
        this.cameras.main.scrollY = this.camStartY - dy
        return
      }

      // Right button + ground/wall/slots — paint while dragging
      if (this.pointerDownButton === 2 && (this.selectedTool || this.activeLayer === 'wall' || this.activeLayer === 'slots') &&
          (this.activeLayer === 'ground' || this.activeLayer === 'wall' || this.activeLayer === 'slots')) {
        this.handlePlace(p)
      }

      this.updateHoverPreview(p)
    })

    this.input.on('pointerup', (p: Phaser.Input.Pointer) => {
      // Only act on right click
      if (this.pointerDownButton === 2 && !this.didDrag) {
        if (this.isDeleteMode) {
          const col = Math.floor(p.worldX / (TILE * ZOOM))
          const row = Math.floor(p.worldY / (TILE * ZOOM))
          this.handleDelete(col, row)
        } else if (this.selectedTool || this.activeLayer === 'wall' || this.activeLayer === 'slots') {
          this.handlePlace(p)
        }
      }
      this.isDragging = false
      this.didDrag = false
      this.pointerDownButton = -1
    })
  }

  private handlePlace(p: Phaser.Input.Pointer) {
    const worldX = p.worldX
    const worldY = p.worldY
    let col = Math.floor(worldX / (TILE * ZOOM))
    let row = Math.floor(worldY / (TILE * ZOOM))

    if (col < 0 || col >= this.layout.cols || row < 0 || row >= this.layout.rows) return

    if (this.activeLayer === 'ground' && this.selectedTool !== null) {
      const groundType = parseInt(this.selectedTool) as GroundType
      setGround(this.layout, row, col, groundType)
      this.renderFloor()
      this.renderWalls()
      return
    }

    if (this.activeLayer === 'wall') {
      const wallType = this.selectedTool ? parseInt(this.selectedTool) as GroundType : GroundType.WALL_MARBLE
      setGround(this.layout, row, col, wallType)
      this.renderFloor()
      this.renderWalls()
      return
    }

    if ((this.activeLayer === 'furniture' || this.activeLayer === 'props') && this.selectedTool) {
      // Center placement: offset by half sprite size
      const offset = this.getSpriteOffset(this.selectedTool)
      col -= offset.col
      row -= offset.row

      // Check if there's already an item at this position — if so, remove it first
      const items = this.activeLayer === 'furniture' ? this.layout.furniture : this.layout.props
      const existing = items.findIndex(f => f.col === col && f.row === row)
      if (existing >= 0) {
        items.splice(existing, 1)
      }

      const id = this.activeLayer === 'furniture'
        ? nextFurnitureId(this.layout)
        : nextPropsId(this.layout)
      items.push({ id, type: this.selectedTool, col, row })

      if (this.activeLayer === 'furniture') {
        this.renderFurniture()
      } else {
        this.renderProps()
      }
      return
    }

    // Slots layer — add slot at clicked position
    if (this.activeLayer === 'slots') {
      if (!this.layout.slots) this.layout.slots = []
      // Check if slot already exists at this position
      const existingIdx = this.layout.slots.findIndex(s => s.col === col && s.row === row)
      if (existingIdx >= 0) {
        // Remove existing slot
        this.layout.slots.splice(existingIdx, 1)
      } else {
        // Add new slot with current direction
        this.layout.slots.push({ col, row, dir: this.slotDirection })
      }
      this.renderSlots()
      return
    }
  }

  private handleDelete(col: number, row: number) {
    if (col < 0 || col >= this.layout.cols || row < 0 || row >= this.layout.rows) return

    if (this.activeLayer === 'ground' || this.activeLayer === 'wall') {
      setGround(this.layout, row, col, GroundType.FLOOR)
      this.renderFloor()
      this.renderWalls()
      return
    }

    if (this.activeLayer === 'furniture') {
      const idx = this.layout.furniture.findIndex(f =>
        col >= f.col && col < f.col + 2 && row >= f.row && row < f.row + 3
      )
      if (idx >= 0) {
        // Also remove workstation reference
        const removedId = this.layout.furniture[idx].id
        this.layout.workstations = this.layout.workstations.filter(
          ws => ws.deskId !== removedId && ws.chairId !== removedId
        )
        this.layout.furniture.splice(idx, 1)
        this.renderFurniture()
      }
    } else if (this.activeLayer === 'props') {
      const idx = this.layout.props.findIndex(f =>
        col >= f.col && col < f.col + 2 && row >= f.row && row < f.row + 3
      )
      if (idx >= 0) {
        const removedId = this.layout.props[idx].id
        this.layout.workstations.forEach(ws => {
          if (ws.monitorId === removedId) ws.monitorId = undefined
        })
        this.layout.props.splice(idx, 1)
        this.renderProps()
      }
    } else if (this.activeLayer === 'slots') {
      if (!this.layout.slots) return
      const idx = this.layout.slots.findIndex(s => s.col === col && s.row === row)
      if (idx >= 0) {
        this.layout.slots.splice(idx, 1)
        this.renderSlots()
      }
    }
  }

  // ── Hover Preview ─────────────────────────────────────────────
  private updateHoverPreview(p: Phaser.Input.Pointer) {
    const col = Math.floor(p.worldX / (TILE * ZOOM))
    const row = Math.floor(p.worldY / (TILE * ZOOM))

    if (col === this.hoverCol && row === this.hoverRow) return
    this.hoverCol = col
    this.hoverRow = row

    this.clearHoverPreview()

    if (col < 0 || col >= this.layout.cols || row < 0 || row >= this.layout.rows) return
    if (!this.selectedTool && this.activeLayer !== 'wall' && this.activeLayer !== 'slots' && !this.isDeleteMode) return

    const x = col * TILE * ZOOM
    const y = row * TILE * ZOOM
    const ts = TILE * ZOOM

    // Delete mode: highlight item under cursor
    if (this.isDeleteMode) {
      const g = this.add.graphics().setDepth(999)

      if (this.activeLayer === 'furniture' || this.activeLayer === 'props') {
        const items = this.activeLayer === 'furniture' ? this.layout.furniture : this.layout.props
        const item = items.find(f =>
          col >= f.col && col < f.col + 2 && row >= f.row && row < f.row + 3
        )
        if (item) {
          const filename = FURNITURE_ASSETS[item.type]
          const texKey = `furn_${filename}`
          if (this.textures.exists(texKey)) {
            const tex = this.textures.get(texKey).get()
            const tilesW = Math.ceil(tex.width / TILE)
            const tilesH = Math.ceil(tex.height / TILE)
            const px = item.col * ts
            const py = item.row * ts
            g.fillStyle(0xff4444, 0.3)
            g.fillRect(px, py, tilesW * ts, tilesH * ts)
            g.lineStyle(3, 0xff4444, 0.9)
            g.strokeRect(px, py, tilesW * ts, tilesH * ts)
          }
        } else {
          // No item here, show X cursor
          g.lineStyle(2, 0xff4444, 0.5)
          g.strokeRect(x, y, ts, ts)
        }
      } else if (this.activeLayer === 'slots') {
        const slot = this.layout.slots?.find(s => s.col === col && s.row === row)
        if (slot) {
          g.fillStyle(0xff4444, 0.4)
          g.fillCircle(x + ts / 2, y + ts / 2, ts / 3)
          g.lineStyle(3, 0xff4444, 0.9)
          g.strokeCircle(x + ts / 2, y + ts / 2, ts / 3)
        } else {
          g.lineStyle(2, 0xff4444, 0.5)
          g.strokeRect(x, y, ts, ts)
        }
      } else {
        // ground/wall: just highlight the cell
        g.fillStyle(0xff4444, 0.3)
        g.fillRect(x, y, ts, ts)
        g.lineStyle(2, 0xff4444, 0.8)
        g.strokeRect(x, y, ts, ts)
      }

      this.hoverPreview = g
      return
    }

    if (this.activeLayer === 'ground') {
      const gt = parseInt(this.selectedTool!) as GroundType
      const g = this.add.graphics().setDepth(999)
      g.fillStyle(GROUND_COLORS[gt], 0.5)
      g.fillRect(x, y, TILE * ZOOM, TILE * ZOOM)
      this.hoverPreview = g
    } else if (this.activeLayer === 'wall') {
      const wallType = this.selectedTool ? parseInt(this.selectedTool) as GroundType : GroundType.WALL_MARBLE
      const g = this.add.graphics().setDepth(999)
      g.fillStyle(GROUND_COLORS[wallType] ?? GROUND_COLORS[GroundType.WALL], 0.5)
      g.fillRect(x, y, TILE * ZOOM, TILE * ZOOM)
      this.hoverPreview = g
    } else if (this.activeLayer === 'slots') {
      const cx = x + ts / 2
      const cy = y + ts / 2
      const g = this.add.graphics().setDepth(999)
      // Check if slot already exists here
      const exists = this.layout.slots?.some(s => s.col === col && s.row === row)
      const color = exists ? 0xff4444 : 0x00ff88
      g.fillStyle(color, 0.4)
      g.fillCircle(cx, cy, ts / 3)
      g.lineStyle(2, color, 0.8)
      g.strokeCircle(cx, cy, ts / 3)

      // Show direction arrow on hover
      if (!exists) {
        g.lineStyle(3, 0xffffff, 0.7)
        const arrowLen = ts / 4
        const arrowHead = 6
        let dx = 0, dy = 0
        if (this.slotDirection === 'up') dy = -1
        else if (this.slotDirection === 'down') dy = 1
        else if (this.slotDirection === 'left') dx = -1
        else if (this.slotDirection === 'right') dx = 1
        const ax = cx + dx * arrowLen
        const ay = cy + dy * arrowLen
        g.lineBetween(cx, cy, ax, ay)
        if (this.slotDirection === 'up') {
          g.lineBetween(ax, ay, ax - arrowHead, ay + arrowHead)
          g.lineBetween(ax, ay, ax + arrowHead, ay + arrowHead)
        } else if (this.slotDirection === 'down') {
          g.lineBetween(ax, ay, ax - arrowHead, ay - arrowHead)
          g.lineBetween(ax, ay, ax + arrowHead, ay - arrowHead)
        } else if (this.slotDirection === 'left') {
          g.lineBetween(ax, ay, ax + arrowHead, ay - arrowHead)
          g.lineBetween(ax, ay, ax + arrowHead, ay + arrowHead)
        } else if (this.slotDirection === 'right') {
          g.lineBetween(ax, ay, ax - arrowHead, ay - arrowHead)
          g.lineBetween(ax, ay, ax - arrowHead, ay + arrowHead)
        }
      }
      this.hoverPreview = g
    } else if (this.activeLayer === 'furniture' || this.activeLayer === 'props') {
      const filename = FURNITURE_ASSETS[this.selectedTool!]
      if (!filename) return
      const texKey = `furn_${filename}`
      if (!this.textures.exists(texKey)) return

      // Center preview on cursor by offsetting by half sprite size
      const offset = this.getSpriteOffset(this.selectedTool)
      const placedCol = col - offset.col
      const placedRow = row - offset.row
      const px = placedCol * TILE * ZOOM
      const py = placedRow * TILE * ZOOM

      const tex = this.textures.get(texKey).get()
      const tilesW = Math.ceil(tex.width / TILE)
      const tilesH = Math.ceil(tex.height / TILE)

      // Draw grid highlight; red on anchor cell if occupied
      const items = this.activeLayer === 'furniture' ? this.layout.furniture : this.layout.props
      const occupied = items.some(f => f.col === placedCol && f.row === placedRow)
      const color = occupied ? 0xff4444 : 0x00ccff
      const fillAlpha = occupied ? 0.25 : 0.15

      const outline = this.add.graphics().setDepth(998)
      outline.fillStyle(color, fillAlpha)
      outline.fillRect(px, py, tilesW * ts, tilesH * ts)
      outline.lineStyle(2, color, 0.7)
      outline.strokeRect(px, py, tilesW * ts, tilesH * ts)
      for (let gc = 1; gc < tilesW; gc++) {
        outline.lineBetween(px + gc * ts, py, px + gc * ts, py + tilesH * ts)
      }
      for (let gr = 1; gr < tilesH; gr++) {
        outline.lineBetween(px, py + gr * ts, px + tilesW * ts, py + gr * ts)
      }
      this.hoverOutline = outline

      const img = this.add.image(px, py, texKey)
        .setOrigin(0, 0)
        .setScale(ZOOM)
        .setAlpha(0.5)
        .setDepth(999)
      this.hoverPreview = img
    }
  }

  private clearHoverPreview() {
    this.hoverPreview?.destroy()
    this.hoverPreview = null
    this.hoverOutline?.destroy()
    this.hoverOutline = null
    this.hoverCol = -1
    this.hoverRow = -1
  }

  // ── Sprite offset (center on cursor) ─────────────────────────
  private getSpriteOffset(tool: string): { col: number; row: number } {
    const filename = FURNITURE_ASSETS[tool]
    if (!filename) return { col: 0, row: 0 }
    const texKey = `furn_${filename}`
    if (!this.textures.exists(texKey)) return { col: 0, row: 0 }
    const tex = this.textures.get(texKey).get()
    // Anchor at bottom-left: no horizontal offset, vertical = sprite height - 1
    return {
      col: 0,
      row: Math.ceil(tex.height / TILE) - 1,
    }
  }

  // ── Rendering ─────────────────────────────────────────────────
  private renderAll() {
    this.renderFloor()
    this.renderWalls()
    this.renderFurniture()
    this.renderProps()
    this.renderSlots()
  }

  private renderFloor() {
    this.floorObjects.forEach(o => o.destroy())
    this.floorObjects = []
    if (!this.layerVisibility.ground) return
    this.floorObjects = sharedRenderFloor(this, this.layout)
  }

  private renderWalls() {
    this.wallObjects.forEach(g => g.destroy())
    this.wallObjects = []
    if (!this.layerVisibility.wall) return
    this.wallObjects = sharedRenderWalls(this, this.layout)
  }

  private renderFurniture() {
    this.furnitureImages.forEach(img => img.destroy())
    this.furnitureImages.clear()
    if (!this.layerVisibility.furniture) return

    const sorted = [...this.layout.furniture].sort((a, b) => a.row - b.row)
    for (const f of sorted) {
      const img = this.renderItemImg(f)
      if (img) this.furnitureImages.set(f.id, img)
    }
  }

  private renderProps() {
    this.propsImages.forEach(img => img.destroy())
    this.propsImages.clear()
    if (!this.layerVisibility.props) return

    const sorted = [...this.layout.props].sort((a, b) => a.row - b.row)
    for (const f of sorted) {
      const img = this.renderItemImg(f)
      if (img) this.propsImages.set(f.id, img)
    }
  }

  private renderItemImg(f: FurnitureItem): Phaser.GameObjects.Image | null {
    return renderItemImage(this, f)
  }

  private renderSlots() {
    this.slotMarkers.forEach(g => {
      const text = g.getData('text')
      if (text) text.destroy()
      const arrow = g.getData('arrow')
      if (arrow) arrow.destroy()
      g.destroy()
    })
    this.slotMarkers = []
    if (!this.layerVisibility.slots) return
    if (!this.layout.slots) this.layout.slots = []

    const ts = TILE * ZOOM
    for (let i = 0; i < this.layout.slots.length; i++) {
      const slot = this.layout.slots[i]
      const x = slot.col * ts
      const y = slot.row * ts
      const cx = x + ts / 2
      const cy = y + ts / 2
      const dir = slot.dir ?? 'up'

      const g = this.add.graphics().setDepth(900)
      // Green circle marker
      g.fillStyle(0x00ff88, 0.6)
      g.fillCircle(cx, cy, ts / 3)
      g.lineStyle(2, 0x00ff88, 1)
      g.strokeCircle(cx, cy, ts / 3)

      // Direction arrow
      const arrowG = this.add.graphics().setDepth(902)
      arrowG.lineStyle(3, 0xffffff, 0.9)
      const arrowLen = ts / 4
      const arrowHead = 6
      let dx = 0, dy = 0
      if (dir === 'up') dy = -1
      else if (dir === 'down') dy = 1
      else if (dir === 'left') dx = -1
      else if (dir === 'right') dx = 1

      const ax = cx + dx * arrowLen
      const ay = cy + dy * arrowLen
      arrowG.lineBetween(cx, cy, ax, ay)
      // Arrow head
      if (dir === 'up') {
        arrowG.lineBetween(ax, ay, ax - arrowHead, ay + arrowHead)
        arrowG.lineBetween(ax, ay, ax + arrowHead, ay + arrowHead)
      } else if (dir === 'down') {
        arrowG.lineBetween(ax, ay, ax - arrowHead, ay - arrowHead)
        arrowG.lineBetween(ax, ay, ax + arrowHead, ay - arrowHead)
      } else if (dir === 'left') {
        arrowG.lineBetween(ax, ay, ax + arrowHead, ay - arrowHead)
        arrowG.lineBetween(ax, ay, ax + arrowHead, ay + arrowHead)
      } else if (dir === 'right') {
        arrowG.lineBetween(ax, ay, ax - arrowHead, ay - arrowHead)
        arrowG.lineBetween(ax, ay, ax - arrowHead, ay + arrowHead)
      }

      // Slot number (smaller, offset)
      const text = this.add.text(x + 6, y + 6, `${i + 1}`, {
        fontSize: '12px',
        fontFamily: 'monospace',
        color: '#ffffff',
      }).setOrigin(0, 0).setDepth(901)

      this.slotMarkers.push(g)
      g.setData('text', text)
      g.setData('arrow', arrowG)
    }
  }

  private renderGrid() {
    this.gridGraphics.clear()
    const { cols, rows } = this.layout
    const ts = TILE * ZOOM

    this.gridGraphics.lineStyle(1, 0xffffff, 0.08)
    for (let c = 0; c <= cols; c++) {
      this.gridGraphics.lineBetween(c * ts, 0, c * ts, rows * ts)
    }
    for (let r = 0; r <= rows; r++) {
      this.gridGraphics.lineBetween(0, r * ts, cols * ts, r * ts)
    }
  }

  update() {
    // Nothing dynamic in editor
  }
}
