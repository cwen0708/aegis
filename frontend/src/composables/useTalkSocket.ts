/**
 * useTalkSocket — 與後端 /api/v1/ws/talk/{memberSlug} 進行語音對話
 *
 * Client → Server:
 *   - {"type":"audio_start","format":"audio/webm;codecs=opus"}
 *   - Binary: audio bytes
 *   - {"type":"audio_end"}
 *   - {"type":"text_input","text":"..."}
 *
 * Server → Client:
 *   - {"type":"state","state":"idle|listening|thinking|speaking"}
 *   - {"type":"transcript","text":"..."}
 *   - {"type":"llm_response","text":"..."}
 *   - Binary frames（MP3 chunks）
 *   - {"type":"audio_end"}
 *   - {"type":"error","error":"..."}
 */
import { ref, onUnmounted } from 'vue'
import { config } from '../config'

export type TalkState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'disconnected' | 'error'

export interface TalkSocketCallbacks {
  onState?: (state: TalkState) => void
  onTranscript?: (text: string) => void
  onLlmResponse?: (text: string) => void
  onAudioEnd?: () => void
  onError?: (error: string) => void
  onOpen?: () => void
  onClose?: () => void
}

interface ServerMessage {
  type: 'state' | 'transcript' | 'llm_response' | 'audio_end' | 'error'
  state?: TalkState
  text?: string
  error?: string
}

export function useTalkSocket(memberSlug: string, callbacks: TalkSocketCallbacks) {
  const connected = ref(false)
  const lastError = ref<string | null>(null)

  let ws: WebSocket | null = null
  const audioChunks: Uint8Array[] = []

  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return
    }

    const token = localStorage.getItem('aegis-token') || ''
    const qs = token ? `?token=${encodeURIComponent(token)}` : ''
    const url = `${config.wsUrl}/api/v1/ws/talk/${encodeURIComponent(memberSlug)}${qs}`

    ws = new WebSocket(url)
    ws.binaryType = 'arraybuffer'

    ws.onopen = () => {
      connected.value = true
      lastError.value = null
      callbacks.onOpen?.()
    }

    ws.onmessage = (event) => {
      if (typeof event.data === 'string') {
        try {
          const msg = JSON.parse(event.data) as ServerMessage
          handleJson(msg)
        } catch (e) {
          console.error('[TalkWS] Parse error:', e)
        }
      } else {
        // Binary MP3 chunk
        audioChunks.push(new Uint8Array(event.data as ArrayBuffer))
      }
    }

    ws.onclose = () => {
      connected.value = false
      callbacks.onClose?.()
    }

    ws.onerror = () => {
      lastError.value = 'WebSocket 連線錯誤'
      callbacks.onError?.(lastError.value)
    }
  }

  function handleJson(msg: ServerMessage) {
    switch (msg.type) {
      case 'state':
        if (msg.state) callbacks.onState?.(msg.state)
        break
      case 'transcript':
        if (msg.text) callbacks.onTranscript?.(msg.text)
        break
      case 'llm_response':
        if (msg.text) callbacks.onLlmResponse?.(msg.text)
        break
      case 'audio_end':
        flushAudioAndPlay()
        break
      case 'error':
        if (msg.error) {
          lastError.value = msg.error
          callbacks.onError?.(msg.error)
        }
        break
    }
  }

  function flushAudioAndPlay() {
    if (audioChunks.length === 0) {
      callbacks.onAudioEnd?.()
      return
    }
    // Concat Uint8Array chunks into a single ArrayBuffer to avoid TS BlobPart
    // issues with SharedArrayBuffer-backed typed arrays.
    const totalLen = audioChunks.reduce((acc, c) => acc + c.byteLength, 0)
    const merged = new Uint8Array(new ArrayBuffer(totalLen))
    let offset = 0
    for (const chunk of audioChunks) {
      merged.set(chunk, offset)
      offset += chunk.byteLength
    }
    audioChunks.length = 0
    const blob = new Blob([merged.buffer as ArrayBuffer], { type: 'audio/mpeg' })
    const url = URL.createObjectURL(blob)
    const audio = new Audio(url)
    audio.onended = () => {
      URL.revokeObjectURL(url)
      callbacks.onAudioEnd?.()
    }
    audio.onerror = () => {
      URL.revokeObjectURL(url)
      callbacks.onError?.('音訊播放失敗')
      callbacks.onAudioEnd?.()
    }
    void audio.play().catch((e) => {
      callbacks.onError?.(`音訊播放失敗：${e instanceof Error ? e.message : String(e)}`)
      callbacks.onAudioEnd?.()
    })
  }

  function sendJson(data: Record<string, unknown>): boolean {
    if (!ws || ws.readyState !== WebSocket.OPEN) return false
    ws.send(JSON.stringify(data))
    return true
  }

  function sendBinary(buffer: ArrayBuffer): boolean {
    if (!ws || ws.readyState !== WebSocket.OPEN) return false
    ws.send(buffer)
    return true
  }

  function sendAudio(buffer: ArrayBuffer, format: string): boolean {
    if (!sendJson({ type: 'audio_start', format })) return false
    if (!sendBinary(buffer)) return false
    return sendJson({ type: 'audio_end' })
  }

  function sendText(text: string): boolean {
    const trimmed = text.trim()
    if (!trimmed) return false
    return sendJson({ type: 'text_input', text: trimmed })
  }

  function disconnect() {
    if (ws) {
      ws.close()
      ws = null
    }
    audioChunks.length = 0
    connected.value = false
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    connected,
    lastError,
    connect,
    disconnect,
    sendAudio,
    sendText,
  }
}
