import { onMounted, onUnmounted } from 'vue'
import { useAegisStore } from '../stores/aegis'

let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let refCount = 0

// HMR cleanup: close ghost connections on module reload
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws) {
      ws.close()
      ws = null
    }
    refCount = 0
  })
}

export function useWebSocket() {
  const store = useAegisStore()

  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return
    }

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const host = window.location.host
    const wsUrl = `${protocol}://${host}/ws`

    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      store.setConnected(true)
      if (reconnectTimer) {
        clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        handleMessage(msg)
      } catch (e) {
        console.error('[WS] Parse error:', e)
      }
    }

    ws.onclose = () => {
      store.setConnected(false)
      ws = null
      scheduleReconnect()
    }

    ws.onerror = () => {
      // onclose will fire after onerror
    }
  }

  function disconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws) {
      ws.close()
      ws = null
    }
    store.setConnected(false)
  }

  function scheduleReconnect() {
    if (reconnectTimer) return
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      connect()
    }, 3000)
  }

  function handleMessage(msg: any) {
    const { type, data } = msg

    switch (type) {
      case 'running_tasks_update':
        store.updateRunningTasks(data)
        break

      case 'system_info_update':
        store.updateSystemInfo(data)
        break

      case 'task_started':
        store.addToast(`任務開始：${data.card_title || data.card_id}`, 'info')
        // 觸發看板重新整理的事件
        window.dispatchEvent(new CustomEvent('aegis:task-event', { detail: { type: 'started', ...data } }))
        break

      case 'task_completed':
        store.addToast(`任務完成：Card #${data.card_id}`, 'success')
        window.dispatchEvent(new CustomEvent('aegis:task-event', { detail: { type: 'completed', ...data } }))
        break

      case 'task_failed':
        store.addToast(`任務失敗：Card #${data.card_id}`, 'error')
        window.dispatchEvent(new CustomEvent('aegis:task-event', { detail: { type: 'failed', ...data } }))
        break

      case 'task_log':
        store.appendTaskLog(data.card_id, data.line)
        break
    }
  }

  // 使用 ref counting 確保只有一個 WebSocket 連線
  onMounted(() => {
    refCount++
    if (refCount === 1) {
      connect()
    }
  })

  onUnmounted(() => {
    refCount--
    if (refCount === 0) {
      disconnect()
    }
  })

  return {
    connect,
    disconnect,
  }
}
