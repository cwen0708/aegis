/**
 * usePushToTalk — MediaRecorder 按住說話錄音
 *
 * 注意：iOS Safari 不支援 `audio/webm;codecs=opus`，未來可用
 * `audio/mp4` fallback（MediaRecorder.isTypeSupported 偵測）。
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

const PREFERRED_MIME_TYPES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
  'audio/ogg;codecs=opus',
]

function pickMimeType(): string | null {
  if (typeof MediaRecorder === 'undefined') return null
  for (const mime of PREFERRED_MIME_TYPES) {
    if (MediaRecorder.isTypeSupported(mime)) return mime
  }
  return null
}

export function usePushToTalk(options: PushToTalkOptions) {
  const recording = ref(false)
  const lastError = ref<string | null>(null)

  let mediaRecorder: MediaRecorder | null = null
  let stream: MediaStream | null = null
  let chunks: Blob[] = []
  let activeMime = ''

  async function start() {
    if (recording.value) return
    lastError.value = null

    const mime = pickMimeType()
    if (!mime) {
      const msg = '此瀏覽器不支援錄音（MediaRecorder）'
      lastError.value = msg
      options.onError?.(msg)
      return
    }

    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (e) {
      const msg = e instanceof Error ? e.message : '無法取得麥克風權限'
      lastError.value = msg
      options.onError?.(`麥克風存取失敗：${msg}`)
      return
    }

    try {
      mediaRecorder = new MediaRecorder(stream, { mimeType: mime })
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      lastError.value = msg
      options.onError?.(`MediaRecorder 初始化失敗：${msg}`)
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
        const msg = e instanceof Error ? e.message : String(e)
        options.onError?.(`錄音資料處理失敗：${msg}`)
      } finally {
        cleanupStream()
        recording.value = false
      }
    }

    mediaRecorder.onerror = (event) => {
      const msg = (event as unknown as { error?: Error }).error?.message || '錄音發生錯誤'
      lastError.value = msg
      options.onError?.(msg)
    }

    try {
      mediaRecorder.start()
      recording.value = true
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      lastError.value = msg
      options.onError?.(`開始錄音失敗：${msg}`)
      cleanupStream()
    }
  }

  function stop() {
    if (!recording.value || !mediaRecorder) return
    try {
      if (mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop()
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      options.onError?.(`停止錄音失敗：${msg}`)
      cleanupStream()
      recording.value = false
    }
  }

  function cleanupStream() {
    if (stream) {
      stream.getTracks().forEach((t) => t.stop())
      stream = null
    }
    mediaRecorder = null
  }

  onUnmounted(() => {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      try {
        mediaRecorder.stop()
      } catch {
        // ignore
      }
    }
    cleanupStream()
  })

  return {
    recording,
    lastError,
    start,
    stop,
  }
}
