/**
 * usePushToTalk — 按住說話錄音，兩種模式：
 *   1. MediaRecorder（webm/opus 整段）— Gemini STT 路徑
 *   2. PCM16 AudioWorklet streaming — ElevenLabs/Deepgram Realtime STT 路徑
 *
 * 由呼叫端依 `stt_provider` 決定用 `start()` / `stop()`（MediaRecorder）
 * 還是 `startPCM16(onChunk)` / `stop()`（streaming）。
 *
 * iOS Safari：不支援 `audio/webm;codecs=opus`，可 fallback `audio/mp4`；
 * AudioWorkletNode 自 Safari 14.1+ 起支援。
 */
import { ref, onUnmounted } from 'vue'

export interface RecordedAudio {
  buffer: ArrayBuffer
  mimeType: string
}

export interface PushToTalkOptions {
  onRecorded: (audio: RecordedAudio) => void
  onError?: (message: string) => void
}

export type PCM16ChunkCallback = (buffer: ArrayBuffer) => void

const PREFERRED_MIME_TYPES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
  'audio/ogg;codecs=opus',
]

const PCM16_WORKLET_URL = '/worklets/pcm16-processor.js'
const PCM16_SAMPLE_RATE = 16000

function pickMimeType(): string | null {
  if (typeof MediaRecorder === 'undefined') return null
  for (const mime of PREFERRED_MIME_TYPES) {
    if (MediaRecorder.isTypeSupported(mime)) return mime
  }
  return null
}

function errorMessage(e: unknown): string {
  if (e instanceof Error) return e.message
  return typeof e === 'string' ? e : String(e)
}

export function usePushToTalk(options: PushToTalkOptions) {
  const recording = ref(false)
  const lastError = ref<string | null>(null)
  const mode = ref<'idle' | 'media-recorder' | 'pcm16'>('idle')

  // MediaRecorder 狀態
  let mediaRecorder: MediaRecorder | null = null
  let stream: MediaStream | null = null
  let chunks: Blob[] = []
  let activeMime = ''

  // PCM16 streaming 狀態
  let audioContext: AudioContext | null = null
  let sourceNode: MediaStreamAudioSourceNode | null = null
  let workletNode: AudioWorkletNode | null = null
  let pcm16Callback: PCM16ChunkCallback | null = null

  function setError(msg: string) {
    lastError.value = msg
    options.onError?.(msg)
  }

  // ─── Mode 1: MediaRecorder（webm/opus 整段）─────────────────

  async function start() {
    if (recording.value) return
    lastError.value = null

    const mime = pickMimeType()
    if (!mime) {
      setError('此瀏覽器不支援錄音（MediaRecorder）')
      return
    }

    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (e) {
      setError(`麥克風存取失敗：${errorMessage(e)}`)
      return
    }

    try {
      mediaRecorder = new MediaRecorder(stream, { mimeType: mime })
    } catch (e) {
      setError(`MediaRecorder 初始化失敗：${errorMessage(e)}`)
      cleanupStream()
      return
    }

    activeMime = mime
    chunks = []

    mediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunks.push(e.data)
    }

    mediaRecorder.onstop = async () => {
      try {
        const blob = new Blob(chunks, { type: activeMime })
        const buffer = await blob.arrayBuffer()
        if (buffer.byteLength > 0) {
          options.onRecorded({ buffer, mimeType: activeMime })
        }
      } catch (e) {
        setError(`錄音資料處理失敗：${errorMessage(e)}`)
      } finally {
        cleanupStream()
        recording.value = false
        mode.value = 'idle'
      }
    }

    mediaRecorder.onerror = (event) => {
      const err = (event as unknown as { error?: Error }).error
      setError(err?.message || '錄音發生錯誤')
    }

    try {
      mediaRecorder.start()
      recording.value = true
      mode.value = 'media-recorder'
    } catch (e) {
      setError(`開始錄音失敗：${errorMessage(e)}`)
      cleanupStream()
    }
  }

  // ─── Mode 2: PCM16 AudioWorklet streaming ─────────────────

  async function startPCM16(onChunk: PCM16ChunkCallback): Promise<void> {
    if (recording.value) return
    lastError.value = null
    pcm16Callback = onChunk

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      })
    } catch (e) {
      setError(`麥克風存取失敗：${errorMessage(e)}`)
      pcm16Callback = null
      return
    }

    try {
      const AudioCtx: typeof AudioContext =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      audioContext = new AudioCtx({ sampleRate: PCM16_SAMPLE_RATE })
      if (audioContext.state === 'suspended') {
        await audioContext.resume()
      }

      await audioContext.audioWorklet.addModule(PCM16_WORKLET_URL)

      sourceNode = audioContext.createMediaStreamSource(stream)
      workletNode = new AudioWorkletNode(audioContext, 'pcm16-processor', {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        outputChannelCount: [1],
      })
      workletNode.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        if (event.data && pcm16Callback) {
          pcm16Callback(event.data)
        }
      }
      // worklet 必須連到 destination（或其他 node）才會被 process
      sourceNode.connect(workletNode)
      workletNode.connect(audioContext.destination)
    } catch (e) {
      setError(`PCM16 streaming 初始化失敗：${errorMessage(e)}`)
      cleanupPCM16()
      return
    }

    recording.value = true
    mode.value = 'pcm16'
  }

  function stop() {
    if (!recording.value) return
    if (mode.value === 'media-recorder' && mediaRecorder) {
      try {
        if (mediaRecorder.state !== 'inactive') {
          mediaRecorder.stop()
        }
      } catch (e) {
        setError(`停止錄音失敗：${errorMessage(e)}`)
        cleanupStream()
        recording.value = false
        mode.value = 'idle'
      }
      return
    }
    if (mode.value === 'pcm16') {
      cleanupPCM16()
      recording.value = false
      mode.value = 'idle'
    }
  }

  function cleanupStream() {
    if (stream) {
      stream.getTracks().forEach((t) => t.stop())
      stream = null
    }
    mediaRecorder = null
  }

  function cleanupPCM16() {
    pcm16Callback = null
    if (workletNode) {
      try {
        workletNode.port.onmessage = null
        workletNode.disconnect()
      } catch {
        // ignore
      }
      workletNode = null
    }
    if (sourceNode) {
      try {
        sourceNode.disconnect()
      } catch {
        // ignore
      }
      sourceNode = null
    }
    if (audioContext) {
      audioContext.close().catch(() => {
        // ignore
      })
      audioContext = null
    }
    cleanupStream()
  }

  onUnmounted(() => {
    if (mode.value === 'media-recorder' && mediaRecorder && mediaRecorder.state !== 'inactive') {
      try {
        mediaRecorder.stop()
      } catch {
        // ignore
      }
    }
    if (mode.value === 'pcm16') {
      cleanupPCM16()
    } else {
      cleanupStream()
    }
  })

  return {
    recording,
    lastError,
    mode,
    start,
    startPCM16,
    stop,
  }
}
