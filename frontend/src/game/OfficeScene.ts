import Phaser from 'phaser'
import type { OfficeLayout, FurnitureItem } from './types'

import { computeAllWalkable } from './layoutManager'
import { buildDefaultLayout } from './defaultLayout'
import {
  TILE, ZOOM, preloadOfficeAssets,
  renderFloor as sharedRenderFloor,
  renderWalls as sharedRenderWalls,
  renderItemImage,
} from './renderUtils'
import { findPath, simplifyPath } from './pathfinding'

// ── Constants ───────────────────────────────────────────────────
const CHAR_FRAME_W = 16
const CHAR_FRAME_H = 32
const MAX_CHAR_COUNT = 7  // 最大可用角色圖數量（preload 用）


// ── Types ───────────────────────────────────────────────────────
export type DeskInfo = {
  member: { id: number; name: string; provider: string; sprite_index: number }
  task: { card_title: string; project: string }
} | null

export interface SceneData {
  totalDesks: number
  desks: DeskInfo[]
  resting: { id: number; name: string; provider: string; sprite_index: number }[]
  bubbles: Map<number, string>
  used: number
  total: number
  memberCount: number
}

// ══════════════════════════════════════════════════════════════════
// OfficeScene
// ══════════════════════════════════════════════════════════════════
export class OfficeScene extends Phaser.Scene {
  private currentData: SceneData | null = null
  private lastDeskCount = 4
  public layout!: OfficeLayout
  private charCount = MAX_CHAR_COUNT  // 實際使用的角色數量（可透過設定調整）
  private allWalkable: Array<{ col: number; row: number }> = []

  // Camera drag
  private isDragging = false
  private dragStartX = 0
  private dragStartY = 0
  private camStartX = 0
  private camStartY = 0

  // Pinch zoom
  private isPinching = false
  private pinchStartDist = 0
  private pinchStartZoom = 1
  private currentZoom = 1
  private readonly MIN_ZOOM = 0.5
  private readonly MAX_ZOOM = 2.0

  // Tracked objects
  private characterSprites: Map<string, Phaser.GameObjects.Container> = new Map()
  private bubbleContainers: Map<number, Phaser.GameObjects.Container> = new Map()

  // Member-specific sprites (AI generated)
  private memberCharLoaded: Set<number> = new Set()
  private memberCharAvailable: Set<number> = new Set()

  // Wandering
  private wanderTimers: Map<string, Phaser.Time.TimerEvent> = new Map()

  // External layout (set before scene starts or via loadLayout)
  private pendingLayout: OfficeLayout | null = null

  constructor() {
    super({ key: 'OfficeScene' })
  }

  setLayout(layout: OfficeLayout) {
    this.pendingLayout = layout
  }

  setCharacterCount(count: number) {
    this.charCount = Math.min(Math.max(1, count), MAX_CHAR_COUNT)
  }

  preload() {
    for (let i = 0; i < MAX_CHAR_COUNT; i++) {
      this.load.spritesheet(`char_${i}`, `/assets/office/characters_4dir/char_${i}.png`, {
        frameWidth: CHAR_FRAME_W, frameHeight: CHAR_FRAME_H,
      })
    }
    preloadOfficeAssets(this)
  }

  create() {
    this.createAnimations()
    this.loadLayout(this.pendingLayout || buildDefaultLayout(this.lastDeskCount))
    this.setupCameraDrag()
    // Allow interactive objects to receive click events
    this.input.setTopOnly(true)

    this.scale.on('resize', () => {
      const worldW = this.layout.cols * TILE * ZOOM
      const worldH = this.layout.rows * TILE * ZOOM
      this.cameras.main.setBounds(0, 0, worldW, worldH)
    })

    // Emit scene-ready event so Office.vue can push data after create() completes
    this.game.events.emit('scene-ready')
  }

