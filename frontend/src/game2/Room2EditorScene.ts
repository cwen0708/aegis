/**
 * Room2EditorScene — Tiled 地圖視覺化編輯器
 * Phase 1: Ground layer 繪製 + 網格 + 攝影機
 * Phase 2: 物件放置 + 渲染 + Layer 管理
 * Phase 3: 選取 + 拖曳 + 刪除 + Undo/Redo
 * Phase 4: 存檔 + 載入 + API
 */
import Phaser from 'phaser'
import {
  ASSET_BASE, TILE_SIZE,
  preloadTilesets, buildTilesetInfos, resolveGid,
  TILESET_PRELOAD_CONFIG,
  type TilesetInfo,
} from './tilesetRegistry'
import {
  EditorHistory, PlaceTileCommand, PlaceObjectCommand,
  DeleteObjectCommand, MoveObjectCommand, BatchCommand,
} from './editorHistory'
import { exportMapJson, fetchDefaultTilesets, type TiledMapJson } from './mapSerializer'
import { EditorEvents } from './editorBridge'
import {
  DEPTH_BASE_LAYER, DEPTH_GRID, DEPTH_HOVER, DEPTH_COLLISION,
  DEPTH_SELECTION, DEPTH_HOVER_SPRITE, DEPTH_SORT_FACTOR,
  ZOOM_MIN, ZOOM_MAX, ZOOM_INITIAL, INITIAL_OBJECT_ID, isDepthSorted,
} from './editorConstants'

export type EditorTool = 'ground' | 'eraser' | 'select' | 'object' | 'fill' | 'hand'

export interface EditorLayerDef {
  name: string
  label: string
  type: 'tile' | 'object'
  editable: boolean
}

export const EDITOR_LAYERS: EditorLayerDef[] = [
  { name: 'Ground', label: '地板', type: 'tile', editable: true },
  { name: 'Chair', label: '椅子', type: 'object', editable: true },
  { name: 'Wall', label: '牆壁', type: 'object', editable: true },
  { name: 'Objects', label: '家具', type: 'object', editable: true },
  { name: 'ObjectsOnCollide', label: '障礙物', type: 'object', editable: true },
  { name: 'GenericObjects', label: '裝飾', type: 'object', editable: true },
  { name: 'GenericObjectsOnCollide', label: '裝飾障礙', type: 'object', editable: true },
  { name: 'Computer', label: '電腦', type: 'object', editable: true },
  { name: 'Whiteboard', label: '白板', type: 'object', editable: true },
  { name: 'Basement', label: '地下室', type: 'object', editable: false },
  { name: 'VendingMachine', label: '販賣機', type: 'object', editable: true },
]

export interface PlacedObject {
  id: number
  gid: number
  x: number
  y: number
  width: number
  height: number
}

/** 選取事件資料，emit 給 Vue */
export interface SelectionInfo {
  obj: PlacedObject
  layerName: string
}

export default class Room2EditorScene extends Phaser.Scene {
  private map!: Phaser.Tilemaps.Tilemap
  private tilesetInfos: TilesetInfo[] = []
  private groundLayer!: Phaser.Tilemaps.TilemapLayer

  // Editor state
  private currentTool: EditorTool = 'ground'
  private selectedGid = 1
  private gridGraphics!: Phaser.GameObjects.Graphics
  private hoverGraphics!: Phaser.GameObjects.Graphics

  // Object placement (Phase 2)
  private targetLayerName = 'Objects'
  private nextObjectId = INITIAL_OBJECT_ID
  private layerSprites: Map<string, Phaser.GameObjects.Sprite[]> = new Map()
  private layerObjects: Map<string, PlacedObject[]> = new Map()
  private hoverSprite: Phaser.GameObjects.Sprite | null = null

  // Selection & drag (Phase 3)
  private history = new EditorHistory()
  private selectedObjId: number | null = null
  private selectedLayerName: string | null = null
  private selectionBox: Phaser.GameObjects.Graphics | null = null
  private isDragging = false
  private dragStartX = 0
  private dragStartY = 0
  private dragObjStartX = 0
  private dragObjStartY = 0

  // Camera
  private isPanning = false
  private isSpaceDown = false
  private isPinching = false
  private pinchStartDist = 0
  private pinchStartZoom = 1

