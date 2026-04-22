import { hudConfigFromState } from '../memberHud'

declare const process: { exit(code: number): never }

function assertEqual<T>(actual: T, expected: T, name: string) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected)
  console.log(ok ? `[PASS] ${name}` : `[FAIL] ${name}: got ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)}`)
  if (!ok) process.exit(1)
}

// Case 1: idle + no step
assertEqual(
  hudConfigFromState({ member_id: 1, status: 'idle' }),
  { text: 'idle', color: 0x888888, opacity: 0.5 },
  'idle without step',
)

// Case 2: running + step
assertEqual(
  hudConfigFromState({ member_id: 1, status: 'running', step: 'tool_use:Read' }),
  { text: 'running: tool_use:Read', color: 0x4ade80, opacity: 1.0 },
  'running with step',
)

// Case 3: error
assertEqual(
  hudConfigFromState({ member_id: 2, status: 'error', step: 'retry' }),
  { text: 'error: retry', color: 0xef4444, opacity: 1.0 },
  'error with step',
)

// Case 4: all statuses have defined color
const statuses: Array<'idle' | 'running' | 'waiting' | 'error' | 'done'> = ['idle', 'running', 'waiting', 'error', 'done']
for (const s of statuses) {
  const cfg = hudConfigFromState({ member_id: 1, status: s })
  assertEqual(typeof cfg.color === 'number' && cfg.color > 0, true, `status=${s} has color`)
}

console.log('All checks passed.')