  loadLayout(layout: OfficeLayout) {
    this.layout = layout
    this.allWalkable = computeAllWalkable(layout)

    const worldW = layout.cols * TILE * ZOOM
    const worldH = layout.rows * TILE * ZOOM
    this.cameras.main.setBounds(0, 0, worldW, worldH)
    this.cameras.main.centerOn(worldW / 2, worldH / 2)

    this.cleanupDynamic()
    // Destroy only non-system display objects (skip camera, input manager, etc.)
    const toDestroy = this.children.getAll().filter(
      obj => (obj as unknown) !== this.cameras.main && obj.type !== 'Manager'
    )
    toDestroy.forEach(obj => obj.destroy())

    this.renderFloor()
    this.renderWalls()
    this.renderFurniture()
    this.renderProps()
    // Room labels disabled
    // this.renderRoomLabels()

    // Clear member tracking for fresh start
    this.memberSpriteKeys.clear()
    this.memberSlotMap.clear()
    this.usedSlots.clear()
    if (this.currentData) this.updateDynamic(this.currentData)
  }

  private createAnimations() {
    for (let i = 0; i < MAX_CHAR_COUNT; i++) {
      const key = `char_${i}`
      if (this.anims.exists(`${key}_idle`)) continue

      // 新排列: 3 cols x 12 rows
      // Row 0-3: walk (down, left, right, up)
      // Row 4-7: sit (down, left, right, up)
      // Row 8-11: work (down, left, right, up)

      // idle 面向下
      this.anims.create({ key: `${key}_idle`, frames: [{ key, frame: 1 }], frameRate: 1, repeat: -1 })

      // 走路動畫
      this.anims.create({ key: `${key}_walk_down`, frames: this.anims.generateFrameNumbers(key, { frames: [0, 1, 2, 1] }), frameRate: 6, repeat: -1 })
      this.anims.create({ key: `${key}_walk_left`, frames: this.anims.generateFrameNumbers(key, { frames: [3, 4, 5, 4] }), frameRate: 6, repeat: -1 })
      this.anims.create({ key: `${key}_walk_right`, frames: this.anims.generateFrameNumbers(key, { frames: [6, 7, 8, 7] }), frameRate: 6, repeat: -1 })
      this.anims.create({ key: `${key}_walk_up`, frames: this.anims.generateFrameNumbers(key, { frames: [9, 10, 11, 10] }), frameRate: 6, repeat: -1 })

      // 坐下動畫
      this.anims.create({ key: `${key}_sit_down`, frames: this.anims.generateFrameNumbers(key, { frames: [12, 13, 14, 13] }), frameRate: 3, repeat: -1 })
      this.anims.create({ key: `${key}_sit_left`, frames: this.anims.generateFrameNumbers(key, { frames: [15, 16, 17, 16] }), frameRate: 3, repeat: -1 })
      this.anims.create({ key: `${key}_sit_right`, frames: this.anims.generateFrameNumbers(key, { frames: [18, 19, 20, 19] }), frameRate: 3, repeat: -1 })
      this.anims.create({ key: `${key}_sit_up`, frames: this.anims.generateFrameNumbers(key, { frames: [21, 22, 23, 22] }), frameRate: 3, repeat: -1 })

      // 工作動畫
      this.anims.create({ key: `${key}_work_down`, frames: this.anims.generateFrameNumbers(key, { frames: [24, 25, 26, 25] }), frameRate: 3, repeat: -1 })
      this.anims.create({ key: `${key}_work_left`, frames: this.anims.generateFrameNumbers(key, { frames: [27, 28, 29, 28] }), frameRate: 3, repeat: -1 })
      this.anims.create({ key: `${key}_work_right`, frames: this.anims.generateFrameNumbers(key, { frames: [30, 31, 32, 31] }), frameRate: 3, repeat: -1 })
      this.anims.create({ key: `${key}_work_up`, frames: this.anims.generateFrameNumbers(key, { frames: [33, 34, 35, 34] }), frameRate: 3, repeat: -1 })

      // 相容舊的 _type (用 work_up)
      this.anims.create({ key: `${key}_type`, frames: this.anims.generateFrameNumbers(key, { frames: [33, 34, 35, 34] }), frameRate: 3, repeat: -1 })
    }
  }

