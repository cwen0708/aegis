/**
 * Room2Scene — 基於 SkyOffice 圖集 + Tiled 地圖的 Phaser 場景
 *
 * 特色：
 * - 32×32 原生 tile（不放大）
 * - Tiled JSON 載入（Phaser 原生 tilemap）
 * - 碰撞自動從 Tiled 屬性讀取
 * - Y-sort 深度排序
 */
import Phaser from 'phaser'

const ASSET_BASE = 'assets/office2'

export default class Room2Scene extends Phaser.Scene {
  private map!: Phaser.Tilemaps.Tilemap

  constructor() {
    super('room2')
  }

  preload() {
    // 地圖
    this.load.tilemapTiledJSON('tilemap2', `${ASSET_BASE}/map.json`)

    // 瓷磚圖集（spritesheet 方式載入，讓 Phaser 自動切幀）
    this.load.spritesheet('tiles_floor', `${ASSET_BASE}/FloorAndGround.png`, {
      frameWidth: 32, frameHeight: 32,
    })
    this.load.spritesheet('tiles_office', `${ASSET_BASE}/tileset/Modern_Office_Black_Shadow.png`, {
      frameWidth: 32, frameHeight: 32,
    })
    this.load.spritesheet('tiles_generic', `${ASSET_BASE}/tileset/Generic.png`, {
      frameWidth: 32, frameHeight: 32,
    })
    this.load.spritesheet('tiles_basement', `${ASSET_BASE}/tileset/Basement.png`, {
      frameWidth: 32, frameHeight: 32,
    })

    // 物件圖集
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
  }

  create() {
    // 建立 tilemap
    this.map = this.make.tilemap({ key: 'tilemap2' })

    // 綁定 tileset 名稱 → 載入的圖片 key
    const floorTileset = this.map.addTilesetImage('FloorAndGround', 'tiles_floor')!
    const officeTileset = this.map.addTilesetImage('Modern_Office_Black_Shadow', 'tiles_office')!
    const genericTileset = this.map.addTilesetImage('Generic', 'tiles_generic')!
    const basementTileset = this.map.addTilesetImage('Basement', 'tiles_basement')!

    const allTilesets = [floorTileset, officeTileset, genericTileset, basementTileset]

    // 建立 tile layers
    const groundLayer = this.map.createLayer('Ground', allTilesets)
    if (groundLayer) {
      groundLayer.setCollisionByProperty({ collides: true })
    }

    // 建立 object layers（椅子、電腦等）
    this._createObjectLayer('Chair', 'chairs')
    this._createObjectLayer('Computer', 'computers')
    this._createObjectLayer('Whiteboard', 'whiteboards')
    this._createObjectLayer('VendingMachine', 'vendingmachines')

    // 嘗試建立其他 tile layers（如果存在）
    for (const layerName of ['Wall', 'Objects', 'ObjectsOnCollide', 'GenericObjects', 'GenericObjectsOnCollide', 'Basement']) {
      const layer = this.map.getObjectLayer(layerName)
      if (layer) {
        const group = this.physics.add.staticGroup()
        layer.objects.forEach((obj) => {
          if (obj.gid) {
            const sprite = group.create(
              obj.x! + (obj.width || 0) / 2,
              obj.y! - (obj.height || 0) / 2,
            )
            // Y-sort 深度
            sprite.setDepth(obj.y!)
            sprite.setVisible(false) // 碰撞用，不顯示（tilemap 已渲染）
          }
        })
      }
    }

    // 攝影機
    const mapWidth = this.map.widthInPixels
    const mapHeight = this.map.heightInPixels
    this.cameras.main.setBounds(0, 0, mapWidth, mapHeight)
    this.cameras.main.setZoom(1.5)
    this.cameras.main.centerOn(mapWidth / 2, mapHeight / 2)

    // 拖曳
    this.input.on('pointermove', (pointer: Phaser.Input.Pointer) => {
      if (pointer.isDown) {
        this.cameras.main.scrollX -= (pointer.x - pointer.prevPosition.x) / this.cameras.main.zoom
        this.cameras.main.scrollY -= (pointer.y - pointer.prevPosition.y) / this.cameras.main.zoom
      }
    })

    // 滾輪縮放
    this.input.on('wheel', (_pointer: unknown, _go: unknown, _dx: number, _dy: number, dz: number) => {
      const cam = this.cameras.main
      const newZoom = Phaser.Math.Clamp(cam.zoom - dz * 0.001, 0.5, 3)
      cam.setZoom(newZoom)
    })
  }

  private _createObjectLayer(layerName: string, spriteKey: string) {
    const layer = this.map.getObjectLayer(layerName)
    if (!layer) return

    layer.objects.forEach((obj) => {
      if (!obj.gid) return
      const sprite = this.add.sprite(
        obj.x! + (obj.width || 0) / 2,
        obj.y! - (obj.height || 0) / 2,
        spriteKey,
        obj.gid - this._getFirstGid(spriteKey),
      )
      // Y-sort
      sprite.setDepth(obj.y! + (obj.height || 0) * 0.27)
    })
  }

  private _getFirstGid(tilesetName: string): number {
    // 從 map.json 的 tilesets 找 firstgid
    const tileset = this.map.tilesets.find(t => {
      // spritesheet key 可能跟 tileset name 不同，用 contains 匹配
      const n = t.name.toLowerCase()
      return tilesetName.toLowerCase().includes(n) || n.includes(tilesetName.toLowerCase())
    })
    return tileset?.firstgid ?? 0
  }
}


export function createRoom2Game(parent: string): Phaser.Game {
  return new Phaser.Game({
    type: Phaser.AUTO,
    parent,
    width: window.innerWidth,
    height: window.innerHeight,
    pixelArt: true,
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
