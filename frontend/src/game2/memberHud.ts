export type HudStatus = 'idle' | 'running' | 'waiting' | 'error' | 'done'

export interface HudState {
  member_id: number
  step?: string
  status: HudStatus
}

export interface HudConfig {
  text: string
  color: number
  opacity: number
}

export function hudConfigFromState(state: HudState): HudConfig {
  const COLOR_MAP: Record<HudStatus, number> = {
    idle:    0x888888,
    running: 0x4ade80,
    waiting: 0xfbbf24,
    error:   0xef4444,
    done:    0x3b82f6,
  }
  const color = COLOR_MAP[state.status]
  const text = state.step ? `${state.status}: ${state.step}` : state.status
  const opacity = state.status === 'idle' ? 0.5 : 1.0
  return { text, color, opacity }
}