  /** 嘗試載入成員專屬 sprite（member_char_{id}.png），載入成功後建立動畫 */
  tryLoadMemberSprite(memberId: number, callback?: () => void) {
    if (this.memberCharLoaded.has(memberId)) {
      callback?.()
      return
    }
    this.memberCharLoaded.add(memberId)

    const key = `mchar_${memberId}`
    const url = `/assets/office/characters_4dir/member_char_${memberId}.png`

    this.load.spritesheet(key, url, { frameWidth: CHAR_FRAME_W, frameHeight: CHAR_FRAME_H })
    this.load.once('complete', () => {
      if (!this.textures.exists(key)) return
      // Verify it's not a broken/empty texture
      const frame = this.textures.get(key).get()
      if (frame.width < CHAR_FRAME_W) return

      this.memberCharAvailable.add(memberId)
      // Create animations for this member sprite
      this._createAnimsForKey(key)
      callback?.()
    })
    this.load.once('loaderror', () => {
      // No custom sprite for this member, use default
    })
    this.load.start()
  }

  private _createAnimsForKey(key: string) {
    if (this.anims.exists(`${key}_idle`)) return
    this.anims.create({ key: `${key}_idle`, frames: [{ key, frame: 1 }], frameRate: 1, repeat: -1 })
    this.anims.create({ key: `${key}_walk_down`, frames: this.anims.generateFrameNumbers(key, { frames: [0, 1, 2, 1] }), frameRate: 6, repeat: -1 })
    this.anims.create({ key: `${key}_walk_left`, frames: this.anims.generateFrameNumbers(key, { frames: [3, 4, 5, 4] }), frameRate: 6, repeat: -1 })
    this.anims.create({ key: `${key}_walk_right`, frames: this.anims.generateFrameNumbers(key, { frames: [6, 7, 8, 7] }), frameRate: 6, repeat: -1 })
    this.anims.create({ key: `${key}_walk_up`, frames: this.anims.generateFrameNumbers(key, { frames: [9, 10, 11, 10] }), frameRate: 6, repeat: -1 })
    this.anims.create({ key: `${key}_sit_down`, frames: this.anims.generateFrameNumbers(key, { frames: [12, 13, 14, 13] }), frameRate: 3, repeat: -1 })
    this.anims.create({ key: `${key}_sit_left`, frames: this.anims.generateFrameNumbers(key, { frames: [15, 16, 17, 16] }), frameRate: 3, repeat: -1 })
    this.anims.create({ key: `${key}_sit_right`, frames: this.anims.generateFrameNumbers(key, { frames: [18, 19, 20, 19] }), frameRate: 3, repeat: -1 })
    this.anims.create({ key: `${key}_sit_up`, frames: this.anims.generateFrameNumbers(key, { frames: [21, 22, 23, 22] }), frameRate: 3, repeat: -1 })
    this.anims.create({ key: `${key}_work_down`, frames: this.anims.generateFrameNumbers(key, { frames: [24, 25, 26, 25] }), frameRate: 3, repeat: -1 })
    this.anims.create({ key: `${key}_work_left`, frames: this.anims.generateFrameNumbers(key, { frames: [27, 28, 29, 28] }), frameRate: 3, repeat: -1 })
    this.anims.create({ key: `${key}_work_right`, frames: this.anims.generateFrameNumbers(key, { frames: [30, 31, 32, 31] }), frameRate: 3, repeat: -1 })
    this.anims.create({ key: `${key}_work_up`, frames: this.anims.generateFrameNumbers(key, { frames: [33, 34, 35, 34] }), frameRate: 3, repeat: -1 })
    this.anims.create({ key: `${key}_type`, frames: this.anims.generateFrameNumbers(key, { frames: [33, 34, 35, 34] }), frameRate: 3, repeat: -1 })
  }

