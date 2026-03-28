/**
 * editorHistory — Command pattern Undo/Redo for Room2 Editor
 * Phase 3
 */
import type Phaser from 'phaser'
import type Room2EditorScene from './Room2EditorScene'
import type { PlacedObject } from './Room2EditorScene'

// ── Command interface ────────────────────────────────────────────

export interface EditorCommand {
  execute(): void
  undo(): void
}

// ── Tile commands ────────────────────────────────────────────────

export class PlaceTileCommand implements EditorCommand {
  map: Phaser.Tilemaps.Tilemap
  col: number
  row: number
  newGid: number
  oldGid: number

  constructor(map: Phaser.Tilemaps.Tilemap, col: number, row: number, newGid: number, oldGid: number) {
    this.map = map
    this.col = col
    this.row = row
    this.newGid = newGid
    this.oldGid = oldGid
  }

  execute() {
    this.map.putTileAt(this.newGid, this.col, this.row, true, 'Ground')
  }

  undo() {
    this.map.putTileAt(this.oldGid, this.col, this.row, true, 'Ground')
  }
}

// ── Object commands ──────────────────────────────────────────────

export class PlaceObjectCommand implements EditorCommand {
  editor: Room2EditorScene
  layerName: string
  obj: PlacedObject

  constructor(editor: Room2EditorScene, layerName: string, obj: PlacedObject) {
    this.editor = editor
    this.layerName = layerName
    this.obj = obj
  }

  execute() {
    this.editor.addObjectToLayer(this.layerName, this.obj)
  }

  undo() {
    this.editor.removeObjectFromLayer(this.layerName, this.obj.id)
  }
}

export class DeleteObjectCommand implements EditorCommand {
  editor: Room2EditorScene
  layerName: string
  obj: PlacedObject

  constructor(editor: Room2EditorScene, layerName: string, obj: PlacedObject) {
    this.editor = editor
    this.layerName = layerName
    this.obj = { ...obj }
  }

  execute() {
    this.editor.removeObjectFromLayer(this.layerName, this.obj.id)
  }

  undo() {
    this.editor.addObjectToLayer(this.layerName, this.obj)
  }
}

export class MoveObjectCommand implements EditorCommand {
  editor: Room2EditorScene
  layerName: string
  objId: number
  oldX: number
  oldY: number
  newX: number
  newY: number

  constructor(
    editor: Room2EditorScene, layerName: string, objId: number,
    oldX: number, oldY: number, newX: number, newY: number,
  ) {
    this.editor = editor
    this.layerName = layerName
    this.objId = objId
    this.oldX = oldX
    this.oldY = oldY
    this.newX = newX
    this.newY = newY
  }

  execute() {
    this.editor.moveObjectInLayer(this.layerName, this.objId, this.newX, this.newY)
  }

  undo() {
    this.editor.moveObjectInLayer(this.layerName, this.objId, this.oldX, this.oldY)
  }
}

// ── Batch command (atomic undo for flood fill etc.) ─────────────

export class BatchCommand implements EditorCommand {
  commands: EditorCommand[]

  constructor(commands: EditorCommand[]) {
    this.commands = commands
  }

  execute() {
    for (const cmd of this.commands) cmd.execute()
  }

  undo() {
    for (let i = this.commands.length - 1; i >= 0; i--) {
      this.commands[i]!.undo()
    }
  }
}

// ── History manager ──────────────────────────────────────────────

const MAX_UNDO_STACK = 500

export class EditorHistory {
  undoStack: EditorCommand[] = []
  redoStack: EditorCommand[] = []

  execute(cmd: EditorCommand) {
    cmd.execute()
    this.undoStack.push(cmd)
    this.redoStack = []
    this.trimStack()
  }

  /** Push a command that was already executed (e.g. drag) */
  pushExecuted(cmd: EditorCommand) {
    this.undoStack.push(cmd)
    this.redoStack = []
    this.trimStack()
  }

  undo(): boolean {
    const cmd = this.undoStack.pop()
    if (!cmd) return false
    cmd.undo()
    this.redoStack.push(cmd)
    return true
  }

  redo(): boolean {
    const cmd = this.redoStack.pop()
    if (!cmd) return false
    cmd.execute()
    this.undoStack.push(cmd)
    return true
  }

  clear() {
    this.undoStack.length = 0
    this.redoStack.length = 0
  }

  get canUndo() { return this.undoStack.length > 0 }
  get canRedo() { return this.redoStack.length > 0 }

  private trimStack() {
    if (this.undoStack.length > MAX_UNDO_STACK) {
      this.undoStack.splice(0, this.undoStack.length - MAX_UNDO_STACK)
    }
  }
}
