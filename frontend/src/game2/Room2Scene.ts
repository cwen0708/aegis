/**
 * Room2Scene — SkyOffice 圖集 + Tiled 地圖 + 角色系統
 */
import Phaser from 'phaser'
import { findPath, simplifyPath } from '../game/pathfinding'
import {
  preloadDefaultChars, createAllDefaultAnims, createAnimsForKey,
  CHAR_FRAME_W, CHAR_LEGACY_W, MAX_CHAR_COUNT,
  legacyCharKeys,
} from './characterAnims'
import { computeTiledWalkable } from './tiledWalkable'
import { extractWorkSlots, type TiledWorkSlot } from './tiledSlots'

const ASSET_BASE = 'assets/office2'
const TILE_SIZE = 32
// 角色縮放：與舊房間一致（ZOOM=3）
// 新版 128x256: 3 * (16/128) = 0.375 → 48px 寬、96px 高
// 舊版 16x32:  3 → 48px 寬、96px 高
const ZOOM = 3
const CHAR_BASE_SCALE = CHAR_LEGACY_W / CHAR_FRAME_W  // 16/128 = 0.125

// tileset name → spritesheet key 映射
const TILESET_KEY_MAP: Record<string, string> = {
  'FloorAndGround': 'tiles_floor',
  'Modern_Office_Black_Shadow': 'tiles_office',
  'Generic': 'tiles_generic',
  'Basement': 'tiles_basement',
  'chair': 'chairs',
  'computer': 'computers',
  'whiteboard': 'whiteboards',
  'vendingmachine': 'vendingmachines',
}

// tileset 資訊（preload 後由 create 填入）
interface TilesetInfo {
  name: string
  firstgid: number
  lastgid: number  // firstgid + tilecount - 1
  spriteKey: string
}

// ── Types ───────────────────────────────────────────────────────
export type DeskInfo = {
  member: { id: number; name: string; provider: string; sprite_index: number; sprite_sheet?: string; sprite_scale?: number }
  task: { card_title: string; project: string }
} | null

export interface SceneData {
  totalDesks: number
  desks: DeskInfo[]
  resting: { id: number; name: string; provider: string; sprite_index: number; sprite_sheet?: string; sprite_scale?: number }[]
  bubbles: Map<number, string>
  used: number
  total: number
  memberCount: number
}

// ══════════════════════════════════════════════════════════════════
export default class Room2Scene extends Phaser.Scene {
  private map!: Phaser.Tilemaps.Tilemap
  private tilesetInfos: TilesetInfo[] = []

  // Character system
  private allWalkable: Array<{ col: number; row: number }> = []
  private workSlots: TiledWorkSlot[] = []
  private characterSprites: Map<string, Phaser.GameObjects.Container> = new Map()
  private bubbleContainers: Map<number, Phaser.GameObjects.Container> = new Map()
  private memberCharLoaded: Set<number> = new Set()
  private memberSpriteUrls: Map<number, string> = new Map()
  private memberSpriteScales: Map<number, number> = new Map()
  private memberCharAvailable: Set<number> = new Set()
  private wanderTimers: Map<string, Phaser.Time.TimerEvent> = new Map()
  private usedSlots: Set<number> = new Set()
  private memberSlotMap: Map<number, number> = new Map()
  private memberSpriteKeys: Map<number, string> = new Map()
  private charCount = MAX_CHAR_COUNT

  constructor() {
    super('room2')
  }

  preload() {
    this.load.tilemapTiledJSON('tilemap2', `${ASSET_BASE}/map.json`)

    // 地板+牆壁
    this.load.spritesheet('tiles_floor', `${ASSET_BASE}/FloorAndGround.png`, {
      frameWidth: 32, frameHeight: 32,
    })
    // 辦公傢俱（32×32 tiles）
    this.load.spritesheet('tiles_office', `${ASSET_BASE}/tileset/Modern_Office_Black_Shadow.png`, {
      frameWidth: 32, frameHeight: 32,
    })
    this.load.spritesheet('tiles_generic', `${ASSET_BASE}/tileset/Generic.png`, {
      frameWidth: 32, frameHeight: 32,
    })
    this.load.spritesheet('tiles_basement', `${ASSET_BASE}/tileset/Basement.png`, {
      frameWidth: 32, frameHeight: 32,
    })
    // 物件（非 32×32）
    this.load.spritesheet('chairs', `${ASSET_BASE}/items/chair.png`, {
      frameWidth: 32, frameHeight: 64,
    })
    this.load.spritesheet('computers', `${ASSET_BASE}/items/computer.png`, {
      frameWidth: 96, frameHeight: 64,
    })
    this.load.spritesheet('whiteboards', `${ASSET_BASE}/items/whiteboard.png`, {
      frameWidth: 64, frameHeight: 64,
    })
    this.load.spritesheet('vendingmachines', `${ASSET_BASE}/items/vendingmachine.png`, {
      frameWidth: 48, frameHeight: 72,
    })

    // 角色精靈
    preloadDefaultChars(this)
  }