  // ── Camera ────────────────────────────────────────────────────
  private setupCameraDrag() {
    // Single pointer drag
    this.input.on('pointerdown', (p: Phaser.Input.Pointer, objs: Phaser.GameObjects.GameObject[]) => {
      // Don't start drag if clicking on an interactive object
      if (objs.length > 0) return
      // Don't start drag if pinching
      if (this.isPinching) return
      this.isDragging = true
      this.dragStartX = p.x; this.dragStartY = p.y
      this.camStartX = this.cameras.main.scrollX
      this.camStartY = this.cameras.main.scrollY
    })
    this.input.on('pointermove', (p: Phaser.Input.Pointer) => {
      // Handle pinch zoom
      if (this.input.pointer1.isDown && this.input.pointer2.isDown) {
        this.handlePinchMove()
        return
      }
      if (!this.isDragging || this.isPinching) return
      this.cameras.main.scrollX = this.camStartX - (p.x - this.dragStartX)
      this.cameras.main.scrollY = this.camStartY - (p.y - this.dragStartY)
    })
    this.input.on('pointerup', () => {
      this.isDragging = false
      // Check if pinch ended
      if (!this.input.pointer1.isDown || !this.input.pointer2.isDown) {
        this.isPinching = false
      }
    })

    // Enable multi-touch
    this.input.addPointer(1) // Allow 2 pointers total
  }

  private handlePinchMove() {
    const p1 = this.input.pointer1
    const p2 = this.input.pointer2

    const dist = Phaser.Math.Distance.Between(p1.x, p1.y, p2.x, p2.y)

    if (!this.isPinching) {
      // Start pinching
      this.isPinching = true
      this.isDragging = false
      this.pinchStartDist = dist
      this.pinchStartZoom = this.currentZoom
    } else {
      // Update zoom based on pinch distance change
      const scale = dist / this.pinchStartDist
      let newZoom = this.pinchStartZoom * scale

      // Clamp zoom
      newZoom = Phaser.Math.Clamp(newZoom, this.MIN_ZOOM, this.MAX_ZOOM)

      this.currentZoom = newZoom
      this.cameras.main.setZoom(newZoom)
    }
  }

  // Public method to reset zoom
  resetZoom() {
    this.currentZoom = 1
    this.cameras.main.setZoom(1)
  }

  // ── Helpers ───────────────────────────────────────────────────
  private tw(col: number, row: number) {
    return { x: col * TILE * ZOOM, y: row * TILE * ZOOM }
  }
  // ── Floor & Walls ────────────────────────────────────────────
  private renderFloor() {
    sharedRenderFloor(this, this.layout)
  }

  private renderWalls() {
    sharedRenderWalls(this, this.layout)
  }

  // ── Furniture ─────────────────────────────────────────────────
  private renderFurniture() {
    const sorted = [...this.layout.furniture].sort((a, b) => a.row - b.row)
    for (const f of sorted) {
      this.renderItem(f)
    }
  }

  private renderProps() {
    const sorted = [...this.layout.props].sort((a, b) => a.row - b.row)
    for (const f of sorted) {
      this.renderItem(f)
    }
  }

  private renderItem(f: FurnitureItem) {
    renderItemImage(this, f)
  }

  // ══════════════════════════════════════════════════════════════════
  // Data bridge
  // ══════════════════════════════════════════════════════════════════
  updateData(data: SceneData) {
    this.currentData = data
    if (!this.layout) return  // Scene not yet created
    if (data.totalDesks !== this.lastDeskCount) {
      this.lastDeskCount = data.totalDesks
      // Only rebuild with default layout if no user-saved layout exists
      if (!this.pendingLayout) {
        this.loadLayout(buildDefaultLayout(data.totalDesks))
      }
    }
    this.updateDynamic(data)
  }

