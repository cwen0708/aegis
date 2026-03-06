# WebSocket Events

Connect to: `ws://localhost:8899/ws`

## Server → Client Events

| Event | Description | Payload |
|-------|-------------|---------|
| `running_tasks_update` | All running tasks (every 5s) | `{ tasks: [...] }` |
| `system_info_update` | CPU/RAM/slots/paused (every 5s) | `{ cpu, ram, slots, paused }` |
| `task_started` | Card execution began | `{ card_id, member_id }` |
| `task_completed` | Card finished successfully | `{ card_id, duration_ms }` |
| `task_failed` | Card execution failed | `{ card_id, error }` |
| `task_log` | Stdout line from AI subprocess | `{ card_id, line }` |

## Task Execution Flow

```
User moves card to "Planning"
        ↓
Card status → "pending"
        ↓
Poller (1s interval) picks up pending card
        ↓
Runner acquires semaphore slot (max 3)
        ↓
Spawns CLI subprocess (Claude/Gemini) in project path
        ↓
Streams stdout → WebSocket → Frontend terminal
        ↓
Completion → updates card status → broadcasts event
        ↓
Frontend auto-refreshes board + shows toast
```

## Frontend Usage

```typescript
import { useWebSocket } from '@/composables/useWebSocket'

const { connect, subscribe, unsubscribe } = useWebSocket()

// Connect on mount
connect()

// Subscribe to events
subscribe('task_completed', (data) => {
  console.log('Task completed:', data.card_id)
})

// Unsubscribe when done
unsubscribe('task_completed')
```