  create() {
    this.map = this.make.tilemap({ key: 'tilemap2' })

    // 註冊 tilesets
    const floorTileset = this.map.addTilesetImage('FloorAndGround', 'tiles_floor')!
    const officeTileset = this.map.addTilesetImage('Modern_Office_Black_Shadow', 'tiles_office')!
    const genericTileset = this.map.addTilesetImage('Generic', 'tiles_generic')!
    const basementTileset = this.map.addTilesetImage('Basement', 'tiles_basement')!

    // 建立 tileset 查找表（從 map.json 的 tilesets 資料）
    this._buildTilesetInfos()

    // 地板 tile layer
    const allTilesets = [floorTileset, officeTileset, genericTileset, basementTileset]
    const groundLayer = this.map.createLayer('Ground', allTilesets)
    if (groundLayer) {
      groundLayer.setCollisionByProperty({ collides: true })
    }

    // Object layers 分兩組渲染：
    // 1. 底層物件（椅子、地下室裝飾）— 不做 Y-sort，永遠在下面
    for (const name of ['Chair', 'Basement']) {
      this._renderObjectLayer(name, false)
    }
    // 2. 上層物件（桌子、電腦等）— Y-sort depth，會蓋住椅子和角色
    for (const name of ['Wall', 'Objects', 'ObjectsOnCollide', 'GenericObjects', 'GenericObjectsOnCollide', 'Computer', 'Whiteboard', 'VendingMachine']) {
      this._renderObjectLayer(name, true)
    }

    // 攝影機
    const mapWidth = this.map.widthInPixels
    const mapHeight = this.map.heightInPixels
    this.cameras.main.setBounds(0, 0, mapWidth, mapHeight)
    this.cameras.main.setZoom(1.5)
    this.cameras.main.centerOn(mapWidth / 2, mapHeight / 2)

    // 攝影機取整（防止 tile bleeding 黑線）
    this.cameras.main.setRoundPixels(true)

    // 拖曳
    this.input.on('pointermove', (pointer: Phaser.Input.Pointer) => {
      if (pointer.isDown) {
        this.cameras.main.scrollX -= (pointer.x - pointer.prevPosition.x) / this.cameras.main.zoom
        this.cameras.main.scrollY -= (pointer.y - pointer.prevPosition.y) / this.cameras.main.zoom
      }
    })

    // 滾輪縮放（限制為整數倍避免子像素）
    this.input.on('wheel', (_p: unknown, _g: unknown, _dx: number, _dy: number, dz: number) => {
      const cam = this.cameras.main
      const raw = cam.zoom - dz * 0.001
      // 取整到 0.5 的倍數（1.0, 1.5, 2.0, 2.5, 3.0）避免非整數 zoom 產生 tile bleeding
      const snapped = Math.round(raw * 2) / 2
      cam.setZoom(Phaser.Math.Clamp(snapped, 0.5, 3))
    })

    // 角色點擊
    this.input.setTopOnly(true)

    // 計算可行走區域和工位
    createAllDefaultAnims(this)
    this.allWalkable = computeTiledWalkable(this.map)
    this.workSlots = extractWorkSlots(this.map)

    // 通知 Vue 場景已就緒
    this.game.events.emit('scene-ready')
  }

  // ── Tileset helpers ─────────────────────────────────────────────