  /** Check if scene has completed create() */
  get isReady(): boolean {
    return !!this.layout
  }

  private cleanupDynamic() {
    this.characterSprites.forEach(c => c.destroy())
    this.characterSprites.clear()
    this.wanderTimers.forEach(t => t.destroy())
    this.wanderTimers.clear()
    this.bubbleContainers.forEach(c => c.destroy())
    this.bubbleContainers.clear()
    this.tweens.killAll()
  }

  private updateDynamic(data: SceneData) {
    this.updateCharactersIncremental(data)
    this.updateBubbles(data.bubbles)
  }

  // ── Characters (incremental update) ─────────────────────────────
  private usedSlots: Set<number> = new Set()
  private memberSlotMap: Map<number, number> = new Map()
  private memberSpriteKeys: Map<number, string> = new Map()

  private updateCharactersIncremental(data: SceneData) {
    if (!this.layout) return
    const slots = this.layout.slots || []

    // Build sets of current workers and resters
    const currentWorkerIds = new Set(data.desks.filter(d => d).map(d => d!.member.id))
    const currentResterIds = new Set(data.resting.map(m => m.id))
    const allCurrentIds = new Set([...currentWorkerIds, ...currentResterIds])

    // Remove characters no longer present
    for (const [memberId, spriteKey] of this.memberSpriteKeys) {
      if (!allCurrentIds.has(memberId)) {
        const sprite = this.characterSprites.get(spriteKey)
        if (sprite) sprite.destroy()
        this.characterSprites.delete(spriteKey)
        this.memberSpriteKeys.delete(memberId)

        // Release slot if was working
        if (this.memberSlotMap.has(memberId)) {
          this.usedSlots.delete(this.memberSlotMap.get(memberId)!)
          this.memberSlotMap.delete(memberId)
        }

        // Stop wander timer
        const timer = this.wanderTimers.get(spriteKey)
        if (timer) {
          timer.destroy()
          this.wanderTimers.delete(spriteKey)
        }

        // Remove bubble
        const bubble = this.bubbleContainers.get(memberId)
        if (bubble) {
          bubble.destroy()
          this.bubbleContainers.delete(memberId)
        }
      }
    }

    // Add/update workers
    data.desks.forEach((desk) => {
      if (!desk) return
      const memberId = desk.member.id

      // Already working? keep it
      if (this.memberSpriteKeys.has(memberId)) {
        const existingKey = this.memberSpriteKeys.get(memberId)!
        if (existingKey.startsWith('w_')) return

        // Was resting, now working - destroy old sprite, create at work position
        const oldSprite = this.characterSprites.get(existingKey)
        if (oldSprite) oldSprite.destroy()
        this.characterSprites.delete(existingKey)
        const timer = this.wanderTimers.get(existingKey)
        if (timer) {
          timer.destroy()
          this.wanderTimers.delete(existingKey)
        }
      }

      // Determine work position and direction
      let col: number, row: number, workDir: 'down' | 'left' | 'right' | 'up'

      if (slots.length > 0) {
        // Use slots system
        let slotIdx = this.memberSlotMap.get(memberId)
        if (slotIdx === undefined) {
          const availableSlots = []
          for (let i = 0; i < slots.length; i++) {
            if (!this.usedSlots.has(i)) availableSlots.push(i)
          }
          if (availableSlots.length > 0) {
            slotIdx = availableSlots[Math.floor(Math.random() * availableSlots.length)]!
            this.usedSlots.add(slotIdx)
            this.memberSlotMap.set(memberId, slotIdx)
          }
        }
        if (slotIdx === undefined || !slots[slotIdx]) return
        col = slots[slotIdx]!.col + 0.5
        row = slots[slotIdx]!.row + 0.5
        workDir = slots[slotIdx]!.dir || 'up'
      } else {
        // Fallback: use random walkable position
        if (this.allWalkable.length === 0) return
        const sp = this.allWalkable[Math.floor(Math.random() * this.allWalkable.length)]!
        col = sp.col + 0.5
        row = sp.row + 0.5
        workDir = 'up'
      }

      const pos = this.tw(col, row)
      const c = this.createCharacter(pos.x, pos.y, memberId, desk.member.name, desk.member.provider, desk.member.sprite_index, 'working', workDir)
      const key = `w_${memberId}`
      this.characterSprites.set(key, c)
      this.memberSpriteKeys.set(memberId, key)
    })

    // Add/update resters
    data.resting.forEach((m) => {
      const memberId = m.id

      // Already resting? keep wandering
      if (this.memberSpriteKeys.has(memberId)) {
        const existingKey = this.memberSpriteKeys.get(memberId)!
        if (existingKey.startsWith('r_')) return

        // Was working, now resting - keep sprite at current position, start wandering
        const sprite = this.characterSprites.get(existingKey)
        if (sprite) {
          // Release slot
          if (this.memberSlotMap.has(memberId)) {
            this.usedSlots.delete(this.memberSlotMap.get(memberId)!)
            this.memberSlotMap.delete(memberId)
          }

          // Update key and start wandering from work position
          this.characterSprites.delete(existingKey)
          const newKey = `r_${memberId}`
          this.characterSprites.set(newKey, sprite)
          this.memberSpriteKeys.set(memberId, newKey)
          this.startWander(newKey, sprite, memberId, this.allWalkable)
          return
        }
      }

      // New rester - spawn at random position
      const walkable = this.allWalkable
      if (walkable.length === 0) return

      const sp = walkable[Math.floor(Math.random() * walkable.length)]!
      const wp = this.tw(sp.col + 0.5, sp.row + 0.5)
      const c = this.createCharacter(wp.x, wp.y, memberId, m.name, m.provider, m.sprite_index, 'idle')
      const key = `r_${memberId}`
      this.characterSprites.set(key, c)
      this.memberSpriteKeys.set(memberId, key)
      this.startWander(key, c, memberId, walkable)
    })

    if (data.resting.length === 0 && data.memberCount > 0) {
      this.showMsg('ALL DEPLOYED!', '#ffd700')
    } else if (data.memberCount === 0) {
      this.showMsg('NO MEMBERS', '#887766')
    }
  }

