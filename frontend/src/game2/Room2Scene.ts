/**
 * Room2Scene — SkyOffice 圖集 + Tiled 地圖
 */
import Phaser from 'phaser'

const ASSET_BASE = 'assets/office2'

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

export default class Room2Scene extends Phaser.Scene {
  private map!: Phaser.Tilemaps.Tilemap
  private tilesetInfos: TilesetInfo[] = []

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

    // 所有 object layers — 統一用 gid 解析渲染
    const objectLayerNames = [
      'Wall', 'Chair', 'Objects', 'ObjectsOnCollide',
      'GenericObjects', 'GenericObjectsOnCollide',
      'Computer', 'Whiteboard', 'Basement', 'VendingMachine',
    ]
    for (const name of objectLayerNames) {
      this._renderObjectLayer(name)
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
  }

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
  private _renderObjectLayer(layerName: string) {
    const layer = this.map.getObjectLayer(layerName)
    if (!layer) return

    layer.objects.forEach((obj) => {
      if (!obj.gid) return

      const resolved = this._resolveGid(obj.gid)
      if (!resolved) return

      // Tiled object 的 (x, y) 是左下角，Phaser sprite 的 origin 是中心
      const sprite = this.add.sprite(
        obj.x! + (obj.width || 0) / 2,
        obj.y! - (obj.height || 0) / 2,
        resolved.key,
        resolved.frame,
      )

      // Y-sort 深度排序
      sprite.setDepth(obj.y! + (obj.height || 0) * 0.27)
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