  /** 從 map 的 tilesets 建立 gid 查找表 */
  private _buildTilesetInfos() {
    this.tilesetInfos = this.map.tilesets.map((ts) => {
      const spriteKey = TILESET_KEY_MAP[ts.name] || ts.name
      return {
        name: ts.name,
        firstgid: ts.firstgid,
        lastgid: ts.firstgid + ts.total - 1,
        spriteKey,
      }
    })
    // 按 firstgid 降序排（查找時大 gid 先匹配）
    this.tilesetInfos.sort((a, b) => b.firstgid - a.firstgid)
  }

  /** 根據 gid 找到對應的 spritesheet key + frame index */
  private _resolveGid(gid: number): { key: string; frame: number } | null {
    for (const info of this.tilesetInfos) {
      if (gid >= info.firstgid && gid <= info.lastgid) {
        return { key: info.spriteKey, frame: gid - info.firstgid }
      }
    }
    return null
  }

  /** 渲染一個 object layer 裡的所有物件 */
  private _renderObjectLayer(layerName: string, useDepthSort: boolean) {
    const layer = this.map.getObjectLayer(layerName)
    if (!layer) return

    layer.objects.forEach((obj) => {
      if (!obj.gid) return

      const resolved = this._resolveGid(obj.gid)
      if (!resolved) return

      const sprite = this.add.sprite(
        obj.x! + (obj.width || 0) / 2,
        obj.y! - (obj.height || 0) / 2,
        resolved.key,
        resolved.frame,
      )

      if (useDepthSort) {
        // Y-sort：y 越大（越靠下）depth 越高，會蓋住上面的物件
        sprite.setDepth(obj.y! + (obj.height || 0) * 0.27)
      } else {
        // 底層物件：固定低 depth（被桌子和角色蓋住）
        sprite.setDepth(0)
      }
    })
  }

  // ══════════════════════════════════════════════════════════════════
  // Data bridge（Vue → Phaser）
  // ══════════════════════════════════════════════════════════════════

  updateData(data: SceneData) {
    if (!this.map) return
    this.updateCharactersIncremental(data)
    this.updateBubbles(data.bubbles)
  }

  // ── Member sprites ──────────────────────────────────────────────

  tryLoadMemberSprite(memberId: number, spriteUrl?: string, callback?: () => void) {
    const prevUrl = this.memberSpriteUrls.get(memberId)
    if (prevUrl && prevUrl === spriteUrl) { callback?.(); return }
    if (this.memberCharLoaded.has(memberId) && !spriteUrl) { callback?.(); return }
    this.memberCharLoaded.add(memberId)
    if (spriteUrl) this.memberSpriteUrls.set(memberId, spriteUrl)

    const key = `mchar_${memberId}`
    const url = spriteUrl || `/uploads/sprites/${memberId}/sprite_sheet.png`

    this.load.spritesheet(key, url, { frameWidth: CHAR_FRAME_W, frameHeight: CHAR_FRAME_W === 128 ? 256 : 32 })

    const onSpriteReady = () => {
      this.memberCharAvailable.add(memberId)
      createAnimsForKey(this, key)
      this._refreshMemberSprite(memberId)
      callback?.()
    }

    this.load.once('filecomplete-spritesheet-' + key, () => {
      if (!this.textures.exists(key)) return
      const tex = this.textures.get(key)
      const source = tex.source[0]
      if (!source) return

      if (source.width < CHAR_FRAME_W) {
        this.textures.remove(key)
        this.load.spritesheet(key, url, { frameWidth: CHAR_LEGACY_W, frameHeight: 32 })
        this.load.once('filecomplete-spritesheet-' + key, () => {
          if (!this.textures.exists(key)) return
          legacyCharKeys.add(key)
          onSpriteReady()
        })
        this.load.start()
        return
      }

      onSpriteReady()
    })
    this.load.once('loaderror', () => { /* 無自訂 sprite，用預設 */ })
    this.load.start()
  }

  private _refreshMemberSprite(memberId: number) {
    const spriteKey = this.memberSpriteKeys.get(memberId)
    if (!spriteKey) return
    const container = this.characterSprites.get(spriteKey)
    if (!container || !container.active) return

    const charKey = `mchar_${memberId}`
    const sprite = container.getAt(1) as Phaser.GameObjects.Sprite
    if (!sprite) return

    const memberScale = this.memberSpriteScales.get(memberId)
    const charScale = legacyCharKeys.has(charKey)
      ? ZOOM
      : ZOOM * (memberScale || CHAR_BASE_SCALE)
    sprite.setTexture(charKey)
    sprite.setScale(charScale)
    sprite.play(`${charKey}_idle`)
  }