  private createCharacter(
    cx: number, cy: number,
    memberId: number, name: string, provider: string,
    spriteIndex: number,
    mode: 'working' | 'idle',
    workDir: 'down' | 'left' | 'right' | 'up' = 'up',
  ): Phaser.GameObjects.Container {
    const container = this.add.container(cx, cy)
    container.setData('memberId', memberId)
    container.setData('spriteIndex', spriteIndex)
    // Prefer member-specific sprite if available, fallback to default
    const charKey = this.memberCharAvailable.has(memberId)
      ? `mchar_${memberId}`
      : `char_${spriteIndex % this.charCount}`

    const shadow = this.add.graphics()
    shadow.fillStyle(0x000000, 0.2)
    shadow.fillEllipse(0, 2, 12 * ZOOM, 4 * ZOOM)

    const sprite = this.add.sprite(0, 0, charKey).setScale(ZOOM).setOrigin(0.5, 1)

    if (mode === 'working') {
      sprite.play(`${charKey}_work_${workDir}`)
    } else {
      sprite.play(`${charKey}_idle`)
    }

    container.add([shadow, sprite])

    // Working: use provider color, Idle: use neutral color
    const provColor = provider === 'claude' ? '#fb923c' : provider === 'gemini' ? '#60a5fa' : '#94a3b8'
    const nameColor = mode === 'working' ? provColor : '#94a3b8'
    const nameText = this.add.text(0, 16, name, {
      fontFamily: '"Press Start 2P"', fontSize: '16px', color: nameColor,
    }).setOrigin(0.5, 0.5)

    const pw = nameText.width + 16
    const ph = nameText.height + 12
    const nameBox = this.add.graphics()
    nameBox.fillStyle(0x1a1510, 0.85)
    nameBox.fillRoundedRect(-pw / 2, -ph / 2 + 16, pw, ph, 4)
    nameBox.lineStyle(1, parseInt(nameColor.replace('#', '0x')), 0.6)
    nameBox.strokeRoundedRect(-pw / 2, -ph / 2 + 16, pw, ph, 4)

    container.add([nameBox, nameText])

    const tileRow = cy / (TILE * ZOOM)
    container.setDepth(Math.round(tileRow * TILE + TILE * 1.5))

    // Make sprite clickable
    sprite.setInteractive({ useHandCursor: true })
    sprite.on('pointerdown', (pointer: Phaser.Input.Pointer) => {
      if (pointer.leftButtonDown()) {
        this.events.emit('character-clicked', { memberId, name, provider })
      }
    })

    return container
  }

