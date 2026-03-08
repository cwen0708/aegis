// ── Ground Types ─────────────────────────────────────────────
export const GroundType = {
  VOID: 0,
  WALL: 1,
  FLOOR: 2,
  WOOD: 3,
  DARK: 4,
  MARBLE: 5,
  STONE: 6,
  BEIGE: 7,
  BAMBOO: 8,
  CHECKER: 9,
  CARPET: 10,
  RED: 11,
  LAVENDER: 12,
  // Wall styles — 4 groups, each uses a pair of spritesheet rows
  // (Row A = decorative front face, Row B = exterior back face)
  WALL_MARBLE: 13,  // rows 5+6  大理石
  WALL_GRAY: 14,    // rows 7+8  灰
  WALL_BRICK: 15,   // rows 9+10 磚
  WALL_PINK: 16,    // rows 11+12 粉
} as const
export type GroundType = (typeof GroundType)[keyof typeof GroundType]

/** Check if a ground type is any wall variant */
export function isWall(gt: number): boolean {
  return gt === GroundType.WALL || (gt >= GroundType.WALL_MARBLE && gt <= GroundType.WALL_PINK)
}



// ── Layout Data ──────────────────────────────────────────────
export interface FurnitureItem {
  id: string
  type: string
  col: number
  row: number
}

export interface RoomDef {
  name: string
  rMin: number
  rMax: number
  cMin: number
  cMax: number
}

export interface WorkstationDef {
  deskId: string
  chairId: string
  monitorId?: string
}

// Simple work slot: position + direction + optional monitor
export type SlotDirection = 'down' | 'left' | 'right' | 'up'

export interface WorkSlot {
  col: number
  row: number
  dir?: SlotDirection  // 工作時面向的方向，預設 'up'
  monitorId?: string
}

export interface OfficeLayout {
  version: 1
  cols: number
  rows: number
  ground: number[] // flat row-major, length = cols * rows
  furniture: FurnitureItem[]
  props: FurnitureItem[]
  rooms: RoomDef[]
  workstations: WorkstationDef[]
  slots?: WorkSlot[]  // Simple slot positions (optional, fallback to workstations)
}

// ── Editor Layer ─────────────────────────────────────────────
export type EditorLayer = 'ground' | 'wall' | 'furniture' | 'props' | 'slots'