  // ── Characters (incremental update) ─────────────────────────────

  private updateCharactersIncremental(data: SceneData) {
    if (!this.map) return

    // 嘗試載入成員自訂精靈
    const allMemberData = [
      ...data.desks.filter(d => d).map(d => d!.member),
      ...data.resting,
    ]
    for (const m of allMemberData) {
      if (m.sprite_scale) this.memberSpriteScales.set(m.id, m.sprite_scale)
      this.tryLoadMemberSprite(m.id, m.sprite_sheet)
    }

    // 建立目前工作/休息成員集合
    const currentWorkerIds = new Set(data.desks.filter(d => d).map(d => d!.member.id))
    const currentResterIds = new Set(data.resting.map(m => m.id))
    const allCurrentIds = new Set([...currentWorkerIds, ...currentResterIds])

    // 移除不存在的角色
    for (const [memberId, spriteKey] of this.memberSpriteKeys) {
      if (!allCurrentIds.has(memberId)) {
        const sprite = this.characterSprites.get(spriteKey)
        if (sprite) sprite.destroy()
        this.characterSprites.delete(spriteKey)
        this.memberSpriteKeys.delete(memberId)

        if (this.memberSlotMap.has(memberId)) {
          this.usedSlots.delete(this.memberSlotMap.get(memberId)!)
          this.memberSlotMap.delete(memberId)
        }

        const timer = this.wanderTimers.get(spriteKey)
        if (timer) { timer.destroy(); this.wanderTimers.delete(spriteKey) }

        const bubble = this.bubbleContainers.get(memberId)
        if (bubble) { bubble.destroy(); this.bubbleContainers.delete(memberId) }
      }
    }

    // 新增/更新工作中的角色
    data.desks.forEach((desk) => {
      if (!desk) return
      const memberId = desk.member.id

      if (this.memberSpriteKeys.has(memberId)) {
        const existingKey = this.memberSpriteKeys.get(memberId)!
        if (existingKey.startsWith('w_')) return

        // 原本在休息，現在工作 — 銷毀舊的
        const oldSprite = this.characterSprites.get(existingKey)
        if (oldSprite) oldSprite.destroy()
        this.characterSprites.delete(existingKey)
        const timer = this.wanderTimers.get(existingKey)
        if (timer) { timer.destroy(); this.wanderTimers.delete(existingKey) }
      }

      // 分配工位
      let slotIdx = this.memberSlotMap.get(memberId)
      if (slotIdx === undefined && this.workSlots.length > 0) {
        const available = []
        for (let i = 0; i < this.workSlots.length; i++) {
          if (!this.usedSlots.has(i)) available.push(i)
        }
        if (available.length > 0) {
          slotIdx = available[Math.floor(Math.random() * available.length)]!
          this.usedSlots.add(slotIdx)
          this.memberSlotMap.set(memberId, slotIdx)
        }
      }

      let px: number, py: number, workDir: 'down' | 'left' | 'right' | 'up'
      if (slotIdx !== undefined && this.workSlots[slotIdx]) {
        const slot = this.workSlots[slotIdx]!
        px = slot.pixelX
        py = slot.pixelY
        workDir = slot.dir
      } else if (this.allWalkable.length > 0) {
        const sp = this.allWalkable[Math.floor(Math.random() * this.allWalkable.length)]!
        px = sp.col * TILE_SIZE + TILE_SIZE / 2
        py = sp.row * TILE_SIZE + TILE_SIZE / 2
        workDir = 'up'
      } else {
        return
      }

      const c = this.createCharacter(px, py, memberId, desk.member.name, desk.member.provider, desk.member.sprite_index, 'working', workDir)
      const key = `w_${memberId}`
      this.characterSprites.set(key, c)
      this.memberSpriteKeys.set(memberId, key)
    })

    // 新增/更新休息中的角色
    data.resting.forEach((m) => {
      const memberId = m.id

      if (this.memberSpriteKeys.has(memberId)) {
        const existingKey = this.memberSpriteKeys.get(memberId)!
        if (existingKey.startsWith('r_')) return

        // 原本在工作，現在休息 — 保留位置開始漫步
        const sprite = this.characterSprites.get(existingKey)
        if (sprite) {
          if (this.memberSlotMap.has(memberId)) {
            this.usedSlots.delete(this.memberSlotMap.get(memberId)!)
            this.memberSlotMap.delete(memberId)
          }
          this.characterSprites.delete(existingKey)
          const newKey = `r_${memberId}`
          this.characterSprites.set(newKey, sprite)
          this.memberSpriteKeys.set(memberId, newKey)
          this.startWander(newKey, sprite, memberId, this.allWalkable)
          return
        }
      }

      // 新成員 — 隨機位置
      if (this.allWalkable.length === 0) return
      const sp = this.allWalkable[Math.floor(Math.random() * this.allWalkable.length)]!
      const px = sp.col * TILE_SIZE + TILE_SIZE / 2
      const py = sp.row * TILE_SIZE + TILE_SIZE / 2
      const c = this.createCharacter(px, py, memberId, m.name, m.provider, m.sprite_index, 'idle')
      const key = `r_${memberId}`
      this.characterSprites.set(key, c)
      this.memberSpriteKeys.set(memberId, key)
      this.startWander(key, c, memberId, this.allWalkable)
    })
  }