  // ── Wandering with A* pathfinding ─────────────────────────────
  private startWander(
    key: string, container: Phaser.GameObjects.Container,
    memberId: number, roomTiles: Array<{ col: number; row: number }>,
  ) {
    const wander = () => {
      if (!container.active) return

      const curCol = Math.round(container.x / (TILE * ZOOM) - 0.5)
      const curRow = Math.round(container.y / (TILE * ZOOM) - 0.5)

      // Pick a random target from nearby tiles
      const byDist = roomTiles
        .map(t => ({ ...t, d: Math.abs(t.col - curCol) + Math.abs(t.row - curRow) }))
        .filter(t => t.d > 1 && t.d < 15) // Not too close, not too far
        .sort((a, b) => a.d - b.d)

      if (byDist.length === 0) {
        this.wanderTimers.set(key, this.time.delayedCall(2000, wander))
        return
      }

      const nearbyCount = Math.max(3, Math.floor(byDist.length * 0.3))
      const target = byDist[Math.floor(Math.random() * nearbyCount)]!

      // Find path using A*
      const path = findPath(this.layout, curCol, curRow, target.col, target.row, roomTiles)
      if (path.length === 0) {
        // No path found, try again later
        this.wanderTimers.set(key, this.time.delayedCall(1000, wander))
        return
      }

      // Simplify path to reduce waypoints
      const simplePath = simplifyPath(path)

      // Walk along path
      this.walkPath(key, container, memberId, simplePath, roomTiles, wander)
    }

    this.wanderTimers.set(key, this.time.delayedCall(500 + Math.random() * 2000, wander))
  }

  private walkPath(
    key: string,
    container: Phaser.GameObjects.Container,
    _memberId: number,
    path: Array<{ col: number; row: number }>,
    roomTiles: Array<{ col: number; row: number }>,
    onComplete: () => void,
  ) {
    const spriteIndex = container.getData('spriteIndex') ?? 0
    const memberId = container.getData('memberId') as number
    const charKey = this.memberCharAvailable.has(memberId)
      ? `mchar_${memberId}`
      : `char_${spriteIndex % this.charCount}`

    if (path.length === 0 || !container.active) {
      const sprite = container.getAt(1) as Phaser.GameObjects.Sprite
      if (sprite?.anims) { sprite.play(`${charKey}_idle`); sprite.setFlipX(false) }
      this.wanderTimers.set(key, this.time.delayedCall(1500 + Math.random() * 4000, onComplete))
      return
    }

    const next = path.shift()!
    const wp = this.tw(next.col + 0.5, next.row + 0.5)
    const dx = wp.x - container.x
    const dy = wp.y - container.y
    const dist = Math.sqrt(dx * dx + dy * dy)
    const speed = TILE * ZOOM * 1.5
    const duration = Math.max(100, (dist / speed) * 1000)

    const sprite = container.getAt(1) as Phaser.GameObjects.Sprite
    if (sprite?.anims) {
      // 根據移動方向選擇動畫
      const absDx = Math.abs(dx)
      const absDy = Math.abs(dy)
      let dir = 'down'
      if (absDx > absDy) {
        dir = dx > 0 ? 'right' : 'left'
      } else {
        dir = dy > 0 ? 'down' : 'up'
      }
      sprite.play(`${charKey}_walk_${dir}`)
    }

    this.tweens.add({
      targets: container,
      x: wp.x,
      y: wp.y,
      duration,
      ease: 'Linear',
      onUpdate: () => {
        container.setDepth(Math.round((container.y / (TILE * ZOOM)) * TILE + TILE * 1.5))
      },
      onComplete: () => {
        // Continue to next waypoint
        this.walkPath(key, container, 0, path, roomTiles, onComplete)
      },
    })
  }

