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
 *   - {"type":"transcript_partial","text":"...","seq":N}  — 即時 STT（可被覆蓋）
 *   - {"type":"transcript","text":"..."}                   — STT 最終文字（final）
 *   - {"type":"llm_partial","text":"..."}  — 單句字幕（streaming）
 *   - {"type":"llm_response","text":"..."} — 完整字幕（結尾）
 *   - Binary frames（MP3 chunks）
 *   - {"type":"audio_boundary"}            — 單句 TTS 結束（flush 播放）
 *   - {"type":"audio_end"}                 — 全部 TTS 結束
 *   - {"type":"error","error":"..."}
 */
import { ref, onUnmounted } from 'vue'
import { config } from '../config'

export type TalkState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'disconnected' | 'error'

export interface TalkSocketCallbacks {
  onState?: (state: TalkState) => void
  /** STT 最終文字（final commit 後一次性；streaming provider 可能在 audio_end 前到達） */
  onTranscript?: (text: string) => void
  /** STT 即時文字（interim），`seq` 單調遞增供前端去重 / 覆蓋顯示 */
  onTranscriptPartial?: (text: string, seq: number) => void
  onLlmPartial?: (text: string) => void
  onLlmResponse?: (text: string) => void
  onAudioEnd?: () => void
  onError?: (error: string) => void
  onOpen?: () => void
  onClose?: () => void
}

type ServerMessageType =
  | 'state'
  | 'transcript'
  | 'transcript_partial'
  | 'llm_partial'
  | 'llm_response'
  | 'audio_boundary'
  | 'audio_end'
  | 'error'

interface ServerMessage {
  type: ServerMessageType
  state?: TalkState
  text?: string
  seq?: number
  error?: string
}

export function useTalkSocket(memberSlug: string, callbacks: TalkSocketCallbacks) {
  const connected = ref(false)
  const lastError = ref<string | null>(null)

  let ws: WebSocket | null = null
  // 當前累積的 MP3 bytes（收到 audio_boundary 或 audio_end 時 flush 成一個 Blob）
  const audioChunks: Uint8Array[] = []
  // Blob URL 播放佇列（單執行緒循序播放）
  const playbackQueue: string[] = []
  let isPlaying = false
  let currentAudio: HTMLAudioElement | null = null
  // audio_end 已送達但播放佇列還沒空 → 最後一段播完才觸發 onAudioEnd
  let pendingFinalEnd = false

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
      case 'transcript_partial':
        if (msg.text) callbacks.onTranscriptPartial?.(msg.text, msg.seq ?? 0)
        break
      case 'llm_partial':
        if (msg.text) callbacks.onLlmPartial?.(msg.text)
        break
      case 'llm_response':
        if (msg.text) callbacks.onLlmResponse?.(msg.text)
        break
      case 'audio_boundary':
        // 單句 TTS 結束 → flush 當前累積成一個 Blob 進 playback queue
        flushChunksIntoQueue()
        if (!isPlaying) playNext()
        break
      case 'audio_end':
        // 全部 TTS 結束 → flush 殘留 + 標記結束，最後一段播完才觸發 onAudioEnd
        flushChunksIntoQueue()
        pendingFinalEnd = true
        if (!isPlaying) {
          if (playbackQueue.length > 0) {
            // 有未播的 Blob（剛 flush 進去）→ 開始播，播完才觸發 end
            playNext()
          } else {
            // 佇列已空（例如空回應）→ 立刻觸發 end
            pendingFinalEnd = false
            callbacks.onAudioEnd?.()
          }
        }
        // else: 正在播放，等 playNext 播完才觸發 end
        break
      case 'error':
        if (msg.error) {
          lastError.value = msg.error
          callbacks.onError?.(msg.error)
        }
        break
    }
  }

  function flushChunksIntoQueue() {
    if (audioChunks.length === 0) return
    // 把累積的 Uint8Array 合併成一個 ArrayBuffer，包成 Blob → 產生 URL 入佇列
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
    playbackQueue.push(url)
  }

  function playNext() {
    const url = playbackQueue.shift()
    if (!url) {
      isPlaying = false
      currentAudio = null
      if (pendingFinalEnd) {
        pendingFinalEnd = false
        callbacks.onAudioEnd?.()
      }
      return
    }
    isPlaying = true
    const audio = new Audio(url)
    currentAudio = audio
    audio.onended = () => {
      URL.revokeObjectURL(url)
      playNext()
    }
    audio.onerror = () => {
      URL.revokeObjectURL(url)
      callbacks.onError?.('音訊播放失敗')
      playNext()
    }
    void audio.play().catch((e) => {
      URL.revokeObjectURL(url)
      callbacks.onError?.(`音訊播放失敗：${e instanceof Error ? e.message : String(e)}`)
      playNext()
    })
  }

  function stopPlayback() {
    if (currentAudio) {
      try { currentAudio.pause() } catch { /* noop */ }
      currentAudio = null
    }
    for (const url of playbackQueue) URL.revokeObjectURL(url)
    playbackQueue.length = 0
    audioChunks.length = 0
    isPlaying = false
    pendingFinalEnd = false
  }

  /**
   * 中斷目前 TTS 播放並清空佇列（用於 barge-in — 使用者在 AI 說話中打斷）。
   * 與 stopPlayback() 相同，但公開給外部呼叫。
   */
  function clearPlaybackQueue() {
    stopPlayback()
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

  /** Streaming 模式：通知後端開始一段語音。前端接著持續 sendBinary PCM16 chunks。 */
  function startAudioStream(format = 'pcm16;rate=16000'): boolean {
    return sendJson({ type: 'audio_start', format })
  }

  /** Streaming 模式：送一個 PCM16 chunk（ArrayBuffer / Int16 buffer）。 */
  function sendAudioChunk(buffer: ArrayBuffer): boolean {
    return sendBinary(buffer)
  }

  /** Streaming 模式：通知後端語音結束（觸發 STT commit）。 */
  function endAudioStream(): boolean {
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
    stopPlayback()
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
    startAudioStream,
    sendAudioChunk,
    endAudioStream,
    clearPlaybackQueue,
  }
}