  // ── Character creation ──────────────────────────────────────────

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

    let charKey = this.memberCharAvailable.has(memberId)
      ? `mchar_${memberId}`
      : `char_${spriteIndex % this.charCount}`
    if (!this.textures.exists(charKey)) charKey = 'char_0'

    // 陰影
    const shadow = this.add.graphics()
    shadow.fillStyle(0x000000, 0.2)
    shadow.fillEllipse(0, 2, 12 * ZOOM, 4 * ZOOM)

    // 精靈
    const memberScale = this.memberSpriteScales.get(memberId)
    const charScale = legacyCharKeys.has(charKey)
      ? ZOOM
      : ZOOM * (memberScale || CHAR_BASE_SCALE)
    const sprite = this.add.sprite(0, 0, charKey).setScale(charScale).setOrigin(0.5, 1)

    if (mode === 'working') {
      sprite.play(`${charKey}_work_${workDir}`)
    } else {
      sprite.play(`${charKey}_idle`)
    }

    container.add([shadow, sprite])

    // 名字標籤
    const provColor = provider === 'claude' ? '#fb923c' : provider === 'gemini' ? '#60a5fa' : '#94a3b8'
    const nameColor = mode === 'working' ? provColor : '#94a3b8'
    const nameText = this.add.text(0, 16, name, {
      fontFamily: '"Press Start 2P"', fontSize: '16px', color: nameColor,
    }).setOrigin(0.5, 0.5)

    const pw = nameText.width + 16
    const ph = nameText.height + 12
    const nameBox = this.add.graphics()
    nameBox.fillStyle(0x1a1a2e, 0.85)
    nameBox.fillRoundedRect(-pw / 2, -ph / 2 + 16, pw, ph, 4)
    nameBox.lineStyle(1, parseInt(nameColor.replace('#', '0x')), 0.6)
    nameBox.strokeRoundedRect(-pw / 2, -ph / 2 + 16, pw, ph, 4)

    container.add([nameBox, nameText])

    // 深度：用 Y 座標自然排序
    container.setDepth(cy)

    // 點擊互動
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

      const curCol = Math.round(container.x / TILE_SIZE - 0.5)
      const curRow = Math.round(container.y / TILE_SIZE - 0.5)

      const byDist = roomTiles
        .map(t => ({ ...t, d: Math.abs(t.col - curCol) + Math.abs(t.row - curRow) }))
        .filter(t => t.d > 1 && t.d < 15)
        .sort((a, b) => a.d - b.d)

      if (byDist.length === 0) {
        this.wanderTimers.set(key, this.time.delayedCall(2000, wander))
        return
      }

      const nearbyCount = Math.max(3, Math.floor(byDist.length * 0.3))
      const target = byDist[Math.floor(Math.random() * nearbyCount)]!

      // pathfinding.ts 的 layout 參數未使用，傳空物件
      const path = findPath({} as any, curCol, curRow, target.col, target.row, roomTiles)
      if (path.length === 0) {
        this.wanderTimers.set(key, this.time.delayedCall(1000, wander))
        return
      }