  // ── Messages ──────────────────────────────────────────────────
  private showMsg(text: string, color: string) {
    const pos = this.tw(10, 16)
    const msg = this.add.text(pos.x, pos.y, text, {
      fontFamily: '"Press Start 2P"', fontSize: '10px', color,
    }).setOrigin(0.5, 0.5).setDepth(500)
    this.characterSprites.set('msg', this.add.container(0, 0).add(msg))
  }

  // ── Bubbles ───────────────────────────────────────────────────
  private updateBubbles(bubbles: Map<number, string>) {
    this.bubbleContainers.forEach((c, id) => {
      if (!bubbles.has(id)) { c.destroy(); this.bubbleContainers.delete(id) }
    })

    bubbles.forEach((text, memberId) => {
      if (this.bubbleContainers.has(memberId)) return
      const pos = this.findChar(memberId)
      if (!pos) return

      const bubble = this.add.container(pos.x, pos.y - CHAR_FRAME_H * ZOOM - 6)
      bubble.setDepth(999)

      const t = this.add.text(0, 0, text, {
        fontFamily: '"Press Start 2P"', fontSize: '21px', color: '#ffd700',
      }).setOrigin(0.5, 0.5)

      const bw = t.width + 12, bh = t.height + 8
      const bg = this.add.graphics()
      bg.fillStyle(0x2a2218, 0.92)
      bg.fillRect(-bw / 2, -bh / 2, bw, bh)
      bg.lineStyle(1, 0xAA8844, 0.6)
      bg.strokeRect(-bw / 2, -bh / 2, bw, bh)
      bg.fillStyle(0x2a2218, 0.92)
      bg.fillTriangle(-3, bh / 2, 3, bh / 2, 0, bh / 2 + 4)

      bubble.add([bg, t])
      this.bubbleContainers.set(memberId, bubble)

      bubble.setScale(0)
      this.tweens.add({ targets: bubble, scaleX: 1, scaleY: 1, duration: 200, ease: 'Back.easeOut' })
    })
  }

  private findChar(memberId: number): { x: number; y: number } | null {
    for (const [, c] of this.characterSprites) {
      if (c.getData('memberId') === memberId) return { x: c.x, y: c.y }
    }
    return null
  }

  update() {
    // Update bubble positions to follow characters
    this.bubbleContainers.forEach((bubble, memberId) => {
      const pos = this.findChar(memberId)
      if (pos) {
        bubble.x = pos.x
        bubble.y = pos.y - CHAR_FRAME_H * ZOOM - 6
      }
    })
  }
}

// ══════════════════════════════════════════════════════════════════
export function createOfficeGame(parent: string, layout?: OfficeLayout): Phaser.Game {
  const scene = new OfficeScene()
  if (layout) scene.setLayout(layout)

  return new Phaser.Game({
    type: Phaser.AUTO,
    parent,
    backgroundColor: '#1a1510',
    pixelArt: true,
    scale: { mode: Phaser.Scale.RESIZE, parent },
    scene,
  })
}
