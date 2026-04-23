import { flowEdgeColor, flowEdgePosition } from '../flowEdge'
import type { FlowEdgeState, Point2D } from '../flowEdge'

declare const process: { exit(code: number): never }

function assertEqual<T>(actual: T, expected: T, name: string) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected)
  console.log(ok ? `[PASS] ${name}` : `[FAIL] ${name}: got ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)}`)
  if (!ok) process.exit(1)
}

function makeState(status: FlowEdgeState['status']): FlowEdgeState {
  return { from_member_id: 1, to_member_id: 2, status, progress: 0 }
}

// Case 1: 4 種 status 各自顏色
assertEqual(flowEdgeColor(makeState('pending')),      0x888888, 'color pending')
assertEqual(flowEdgeColor(makeState('transferring')), 0x4ade80, 'color transferring')
assertEqual(flowEdgeColor(makeState('done')),         0x3b82f6, 'color done')
assertEqual(flowEdgeColor(makeState('error')),        0xef4444, 'color error')

// Case 2: 線性插值 progress=0 / 1 / 0.5
assertEqual(
  flowEdgePosition({ x: 0, y: 0 }, { x: 100, y: 0 }, 0),
  { x: 0, y: 0 },
  'position progress=0',
)
assertEqual(
  flowEdgePosition({ x: 0, y: 0 }, { x: 100, y: 0 }, 1),
  { x: 100, y: 0 },
  'position progress=1',
)
assertEqual(
  flowEdgePosition({ x: 0, y: 0 }, { x: 100, y: 0 }, 0.5),
  { x: 50, y: 0 },
  'position progress=0.5',
)

// Case 3: progress 超出範圍 clamp 到 [0,1]
assertEqual(
  flowEdgePosition({ x: 0, y: 0 }, { x: 100, y: 0 }, -0.5),
  { x: 0, y: 0 },
  'position progress=-0.5 clamp to 0',
)
assertEqual(
  flowEdgePosition({ x: 0, y: 0 }, { x: 100, y: 0 }, 1.5),
  { x: 100, y: 0 },
  'position progress=1.5 clamp to 1',
)

// Case 4: 不 mutate 入參
const fromPt: Point2D = { x: 10, y: 20 }
const toPt: Point2D = { x: 30, y: 40 }
const fromBefore = JSON.stringify(fromPt)
const toBefore = JSON.stringify(toPt)
flowEdgePosition(fromPt, toPt, 0.7)
assertEqual(JSON.stringify(fromPt), fromBefore, 'from not mutated')
assertEqual(JSON.stringify(toPt), toBefore, 'to not mutated')

console.log('All checks passed.')
