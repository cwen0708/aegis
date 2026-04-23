export type FlowEdgeStatus = 'pending' | 'transferring' | 'done' | 'error'

export interface FlowEdgeState {
  from_member_id: number
  to_member_id: number
  status: FlowEdgeStatus
  progress: number
}

export interface Point2D {
  x: number
  y: number
}

export function flowEdgeColor(state: FlowEdgeState): number {
  const COLOR_MAP: Record<FlowEdgeStatus, number> = {
    pending:      0x888888,
    transferring: 0x4ade80,
    done:         0x3b82f6,
    error:        0xef4444,
  }
  return COLOR_MAP[state.status]
}

export function flowEdgePosition(from: Point2D, to: Point2D, progress: number): Point2D {
  const t = progress < 0 ? 0 : progress > 1 ? 1 : progress
  return {
    x: from.x + (to.x - from.x) * t,
    y: from.y + (to.y - from.y) * t,
  }
}
