/**
 * useVAD — Voice Activity Detection 自動斷句錄音
 *
 * 使用純 Web Audio API + RMS（Root Mean Square）音量偵測：
 *  - 按一次 start() 開啟「傾聽模式」，持續監聽麥克風音量
 *  - 音量 > threshold → 視為開始說話 → 啟動 MediaRecorder
 *  - 音量持續 < threshold 達 silenceDurationMs → 自動送出音訊 + 繼續監聽
 *  - 再次呼叫 stop() 關閉傾聽模式
 *
 * 選擇 Web Audio API 而非 ML-based VAD（如 @ricky0123/vad-web）：
 *  - 0 依賴，不增加 bundle size
 *  - 實作簡單，易於調校
 *  - 閾值可由呼叫端依現場調整
 *
 * iOS Safari 相容：
 *  - AudioContext 需要 user gesture 觸發 resume()
 *  - MediaRecorder mimeType 自動 fallback（與 usePushToTalk 一致）
 *
 * 不可變性 / 錯誤處理：
 *  - state 以 ref 暴露，不直接修改內部狀態物件
 *  - 錯誤皆透過 onError callback 傳出，並同步更新 lastError
 */
import { ref, onUnmounted } from 'vue'

export interface VADRecordedAudio {
  buffer: ArrayBuffer
  mimeType: string
}

export interface UseVADOptions {
  onSpeechStart?: () => void
  onSpeechEnd?: (audio: VADRecordedAudio) => void
  onError?: (message: string) => void
  /** 連續低於 threshold 多久判定為停頓（毫秒），預設 800ms */
  silenceDurationMs?: number
  /** RMS 音量閾值（0–1），預設 0.02 */
  threshold?: number
  /** 開始說話前，音量須連續高於 threshold 多久（毫秒），預設 100ms — 抗瞬時噪音 */
  speechOnsetMs?: number
  /** 單次錄音最短時長（毫秒），短於此值視為噪音丟棄，預設 300ms */
  minSpeechMs?: number
}

const PREFERRED_MIME_TYPES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
  'audio/ogg;codecs=opus',
] as const

function pickMimeType(): string | null {
  if (typeof MediaRecorder === 'undefined') return null
  for (const mime of PREFERRED_MIME_TYPES) {
    if (MediaRecorder.isTypeSupported(mime)) return mime
  }
  return null
}

function errorMessage(e: unknown): string {
  if (e instanceof Error) return e.message
  return typeof e === 'string' ? e : '未知錯誤'
}