      const simplePath = simplifyPath(path)
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
    let charKey = this.memberCharAvailable.has(memberId)
      ? `mchar_${memberId}`
      : `char_${spriteIndex % this.charCount}`
    if (!this.textures.exists(charKey)) charKey = 'char_0'

    if (path.length === 0 || !container.active) {
      const sprite = container.getAt(1) as Phaser.GameObjects.Sprite
      if (sprite?.anims) { sprite.play(`${charKey}_idle`); sprite.setFlipX(false) }
      this.wanderTimers.set(key, this.time.delayedCall(1500 + Math.random() * 4000, onComplete))
      return
    }

    const next = path.shift()!
    const wpX = next.col * TILE_SIZE + TILE_SIZE / 2
    const wpY = next.row * TILE_SIZE + TILE_SIZE / 2
    const dx = wpX - container.x
    const dy = wpY - container.y
    const dist = Math.sqrt(dx * dx + dy * dy)
    const speed = TILE_SIZE * 1.5  // 48 px/s
    const duration = Math.max(100, (dist / speed) * 1000)

    const sprite = container.getAt(1) as Phaser.GameObjects.Sprite
    if (sprite?.anims) {
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
      x: wpX,
      y: wpY,
      duration,
      ease: 'Linear',
      onUpdate: () => {
        container.setDepth(container.y)
      },
      onComplete: () => {
        this.walkPath(key, container, 0, path, roomTiles, onComplete)
      },
    })
  }

  // ── Bubbles ───────────────────────────────────────────────────

  private updateBubbles(bubbles: Map<number, string>) {
    this.bubbleContainers.forEach((c, id) => {
      if (!bubbles.has(id)) { c.destroy(); this.bubbleContainers.delete(id) }
    })

    bubbles.forEach((text, memberId) => {
      if (this.bubbleContainers.has(memberId)) return
      const pos = this._findChar(memberId)
      if (!pos) return

      const bubble = this.add.container(pos.x, pos.y - CHAR_LEGACY_W * 2 * ZOOM - 6)
      bubble.setDepth(999)

      const t = this.add.text(0, 0, text, {
        fontFamily: '"Press Start 2P"', fontSize: '21px', color: '#ffd700',
      }).setOrigin(0.5, 0.5)

      const bw = t.width + 12, bh = t.height + 8
      const bg = this.add.graphics()
      bg.fillStyle(0x1a1a2e, 0.92)
      bg.fillRect(-bw / 2, -bh / 2, bw, bh)
      bg.lineStyle(1, 0xAA8844, 0.6)
      bg.strokeRect(-bw / 2, -bh / 2, bw, bh)
      bg.fillStyle(0x1a1a2e, 0.92)
      bg.fillTriangle(-3, bh / 2, 3, bh / 2, 0, bh / 2 + 4)

      bubble.add([bg, t])
      this.bubbleContainers.set(memberId, bubble)

      bubble.setScale(0)
      this.tweens.add({ targets: bubble, scaleX: 1, scaleY: 1, duration: 200, ease: 'Back.easeOut' })
    })
  }

  private _findChar(memberId: number): { x: number; y: number } | null {
    for (const [, c] of this.characterSprites) {
      if (c.getData('memberId') === memberId) return { x: c.x, y: c.y }
    }
    return null
  }

  update() {
    // 泡泡跟隨角色
    this.bubbleContainers.forEach((bubble, memberId) => {
      const pos = this._findChar(memberId)
      if (pos) {
        bubble.x = pos.x
        bubble.y = pos.y - CHAR_LEGACY_W * 2 * ZOOM - 6
      }
    })
  }
}


export function createRoom2Game(parent: string): Phaser.Game {
  return new Phaser.Game({
    type: Phaser.AUTO,
    parent,
    width: window.innerWidth,
    height: window.innerHeight,
    pixelArt: true,
    roundPixels: true,
    physics: {
      default: 'arcade',
      arcade: { debug: false },
    },
    scene: [Room2Scene],
    scale: {
      mode: Phaser.Scale.RESIZE,
      autoCenter: Phaser.Scale.CENTER_BOTH,
    },
    backgroundColor: '#1a1a2e',
  })
}
