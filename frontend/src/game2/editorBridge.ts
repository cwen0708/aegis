/**
 * editorBridge — Vue ↔ Phaser 通訊中介層
 * 集中管理事件名稱、提供型別安全的 API
 */
import type Room2EditorScene from './Room2EditorScene'
import type { EditorTool, SelectionInfo } from './Room2EditorScene'
import type { TilesetInfo } from './tilesetRegistry'
import type { TiledMapJson } from './mapSerializer'

/** 所有 Phaser → Vue 事件名稱 */
export const EditorEvents = {
  READY: 'editor-ready',
  OBJECT_SELECTED: 'object-selected',
  COLLISION_TOGGLED: 'collision-toggled',
} as const

/**
 * EditorBridge — Vue 元件透過此物件操作 Scene
 * 避免直接持有 Scene 引用，所有操作方法都有 null-safe 保護
 */
export class EditorBridge {
  private scene: Room2EditorScene | null = null

  bind(scene: Room2EditorScene) {
    this.scene = scene
  }

  unbind() {
    this.scene = null
  }

  get isBound() { return this.scene !== null }

  // ── Tool ──────────────────────────────────────────────────────

  setTool(tool: EditorTool) { this.scene?.setTool(tool) }
  setSelectedGid(gid: number) { this.scene?.setSelectedGid(gid) }
  setTargetLayer(layerName: string) { this.scene?.setTargetLayer(layerName) }

  // ── History ───────────────────────────────────────────────────

  undo() { this.scene?.undo() }
  redo() { this.scene?.redo() }

  // ── Selection ─────────────────────────────────────────────────

  deleteSelected() { this.scene?.deleteSelected() }
  getSelection(): SelectionInfo | null { return this.scene?.getSelection() ?? null }
  updateObjectPosition(layerName: string, objId: number, x: number, y: number) {
    this.scene?.updateObjectPosition(layerName, objId, x, y)
  }

  // ── Layer ─────────────────────────────────────────────────────

  toggleLayerVisibility(layerName: string, visible: boolean) {
    this.scene?.toggleLayerVisibility(layerName, visible)
  }

  toggleCollisionPreview() { this.scene?.toggleCollisionPreview() }

  // ── Data ──────────────────────────────────────────────────────

  getTilesetInfos(): TilesetInfo[] { return this.scene?.getTilesetInfos() ?? [] }
  getSceneRef(): Phaser.Scene | null { return this.scene?.getSceneRef() ?? null }

  async getMapData(): Promise<TiledMapJson | null> {
    return this.scene?.getMapData() ?? null
  }
}