export function useVAD(options: UseVADOptions) {
  const silenceDurationMs = options.silenceDurationMs ?? 800
  const threshold = options.threshold ?? 0.02
  const speechOnsetMs = options.speechOnsetMs ?? 100
  const minSpeechMs = options.minSpeechMs ?? 300

  const isListening = ref(false)
  const isSpeaking = ref(false)
  const currentVolume = ref(0)
  const lastError = ref<string | null>(null)

  // 內部可變狀態（閉包內，不暴露出去）
  let mediaStream: MediaStream | null = null
  let audioContext: AudioContext | null = null
  let analyser: AnalyserNode | null = null
  let sourceNode: MediaStreamAudioSourceNode | null = null
  let mediaRecorder: MediaRecorder | null = null
  let chunks: Blob[] = []
  let activeMime = ''
  let rafId: number | null = null

  // 定時器與時戳
  let silenceTimerId: number | null = null
  let onsetAboveSince: number | null = null
  let speechStartedAt: number | null = null
  // 下一次 onstop 觸發時是否丟棄（太短音訊視為噪音）
  let discardNextStop = false

  function setError(msg: string) {
    lastError.value = msg
    options.onError?.(msg)
  }

  function clearSilenceTimer() {
    if (silenceTimerId !== null) {
      window.clearTimeout(silenceTimerId)
      silenceTimerId = null
    }
  }

  function computeRms(data: Uint8Array): number {
    // getByteFrequencyData 回傳 0–255，轉為 0–1 RMS
    let sumSq = 0
    for (let i = 0; i < data.length; i++) {
      const v = data[i] ?? 0
      sumSq += v * v
    }
    const rms = Math.sqrt(sumSq / data.length) / 255
    return rms
  }

  function beginRecordingSegment() {
    if (!mediaRecorder || mediaRecorder.state !== 'inactive') return
    chunks = []
    speechStartedAt = performance.now()
    try {
      mediaRecorder.start()
      isSpeaking.value = true
      options.onSpeechStart?.()
    } catch (e) {
      setError(`開始錄音失敗：${errorMessage(e)}`)
    }
  }

  function endRecordingSegment() {
    if (!mediaRecorder || mediaRecorder.state === 'inactive') return
    try {
      mediaRecorder.stop()
    } catch (e) {
      setError(`停止錄音失敗：${errorMessage(e)}`)
    }
  }

  function monitorVolume() {
    if (!isListening.value || !analyser) {
      rafId = null
      return
    }
    const data = new Uint8Array(analyser.frequencyBinCount)
    analyser.getByteFrequencyData(data)
    const rms = computeRms(data)
    currentVolume.value = rms

    const now = performance.now()

    if (rms > threshold) {
      // 聲音夠大
      if (!isSpeaking.value) {
        // 還沒開始錄 → 檢查是否已連續夠久（抗瞬時噪音）
        if (onsetAboveSince === null) {
          onsetAboveSince = now
        } else if (now - onsetAboveSince >= speechOnsetMs) {
          beginRecordingSegment()
          onsetAboveSince = null
        }
      } else {
        // 錄音中 → 重置靜音計時器
        clearSilenceTimer()
      }
    } else {
      // 聲音低於閾值
      onsetAboveSince = null
      if (isSpeaking.value && silenceTimerId === null) {
        silenceTimerId = window.setTimeout(() => {
          silenceTimerId = null
          // 檢查錄音時長：太短視為噪音，丟棄
          const duration = speechStartedAt !== null ? performance.now() - speechStartedAt : 0
          if (duration < minSpeechMs) {
            // 短於最小語音長度 → 標記丟棄後停止，onstop 會跳過送出
            discardNextStop = true
          }
          endRecordingSegment()
        }, silenceDurationMs)
      }
    }

    rafId = requestAnimationFrame(monitorVolume)
  }

  async function start(): Promise<void> {
    if (isListening.value) return
    lastError.value = null

    const mime = pickMimeType()
    if (!mime) {
      setError('此瀏覽器不支援錄音（MediaRecorder）')
      return
    }

    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (e) {
      setError(`麥克風存取失敗：${errorMessage(e)}`)
      return
    }

    try {
      // iOS Safari 需要在 user gesture 下建立並 resume
      const AudioCtx: typeof AudioContext =
        window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      audioContext = new AudioCtx()
      if (audioContext.state === 'suspended') {
        await audioContext.resume()
      }
      sourceNode = audioContext.createMediaStreamSource(mediaStream)
      analyser = audioContext.createAnalyser()
      analyser.fftSize = 512
      analyser.smoothingTimeConstant = 0.3
      sourceNode.connect(analyser)
    } catch (e) {
      setError(`音訊分析初始化失敗：${errorMessage(e)}`)
      cleanup()
      return
    }

    try {
      mediaRecorder = new MediaRecorder(mediaStream, { mimeType: mime })
    } catch (e) {
      setError(`MediaRecorder 初始化失敗：${errorMessage(e)}`)
      cleanup()
      return
    }

    activeMime = mime

    mediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunks.push(e.data)
    }

    mediaRecorder.onstop = async () => {
      const shouldDiscard = discardNextStop
      discardNextStop = false
      try {
        if (!shouldDiscard) {
          const blob = new Blob(chunks, { type: activeMime })
          if (blob.size > 0) {
            const buffer = await blob.arrayBuffer()
            options.onSpeechEnd?.({ buffer, mimeType: activeMime })
          }
        }
      } catch (e) {
        setError(`錄音資料處理失敗：${errorMessage(e)}`)
      } finally {
        chunks = []
        isSpeaking.value = false
        speechStartedAt = null
        // stop() 已被呼叫且不再監聽 → 最終清理
        if (!isListening.value) {
          cleanup()
        }
      }
    }

    mediaRecorder.onerror = (event) => {
      const err = (event as unknown as { error?: Error }).error
      setError(`錄音發生錯誤：${err?.message || '未知'}`)
    }

    isListening.value = true
    isSpeaking.value = false
    onsetAboveSince = null
    speechStartedAt = null
    clearSilenceTimer()
    monitorVolume()
  }

  function stop(): void {
    if (!isListening.value) return
    isListening.value = false

    if (rafId !== null) {
      cancelAnimationFrame(rafId)
      rafId = null
    }
    clearSilenceTimer()

    // 如果正在錄音，先嘗試送出當下這段
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      try {
        mediaRecorder.stop()
      } catch {
        // ignore — onstop 會在後續觸發
      }
    } else {
      // 立即清理
      cleanup()
    }
  }

  function cleanup() {
    if (mediaStream) {
      mediaStream.getTracks().forEach((t) => t.stop())
      mediaStream = null
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
    analyser = null
    mediaRecorder = null
    chunks = []
    isSpeaking.value = false
    currentVolume.value = 0
    onsetAboveSince = null
    speechStartedAt = null
    clearSilenceTimer()
  }

  onUnmounted(() => {
    if (isListening.value) {
      stop()
    }
    cleanup()
  })

  return {
    isListening,
    isSpeaking,
    currentVolume,
    lastError,
    start,
    stop,
  }
}