  // Collision preview (Phase 5)
  private collisionOverlay: Phaser.GameObjects.Graphics | null = null
  private showCollision = false

  // Custom map (Phase 4)
  private customMapJson: TiledMapJson | null = null

  constructor(customMapJson?: TiledMapJson) {
    super('room2-editor')
    this.customMapJson = customMapJson ?? null
  }

  preload() {
    if (this.customMapJson) {
      this.cache.tilemap.add('tilemap2_edit', {
        data: this.customMapJson,
        format: Phaser.Tilemaps.Formats.TILED_JSON,
      })
    } else {
      this.load.tilemapTiledJSON('tilemap2_edit', `${ASSET_BASE}/map.json`)
    }
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

    // 渲染所有 object layers 並追蹤 sprites + 填入 layerObjects
    for (const layerDef of EDITOR_LAYERS) {
      if (layerDef.type === 'object') {
        this.loadObjectLayer(layerDef.name)
      }
    }

    // Selection box graphics
    this.selectionBox = this.add.graphics().setDepth(DEPTH_SELECTION)

    // Collision overlay
    this.collisionOverlay = this.add.graphics().setDepth(DEPTH_COLLISION)

    // 網格
    this.gridGraphics = this.add.graphics().setDepth(DEPTH_GRID)
    this.drawGrid()

    // Hover 預覽
    this.hoverGraphics = this.add.graphics().setDepth(DEPTH_HOVER)

    // 攝影機
    const mapWidth = this.map.widthInPixels
    const mapHeight = this.map.heightInPixels
    this.cameras.main.setBounds(0, 0, mapWidth, mapHeight)
    this.cameras.main.setZoom(ZOOM_INITIAL)
    this.cameras.main.centerOn(mapWidth / 2, mapHeight / 2)
    this.cameras.main.setRoundPixels(true)

    this.setupInput()
    this.setupKeyboard()

    // 通知 Vue 場景就緒
    this.game.events.emit(EditorEvents.READY)
  }

  // ── Input ──────────────────────────────────────────────────────

  private setupInput() {
    // ── pointermove ─────────────────────────────────────────
    this.input.on('pointermove', (pointer: Phaser.Input.Pointer) => {
      // pinch zoom
      if (this.input.pointer1.isDown && this.input.pointer2.isDown) {
        this.handlePinchMove()
        return
      }
      if (this.isPinching) return

      // 拖曳物件
      if (this.isDragging && pointer.isDown) {
        this.handleDragMove(pointer)
        return
      }

      // 攝影機平移（右鍵 / 中鍵 / Space+左鍵 / hand 工具左鍵）
      if (this.isPanning && pointer.isDown) {
        this.cameras.main.scrollX -= (pointer.x - pointer.prevPosition.x) / this.cameras.main.zoom
        this.cameras.main.scrollY -= (pointer.y - pointer.prevPosition.y) / this.cameras.main.zoom
        return
      }

      // 左鍵拖曳連續繪製（ground/eraser）
      if (pointer.isDown && !pointer.middleButtonDown() && !pointer.rightButtonDown()) {
        if (this.currentTool === 'ground' || this.currentTool === 'eraser') {
          this.handlePaint(pointer)
        }
      }

      // hover 預覽
      this.updateHover(pointer)
    })

    // ── pointerdown ─────────────────────────────────────────
    this.input.on('pointerdown', (pointer: Phaser.Input.Pointer) => {
      // 右鍵 / 中鍵 → 永遠攝影機平移（like Photoshop）
      if (pointer.rightButtonDown() || pointer.middleButtonDown()) {
        this.isPanning = true
        return
      }

      // Space+左鍵 or hand 工具 → 攝影機平移
      if (this.isSpaceDown || this.currentTool === 'hand') {
        this.isPanning = true
        return
      }

      // 左鍵操作（依工具）
      switch (this.currentTool) {
        case 'select':
          this.handleSelectDown(pointer)
          break
        case 'object':
          this.handleObjectPlace(pointer)
          break
        case 'fill':
          this.handleFloodFill(pointer)
          break
        case 'ground':
        case 'eraser':
          this.handlePaint(pointer)
          break
      }
    })

    // ── pointerup ───────────────────────────────────────────
    this.input.on('pointerup', (pointer: Phaser.Input.Pointer) => {
      if (!this.input.pointer1.isDown || !this.input.pointer2.isDown) {
        this.isPinching = false
      }
      this.isPanning = false
      if (this.isDragging) {
        this.handleDragEnd(pointer)
      }
    })

    // 多點觸控
    this.input.addPointer(1)

    // 滾輪縮放
    this.input.on('wheel', (_p: unknown, _g: unknown, _dx: number, _dy: number, dz: number) => {
      this.applyZoom(this.cameras.main.zoom - dz * 0.001)
    })

    // 滑鼠離開 canvas 時清除 hover
    this.input.on('pointerout', () => {
      this.hoverGraphics.clear()
      this.destroyHoverSprite()
    })

    // 停用右鍵選單
    this.input.mouse?.disableContextMenu()
  }

