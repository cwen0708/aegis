import {
  GroundType,
  type OfficeLayout, type FurnitureItem, type WorkstationDef, type WorkSlot,
} from './types'

const COLS = 32
const ROWS = 22

// ── Build default layout (migrated from old buildLayout) ─────
export function buildDefaultLayout(deskCount: number): OfficeLayout {
  const ground = new Array(COLS * ROWS).fill(GroundType.FLOOR)

  function setGround(r: number, c: number, type: GroundType) {
    ground[r * COLS + c] = type
  }

  // Internal dividers
  const divCol = 20
  const divRow = 10

  for (let r = 0; r <= divRow; r++) setGround(r, divCol, GroundType.WALL)
  for (let c = 0; c <= divCol; c++) setGround(divRow, c, GroundType.WALL)
  for (let r = 13; r < ROWS; r++) setGround(r, divCol, GroundType.WALL)
  for (let c = divCol; c < COLS; c++) setGround(12, c, GroundType.WALL)

  // Doorways
  for (let r = 5; r <= 7; r++) setGround(r, divCol, GroundType.FLOOR)
  for (let c = 9; c <= 11; c++) setGround(divRow, c, GroundType.FLOOR)
  for (let c = 25; c <= 27; c++) setGround(12, c, GroundType.FLOOR)
  for (let r = 16; r <= 18; r++) setGround(r, divCol, GroundType.FLOOR)

  // Furniture
  const furniture: FurnitureItem[] = []
  const props: FurnitureItem[] = []
  const workstations: WorkstationDef[] = []
  let fIdx = 0
  let pIdx = 0

  function addF(type: string, col: number, row: number): string {
    const id = `f_${String(fIdx++).padStart(3, '0')}`
    furniture.push({ id, type, col, row })
    return id
  }
  function addP(type: string, col: number, row: number): string {
    const id = `p_${String(pIdx++).padStart(3, '0')}`
    props.push({ id, type, col, row })
    return id
  }

  // === WORK ROOM ===
  const maxDesksPerRow = 4
  const actualDesks = Math.min(deskCount, maxDesksPerRow * 2)

  for (let i = 0; i < actualDesks; i++) {
    const rowIdx = Math.floor(i / maxDesksPerRow)
    const colIdx = i % maxDesksPerRow
    const dc = 1 + colIdx * 4
    const dr = rowIdx === 0 ? 1 : 5

    const deskId = addF('desk', dc, dr)
    const monId = addP('monitor', dc, dr)
    const chairId = addF('chair', dc, dr + 3)
    workstations.push({ deskId, chairId, monitorId: monId })
  }

  addF('divider_tl', 1, 0)
  addF('divider_tm', 3, 0)
  addF('divider_tm', 5, 0)
  addF('divider_tr', 7, 0)
  addF('plant_tall', 0, 0)
  addF('plant_tall', 18, 0)
  addF('copier', 17, 7)
  addF('printer', 15, 7)
  addF('plant', 0, 8)

  // === MEETING ROOM ===
  addF('screen_tv', 25, 0)
  addF('board_cork', 28, 0)
  addF('desk_gray', 23, 3)
  addF('desk_gray', 26, 3)
  addF('desk_gray', 23, 6)
  addF('desk_gray', 26, 6)
  addF('chair', 22, 4)
  addF('chair_back', 25, 4)
  addF('chair', 28, 4)
  addF('chair', 22, 7)
  addF('chair_back', 25, 7)
  addF('chair', 28, 7)
  addF('plant', 21, 0)
  addF('plant', 30, 0)
  addF('plant_big', 30, 9)
  addF('bookshelf', 21, 8)
  addP('phone', 29, 3)

  // === BREAK ROOM ===
  addF('sofa', 2, 12)
  addF('sofa', 4, 12)
  addF('sofa', 2, 16)
  addF('sofa', 4, 16)
  addF('vending', 16, 11)
  addF('copier', 14, 11)
  addF('shelf', 12, 11)
  addF('plant', 0, 11)
  addF('plant_big', 0, 15)
  addF('plant_bush', 18, 19)
  addF('plant', 0, 19)
  addF('desk', 8, 14)
  addF('chair', 8, 17)
  addF('chair', 10, 17)
  addP('laptop', 8, 14)
  addF('board', 10, 11)

  // === LOUNGE ===
  addF('bookshelf', 29, 13)
  addF('bookshelf2', 29, 16)
  addF('cabinet', 27, 13)
  addF('plant', 21, 13)
  addF('plant_big', 21, 19)
  addF('plant_bush', 29, 19)
  addF('sofa', 23, 15)
  addF('sofa', 25, 15)
  addF('sofa', 23, 18)
  addF('desk_gray', 23, 13)
  addP('laptop', 23, 13)
  addF('chair_exec', 25, 14)
  addF('server', 27, 16)

  const rooms = [
    { name: 'BREAK ROOM', rMin: 11, rMax: ROWS - 1, cMin: 0, cMax: 19 },
    { name: 'LOUNGE', rMin: 13, rMax: ROWS - 1, cMin: 21, cMax: COLS - 1 },
  ]

  // Define 4 work slots directly (col, row = chair position)
  const slots = [
    { col: 2, row: 5 },   // desk 1
    { col: 6, row: 5 },   // desk 2
    { col: 10, row: 5 },  // desk 3
    { col: 14, row: 5 },  // desk 4
  ]

  // Link monitors to slots
  slots.forEach((slot, i) => {
    if (workstations[i]?.monitorId) {
      slot.monitorId = workstations[i].monitorId
    }
  })

  return {
    version: 1,
    cols: COLS,
    rows: ROWS,
    ground,
    furniture,
    props,
    rooms,
    workstations,
    slots,
  }
}
