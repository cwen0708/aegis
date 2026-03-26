/**
 * characterAnims — 角色精靈載入與動畫建立（從 OfficeScene 提取）
 *
 * 支援新版 128×256 和舊版 16×32 sprite sheets，自動偵測。
 */
import Phaser from 'phaser'

export const CHAR_FRAME_W = 128
export const CHAR_FRAME_H = 256
export const CHAR_LEGACY_W = 16
export const CHAR_LEGACY_H = 32
export const MAX_CHAR_COUNT = 7

/** 追蹤舊版 sprite keys（16×32），需要不同 scale */
export const legacyCharKeys = new Set<string>()

/** 載入 spritesheet，自動偵測新版或舊版 */
function loadCharSpritesheet(scene: Phaser.Scene, key: string, url: string) {
  scene.load.spritesheet(key, url, {
    frameWidth: CHAR_FRAME_W, frameHeight: CHAR_FRAME_H,
  })
  scene.load.once('filecomplete-spritesheet-' + key, () => {
    const tex = scene.textures.get(key)
    const source = tex.source[0]
    if (!source) return
    if (source.width < CHAR_FRAME_W) {
      scene.textures.remove(key)
      scene.load.spritesheet(key, url, {
        frameWidth: CHAR_LEGACY_W, frameHeight: CHAR_LEGACY_H,
      })
      scene.load.once('filecomplete-spritesheet-' + key, () => {
        createAnimsForKey(scene, key)
      })
      scene.load.start()
      legacyCharKeys.add(key)
    }
  })
}

/** 預載 char_0 ~ char_6 預設角色 */
export function preloadDefaultChars(scene: Phaser.Scene) {
  for (let i = 0; i < MAX_CHAR_COUNT; i++) {
    loadCharSpritesheet(scene, `char_${i}`, `/assets/office/characters_4dir/char_${i}.png`)
  }
}

/**
 * 為指定 key 建立所有動畫（idle, walk×4, sit×4, work×4, type）
 *
 * 3 cols × 12 rows:
 *   Row 0-3: walk (down, left, right, up)
 *   Row 4-7: sit
 *   Row 8-11: work
 */
export function createAnimsForKey(scene: Phaser.Scene, key: string) {
  if (scene.anims.exists(`${key}_idle`)) return
  if (!scene.textures.exists(key)) return

  scene.anims.create({ key: `${key}_idle`, frames: [{ key, frame: 1 }], frameRate: 1, repeat: -1 })

  scene.anims.create({ key: `${key}_walk_down`, frames: scene.anims.generateFrameNumbers(key, { frames: [0, 1, 2, 1] }), frameRate: 6, repeat: -1 })
  scene.anims.create({ key: `${key}_walk_left`, frames: scene.anims.generateFrameNumbers(key, { frames: [3, 4, 5, 4] }), frameRate: 6, repeat: -1 })
  scene.anims.create({ key: `${key}_walk_right`, frames: scene.anims.generateFrameNumbers(key, { frames: [6, 7, 8, 7] }), frameRate: 6, repeat: -1 })
  scene.anims.create({ key: `${key}_walk_up`, frames: scene.anims.generateFrameNumbers(key, { frames: [9, 10, 11, 10] }), frameRate: 6, repeat: -1 })

  scene.anims.create({ key: `${key}_sit_down`, frames: scene.anims.generateFrameNumbers(key, { frames: [12, 13, 14, 13] }), frameRate: 3, repeat: -1 })
  scene.anims.create({ key: `${key}_sit_left`, frames: scene.anims.generateFrameNumbers(key, { frames: [15, 16, 17, 16] }), frameRate: 3, repeat: -1 })
  scene.anims.create({ key: `${key}_sit_right`, frames: scene.anims.generateFrameNumbers(key, { frames: [18, 19, 20, 19] }), frameRate: 3, repeat: -1 })
  scene.anims.create({ key: `${key}_sit_up`, frames: scene.anims.generateFrameNumbers(key, { frames: [21, 22, 23, 22] }), frameRate: 3, repeat: -1 })

  scene.anims.create({ key: `${key}_work_down`, frames: scene.anims.generateFrameNumbers(key, { frames: [24, 25, 26, 25] }), frameRate: 3, repeat: -1 })
  scene.anims.create({ key: `${key}_work_left`, frames: scene.anims.generateFrameNumbers(key, { frames: [27, 28, 29, 28] }), frameRate: 3, repeat: -1 })
  scene.anims.create({ key: `${key}_work_right`, frames: scene.anims.generateFrameNumbers(key, { frames: [30, 31, 32, 31] }), frameRate: 3, repeat: -1 })
  scene.anims.create({ key: `${key}_work_up`, frames: scene.anims.generateFrameNumbers(key, { frames: [33, 34, 35, 34] }), frameRate: 3, repeat: -1 })

  scene.anims.create({ key: `${key}_type`, frames: scene.anims.generateFrameNumbers(key, { frames: [33, 34, 35, 34] }), frameRate: 3, repeat: -1 })
}

/** 批次建立所有預設角色動畫 */
export function createAllDefaultAnims(scene: Phaser.Scene) {
  for (let i = 0; i < MAX_CHAR_COUNT; i++) {
    createAnimsForKey(scene, `char_${i}`)
  }
}