  private setupKeyboard() {
    // Space 按住 = 攝影機平移模式
    this.input.keyboard?.on('keydown-SPACE', () => { this.isSpaceDown = true })
    this.input.keyboard?.on('keyup-SPACE', () => {
      this.isSpaceDown = false
      this.isPanning = false
    })

    this.input.keyboard?.on('keydown-Z', (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey) {
        if (e.shiftKey) {
          this.history.redo()
        } else {
          this.history.undo()
        }
        this.clearSelection()
      }
    })

    this.input.keyboard?.on('keydown-Y', (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey) {
        this.history.redo()
        this.clearSelection()
      }
    })

    this.input.keyboard?.on('keydown-DELETE', () => {
      this.deleteSelected()
    })

    this.input.keyboard?.on('keydown-BACKSPACE', () => {
      this.deleteSelected()
    })

    this.input.keyboard?.on('keydown-C', () => {
      this.toggleCollisionPreview()
    })
  }

  private applyZoom(raw: number) {
    const snapped = Math.round(raw * 2) / 2
    this.cameras.main.setZoom(Phaser.Math.Clamp(snapped, ZOOM_MIN, ZOOM_MAX))
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

    const worldPoint = this.cameras.main.getWorldPoint(pointer.x, pointer.y)
    const col = Math.floor(worldPoint.x / TILE_SIZE)
    const row = Math.floor(worldPoint.y / TILE_SIZE)

    if (col < 0 || col >= this.map.width || row < 0 || row >= this.map.height) {
      this.destroyHoverSprite()
      return
    }

    if (this.currentTool === 'ground' || this.currentTool === 'eraser' || this.currentTool === 'fill') {
      this.destroyHoverSprite()
      const color = this.currentTool === 'eraser' ? 0xff4444
        : this.currentTool === 'fill' ? 0x4488ff : 0x44ff44
      this.hoverGraphics.fillStyle(color, 0.3)
      this.hoverGraphics.fillRect(col * TILE_SIZE, row * TILE_SIZE, TILE_SIZE, TILE_SIZE)
    } else if (this.currentTool === 'object') {
      this.updateObjectHover(worldPoint)
    } else {
      this.destroyHoverSprite()
    }
  }

  private updateObjectHover(worldPoint: Phaser.Math.Vector2) {
    const resolved = resolveGid(this.selectedGid, this.tilesetInfos)
    if (!resolved) {
      this.destroyHoverSprite()
      return
    }

    const cfg = this.getFrameSize(resolved.key)
    const snapX = Math.floor(worldPoint.x / TILE_SIZE) * TILE_SIZE
    const snapY = (Math.floor(worldPoint.y / TILE_SIZE) + 1) * TILE_SIZE

    if (!this.hoverSprite) {
      this.hoverSprite = this.add.sprite(0, 0, resolved.key, resolved.frame)
      this.hoverSprite.setAlpha(0.5).setDepth(DEPTH_HOVER_SPRITE)
    }

    if (this.hoverSprite.texture.key !== resolved.key || this.hoverSprite.frame.name !== String(resolved.frame)) {
      this.hoverSprite.setTexture(resolved.key, resolved.frame)
    }

    this.hoverSprite.setPosition(
      snapX + cfg.frameWidth / 2,
      snapY - cfg.frameHeight / 2,
    )
  }

  private destroyHoverSprite() {
    if (this.hoverSprite) {
      this.hoverSprite.destroy()
      this.hoverSprite = null
    }
  }

  // ── Selection ─────────────────────────────────────────────────

  private handleSelectDown(pointer: Phaser.Input.Pointer) {
    const worldPoint = this.cameras.main.getWorldPoint(pointer.x, pointer.y)
    const hit = this.hitTestObjects(worldPoint.x, worldPoint.y)

    if (hit) {
      this.selectObject(hit.obj.id, hit.layerName)
      // Start drag
      this.isDragging = true
      this.dragStartX = worldPoint.x
      this.dragStartY = worldPoint.y
      this.dragObjStartX = hit.obj.x
      this.dragObjStartY = hit.obj.y
    } else {
      this.clearSelection()
    }
  }

  private handleDragMove(pointer: Phaser.Input.Pointer) {
    if (!this.selectedObjId || !this.selectedLayerName) return

    const worldPoint = this.cameras.main.getWorldPoint(pointer.x, pointer.y)
    const dx = worldPoint.x - this.dragStartX
    const dy = worldPoint.y - this.dragStartY

    const newX = Math.round((this.dragObjStartX + dx) / TILE_SIZE) * TILE_SIZE
    const newY = Math.round((this.dragObjStartY + dy) / TILE_SIZE) * TILE_SIZE

    this.moveObjectVisual(this.selectedLayerName, this.selectedObjId, newX, newY)
    this.drawSelectionBox()
  }

  private handleDragEnd(_pointer: Phaser.Input.Pointer) {
    if (!this.isDragging || !this.selectedObjId || !this.selectedLayerName) {
      this.isDragging = false
      return
    }
    this.isDragging = false

    const obj = this.findObject(this.selectedLayerName, this.selectedObjId)
    if (!obj) return

    if (obj.x === this.dragObjStartX && obj.y === this.dragObjStartY) return

    const cmd = new MoveObjectCommand(
      this, this.selectedLayerName, this.selectedObjId,
      this.dragObjStartX, this.dragObjStartY,
      obj.x, obj.y,
    )
    this.history.pushExecuted(cmd)
    this.emitSelection()
  }

  private hitTestObjects(worldX: number, worldY: number): { obj: PlacedObject; layerName: string } | null {
    // 從上層往下找，先命中的優先
    const layerOrder = [...EDITOR_LAYERS].reverse()
    for (const layerDef of layerOrder) {
      if (layerDef.type !== 'object') continue
      const objects = this.layerObjects.get(layerDef.name)
      if (!objects) continue

      // 從後往前（後放的在上面）
      for (let i = objects.length - 1; i >= 0; i--) {
        const obj = objects[i]!
        // bounds check：obj.x 是左邊，obj.y 是底邊
        const left = obj.x
        const right = obj.x + obj.width
        const top = obj.y - obj.height
        const bottom = obj.y
        if (worldX >= left && worldX <= right && worldY >= top && worldY <= bottom) {
          return { obj, layerName: layerDef.name }
        }
      }
    }
    return null
  }

  private selectObject(objId: number, layerName: string) {
    this.selectedObjId = objId
    this.selectedLayerName = layerName
    this.drawSelectionBox()
    this.emitSelection()
  }

  clearSelection() {
    this.selectedObjId = null
    this.selectedLayerName = null
    this.selectionBox?.clear()
    this.emitSelection()
  }

  private drawSelectionBox() {
    if (!this.selectionBox) return
    this.selectionBox.clear()

    if (!this.selectedObjId || !this.selectedLayerName) return
    const obj = this.findObject(this.selectedLayerName, this.selectedObjId)
    if (!obj) return

    this.selectionBox.lineStyle(2, 0x4488ff, 1)
    this.selectionBox.strokeRect(obj.x, obj.y - obj.height, obj.width, obj.height)

    // corner handles
    const s = 4
    this.selectionBox.fillStyle(0x4488ff, 1)
    this.selectionBox.fillRect(obj.x - s / 2, obj.y - obj.height - s / 2, s, s)
    this.selectionBox.fillRect(obj.x + obj.width - s / 2, obj.y - obj.height - s / 2, s, s)
    this.selectionBox.fillRect(obj.x - s / 2, obj.y - s / 2, s, s)
    this.selectionBox.fillRect(obj.x + obj.width - s / 2, obj.y - s / 2, s, s)
  }

  private emitSelection() {
    if (this.selectedObjId && this.selectedLayerName) {
      const obj = this.findObject(this.selectedLayerName, this.selectedObjId)
      if (obj) {
        this.game.events.emit(EditorEvents.OBJECT_SELECTED, { obj: { ...obj }, layerName: this.selectedLayerName } satisfies SelectionInfo)
        return
      }
    }
    this.game.events.emit(EditorEvents.OBJECT_SELECTED, null)
  }

  deleteSelected() {
    if (!this.selectedObjId || !this.selectedLayerName) return
    const obj = this.findObject(this.selectedLayerName, this.selectedObjId)
    if (!obj) return

    const cmd = new DeleteObjectCommand(this, this.selectedLayerName, obj)
    this.history.execute(cmd)
    this.clearSelection()
  }

  // ── Object placement (with history) ───────────────────────────

  private handleObjectPlace(pointer: Phaser.Input.Pointer) {
    const resolved = resolveGid(this.selectedGid, this.tilesetInfos)
    if (!resolved) return

    const worldPoint = this.cameras.main.getWorldPoint(pointer.x, pointer.y)
    const cfg = this.getFrameSize(resolved.key)

    const snapX = Math.floor(worldPoint.x / TILE_SIZE) * TILE_SIZE
    const snapY = (Math.floor(worldPoint.y / TILE_SIZE) + 1) * TILE_SIZE

    const obj: PlacedObject = {
      id: this.nextObjectId++,
      gid: this.selectedGid,
      x: snapX,
      y: snapY,
      width: cfg.frameWidth,
      height: cfg.frameHeight,
    }

    const cmd = new PlaceObjectCommand(this, this.targetLayerName, obj)
    this.history.execute(cmd)
  }

  // ── Load original object layer into editable state ─────────────

  private loadObjectLayer(layerName: string) {
    const useDepthSort = isDepthSorted(layerName)
    const mapLayer = this.map.getObjectLayer(layerName)
    const objects: PlacedObject[] = []
    const sprites: Phaser.GameObjects.Sprite[] = []

    if (mapLayer) {
      for (const obj of mapLayer.objects) {
        if (!obj.gid) continue
        const resolved = resolveGid(obj.gid, this.tilesetInfos)
        if (!resolved) continue

        const id = obj.id || this.nextObjectId++
        if (id >= this.nextObjectId) this.nextObjectId = id + 1

        const placedObj: PlacedObject = {
          id,
          gid: obj.gid,
          x: obj.x ?? 0,
          y: obj.y ?? 0,
          width: obj.width ?? 0,
          height: obj.height ?? 0,
        }
        objects.push(placedObj)

        const sprite = this.add.sprite(
          placedObj.x + placedObj.width / 2,
          placedObj.y - placedObj.height / 2,
          resolved.key,
          resolved.frame,
        )
        sprite.setData('objId', id)
        if (useDepthSort) {
          sprite.setDepth(placedObj.y + placedObj.height * DEPTH_SORT_FACTOR)
        } else {
          sprite.setDepth(DEPTH_BASE_LAYER)
        }
        sprites.push(sprite)
      }
    }

    this.layerObjects.set(layerName, objects)
    this.layerSprites.set(layerName, sprites)
  }

  // ── Object manipulation (called by Commands) ──────────────────

  addObjectToLayer(layerName: string, obj: PlacedObject) {
    if (!this.layerObjects.has(layerName)) {
      this.layerObjects.set(layerName, [])
    }
    this.layerObjects.get(layerName)!.push(obj)

    const resolved = resolveGid(obj.gid, this.tilesetInfos)
    if (!resolved) return

    const sprite = this.add.sprite(
      obj.x + obj.width / 2,
      obj.y - obj.height / 2,
      resolved.key,
      resolved.frame,
    )
    sprite.setData('objId', obj.id)
    if (isDepthSorted(layerName)) {
      sprite.setDepth(obj.y + obj.height * DEPTH_SORT_FACTOR)
    } else {
      sprite.setDepth(DEPTH_BASE_LAYER)
    }

    if (!this.layerSprites.has(layerName)) {
      this.layerSprites.set(layerName, [])
    }
    this.layerSprites.get(layerName)!.push(sprite)
  }

  removeObjectFromLayer(layerName: string, objId: number) {
    const objects = this.layerObjects.get(layerName)
    if (objects) {
      const idx = objects.findIndex(o => o.id === objId)
      if (idx >= 0) objects.splice(idx, 1)
    }

    const sprites = this.layerSprites.get(layerName)
    if (sprites) {
      const idx = sprites.findIndex(s => s.getData('objId') === objId)
      if (idx >= 0) {
        sprites[idx]!.destroy()
        sprites.splice(idx, 1)
      }
    }
  }

  moveObjectInLayer(layerName: string, objId: number, x: number, y: number) {
    this.moveObjectVisual(layerName, objId, x, y)
  }

  private moveObjectVisual(layerName: string, objId: number, x: number, y: number) {
    const obj = this.findObject(layerName, objId)
    if (!obj) return
    obj.x = x
    obj.y = y

    const sprites = this.layerSprites.get(layerName)
    if (sprites) {
      const sprite = sprites.find(s => s.getData('objId') === objId)
      if (sprite) {
        sprite.setPosition(x + obj.width / 2, y - obj.height / 2)
        if (isDepthSorted(layerName)) {
          sprite.setDepth(y + obj.height * DEPTH_SORT_FACTOR)
        }
      }
    }
  }

  private findObject(layerName: string, objId: number): PlacedObject | undefined {
    return this.layerObjects.get(layerName)?.find(o => o.id === objId)
  }

  private getFrameSize(key: string): { frameWidth: number; frameHeight: number } {
    const cfg = TILESET_PRELOAD_CONFIG.find(c => c.key === key)
    return cfg
      ? { frameWidth: cfg.frameWidth, frameHeight: cfg.frameHeight }
      : { frameWidth: TILE_SIZE, frameHeight: TILE_SIZE }
  }

  // ── Paint (with history) ──────────────────────────────────────

  private handlePaint(pointer: Phaser.Input.Pointer) {
    if (this.currentTool !== 'ground' && this.currentTool !== 'eraser') return
    if (!this.groundLayer) return

    const worldPoint = this.cameras.main.getWorldPoint(pointer.x, pointer.y)
    const col = Math.floor(worldPoint.x / TILE_SIZE)
    const row = Math.floor(worldPoint.y / TILE_SIZE)

    if (col < 0 || col >= this.map.width || row < 0 || row >= this.map.height) return

    const oldTile = this.map.getTileAt(col, row, true, 'Ground')
    const oldGid = oldTile?.index ?? -1
    const newGid = this.currentTool === 'eraser' ? -1 : this.selectedGid

    if (oldGid === newGid) return

    const cmd = new PlaceTileCommand(this.map, col, row, newGid, oldGid)
    this.history.execute(cmd)
  }

  // ── Flood Fill (Phase 5) ───────────────────────────────────────

  private static readonly MAX_FILL_AREA = 2000

  private handleFloodFill(pointer: Phaser.Input.Pointer) {
    if (!this.groundLayer) return

    const worldPoint = this.cameras.main.getWorldPoint(pointer.x, pointer.y)
    const col = Math.floor(worldPoint.x / TILE_SIZE)
    const row = Math.floor(worldPoint.y / TILE_SIZE)

    if (col < 0 || col >= this.map.width || row < 0 || row >= this.map.height) return

    const oldTile = this.map.getTileAt(col, row, true, 'Ground')
    const targetGid = oldTile?.index ?? -1
    const newGid = this.selectedGid

    if (targetGid === newGid) return

    // BFS flood fill with area limit (head pointer for O(n) performance)
    const visited = new Set<string>()
    const queue: [number, number][] = [[col, row]]
    const tiles: [number, number][] = []
    let head = 0

    while (head < queue.length && tiles.length < Room2EditorScene.MAX_FILL_AREA) {
      const [c, r] = queue[head++]!
      const key = `${c},${r}`
      if (visited.has(key)) continue
      if (c < 0 || c >= this.map.width || r < 0 || r >= this.map.height) continue

      const tile = this.map.getTileAt(c, r, true, 'Ground')
      const gid = tile?.index ?? -1
      if (gid !== targetGid) continue

      visited.add(key)
      tiles.push([c, r])

      queue.push([c + 1, r], [c - 1, r], [c, r + 1], [c, r - 1])
    }

    if (tiles.length === 0) return

    // Atomic undo: wrap all tile commands in a BatchCommand
    const cmds = tiles.map(([tc, tr]) =>
      new PlaceTileCommand(this.map, tc, tr, newGid, targetGid),
    )
    this.history.execute(new BatchCommand(cmds))
  }

  // ── Collision Preview (Phase 5) ───────────────────────────────

  toggleCollisionPreview() {
    this.showCollision = !this.showCollision
    this.drawCollisionOverlay()
    this.game.events.emit(EditorEvents.COLLISION_TOGGLED, this.showCollision)
  }

  private drawCollisionOverlay() {
    if (!this.collisionOverlay) return
    this.collisionOverlay.clear()

    if (!this.showCollision) return

    // ObjectsOnCollide + GenericObjectsOnCollide = 半透明紅色
    for (const name of ['ObjectsOnCollide', 'GenericObjectsOnCollide']) {
      const sprites = this.layerSprites.get(name)
      if (!sprites) continue
      for (const s of sprites) {
        if (!s.visible) continue
        this.collisionOverlay.fillStyle(0xff4444, 0.3)
        this.collisionOverlay.fillRect(
          s.x - s.displayWidth / 2,
          s.y - s.displayHeight / 2,
          s.displayWidth,
          s.displayHeight,
        )
      }
    }

    // Wall = 半透明橘色
    const wallSprites = this.layerSprites.get('Wall')
    if (wallSprites) {
      for (const s of wallSprites) {
        if (!s.visible) continue
        this.collisionOverlay.fillStyle(0xff8800, 0.3)
        this.collisionOverlay.fillRect(
          s.x - s.displayWidth / 2,
          s.y - s.displayHeight / 2,
          s.displayWidth,
          s.displayHeight,
        )
      }
    }
  }

  // ── Layer visibility ──────────────────────────────────────────

  toggleLayerVisibility(layerName: string, visible: boolean) {
    if (layerName === 'Ground') {
      this.groundLayer?.setVisible(visible)
      return
    }
    const sprites = this.layerSprites.get(layerName)
    if (sprites) {
      for (const s of sprites) s.setVisible(visible)
    }
  }

  // ── Cleanup ────────────────────────────────────────────────────

  shutdown() {
    this.history.clear()
    this.layerObjects.clear()
    this.layerSprites.clear()
  }

  // ── Public API (Vue → Phaser) ──────────────────────────────────

  setTool(tool: EditorTool) {
    // 如果正在拖曳中切換工具，先回滾到拖曳起始位置
    if (this.isDragging && this.selectedObjId && this.selectedLayerName) {
      this.moveObjectVisual(this.selectedLayerName, this.selectedObjId, this.dragObjStartX, this.dragObjStartY)
      this.isDragging = false
    }
    this.currentTool = tool
    if (tool !== 'object') this.destroyHoverSprite()
    if (tool !== 'select') {
      this.isDragging = false
      this.clearSelection()
    }
  }

  setSelectedGid(gid: number) {
    this.selectedGid = gid
  }

  setTargetLayer(layerName: string) {
    this.targetLayerName = layerName
  }

  getTilesetInfos(): TilesetInfo[] {
    return this.tilesetInfos
  }

  getSceneRef(): this {
    return this
  }

  undo() {
    this.history.undo()
    this.clearSelection()
  }

  redo() {
    this.history.redo()
    this.clearSelection()
  }

  get canUndo() { return this.history.canUndo }
  get canRedo() { return this.history.canRedo }

  async getMapData(): Promise<TiledMapJson> {
    const tilesets = await fetchDefaultTilesets()
    return exportMapJson(this.map, this.layerObjects, tilesets)
  }

  getSelection(): SelectionInfo | null {
    if (!this.selectedObjId || !this.selectedLayerName) return null
    const obj = this.findObject(this.selectedLayerName, this.selectedObjId)
    if (!obj) return null
    return { obj: { ...obj }, layerName: this.selectedLayerName }
  }

  updateObjectPosition(layerName: string, objId: number, x: number, y: number) {
    const obj = this.findObject(layerName, objId)
    if (!obj) return
    const oldX = obj.x
    const oldY = obj.y
    if (oldX === x && oldY === y) return
    const cmd = new MoveObjectCommand(this, layerName, objId, oldX, oldY, x, y)
    this.history.execute(cmd)
    this.drawSelectionBox()
    this.emitSelection()
  }
}
