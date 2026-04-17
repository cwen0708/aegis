/**
 * useAmbientBgm — AI Thinking 背景音樂（Web Audio + GainNode 淡入淡出）
 *
 * 用途：
 * - Talk 頁在 `thinking` 持續 3 秒 + playback queue 為空時淡入
 * - TTS 音訊到達時 duck（降音量，不停止）
 * - TTS 結束仍 thinking 時 resume（淡入回原音量）
 * - 回 idle / 卸載時淡出停止
 *
 * iOS Safari 解鎖：
 * - `unlock()` 必須在 user gesture click handler 同步鏈第一行呼叫
 * - 內部做 `audioCtx.resume()` + 每個 <audio> 元素 play().pause()
 *
 * Graceful fail：
 * - 即使音檔不存在（404）也不報錯，變 no-op
 * - 使用者可透過 `talk_bgm_enabled` SystemSetting 關閉整個功能
 */
import { ref } from 'vue'

export interface UseAmbientBgmOptions {
  /** 音量上限（0-1），預設 0.25 避免蓋過 TTS */
  maxVolume?: number
  /** 音檔 URL 清單；預設 3 首 ambient */
  tracks?: string[]
}

type BgmState = 'idle' | 'playing' | 'ducked' | 'stopped'

const DEFAULT_TRACKS: readonly string[] = [
  '/bgm/ambient_01.mp3',
  '/bgm/ambient_02.mp3',
  '/bgm/ambient_03.mp3',
] as const

const DEFAULT_MAX_VOLUME = 0.25
const UNLOCK_TIMEOUT_MS = 0

export function useAmbientBgm(options?: UseAmbientBgmOptions) {
  const maxVolume = options?.maxVolume ?? DEFAULT_MAX_VOLUME
  const tracks: readonly string[] = options?.tracks ?? DEFAULT_TRACKS

  // Reactive state（給外部 UI debug 用，非必須）
  const state = ref<BgmState>('idle')
  const enabled = ref<boolean>(true)

  // 內部狀態（不 reactive，避免 getter/setter 開銷）
  let audioCtx: AudioContext | null = null
  let gainNode: GainNode | null = null
  let audioEl: HTMLAudioElement | null = null
  let sourceNode: MediaElementAudioSourceNode | null = null
  let unlocked = false
  const currentTrackIndex = 0

  function _ensureContext(): AudioContext | null {
    if (audioCtx) return audioCtx
    try {
      const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      if (!Ctx) return null
      audioCtx = new Ctx()
      gainNode = audioCtx.createGain()
      gainNode.gain.value = 0
      gainNode.connect(audioCtx.destination)
      return audioCtx
    } catch (err) {
      console.warn('[useAmbientBgm] AudioContext init failed', err)
      return null
    }
  }

  function _ensureAudioElement(): HTMLAudioElement | null {
    if (audioEl) return audioEl
    const ctx = _ensureContext()
    if (!ctx || !gainNode) return null
    const src = tracks[currentTrackIndex]
    if (!src) return null

    try {
      const el = new Audio()
      el.crossOrigin = 'anonymous'
      el.loop = true
      el.preload = 'auto'
      el.src = src

      el.addEventListener('error', () => {
        // 音檔不存在或解碼失敗 → no-op
      })

      try {
        sourceNode = ctx.createMediaElementSource(el)
        sourceNode.connect(gainNode)
      } catch (err) {
        console.warn('[useAmbientBgm] MediaElementSource failed', err)
        return null
      }

      audioEl = el
      return el
    } catch (err) {
      console.warn('[useAmbientBgm] Audio element create failed', err)
      return null
    }
  }

  function _rampTo(target: number, ms: number): void {
    if (!audioCtx || !gainNode) return
    const now = audioCtx.currentTime
    const duration = Math.max(ms, 1) / 1000
    try {
      // 取消先前排程的 ramp
      gainNode.gain.cancelScheduledValues(now)
      // 從當前值開始 ramp（避免跳音）
      gainNode.gain.setValueAtTime(gainNode.gain.value, now)
      gainNode.gain.linearRampToValueAtTime(target, now + duration)
    } catch (err) {
      console.warn('[useAmbientBgm] ramp failed', err)
    }
  }

  /**
   * iOS Safari 解鎖：必須在 user gesture 同步鏈中呼叫。
   * 做兩件事：
   * 1. `audioCtx.resume()`（若 suspended）
   * 2. 對 <audio> 元素呼叫 play() 然後立刻 pause()（iOS 會記住這次 gesture 授權）
   */
  function unlock(): void {
    const ctx = _ensureContext()
    if (!ctx) return

    if (ctx.state === 'suspended') {
      // resume() 回傳 Promise，但在 user gesture 同步鏈中呼叫是可以的
      void ctx.resume().catch(() => { /* noop */ })
    }

    const el = _ensureAudioElement()
    if (el && !unlocked) {
      try {
        const playPromise = el.play()
        if (playPromise && typeof playPromise.then === 'function') {
          playPromise.then(() => {
            try { el.pause() } catch { /* noop */ }
          }).catch(() => {
            // 音檔不存在會在這裡失敗 → graceful fail（no-op）
          })
        }
      } catch {
        // noop
      }
      unlocked = true
    }
  }

  function play(fadeInMs = 1500): void {
    if (!enabled.value) return
    const ctx = _ensureContext()
    const el = _ensureAudioElement()
    if (!ctx || !el || !gainNode) return

    // 若 context 仍 suspended（未解鎖），不報錯靜默 no-op
    if (ctx.state === 'suspended') {
      void ctx.resume().catch(() => { /* noop */ })
    }

    try {
      const playPromise = el.play()
      if (playPromise && typeof playPromise.then === 'function') {
        playPromise.catch(() => {
          // 檔案不存在 / autoplay policy 擋住 → no-op
        })
      }
    } catch {
      // noop
    }

    _rampTo(maxVolume, fadeInMs)
    state.value = 'playing'
  }

  function duck(fadeOutMs = 400): void {
    if (!enabled.value) return
    if (state.value === 'idle' || state.value === 'stopped') return
    _rampTo(0, fadeOutMs)
    state.value = 'ducked'
  }

  function resume(fadeInMs = 1500): void {
    if (!enabled.value) return
    if (state.value !== 'ducked') return
    _rampTo(maxVolume, fadeInMs)
    state.value = 'playing'
  }

  function stop(fadeOutMs = 600): void {
    if (state.value === 'idle' || state.value === 'stopped') return
    _rampTo(0, fadeOutMs)
    const el = audioEl
    const pauseAfter = Math.max(fadeOutMs, 1)
    if (el) {
      // 延遲到 ramp 完成後再 pause
      setTimeout(() => {
        try {
          if (state.value === 'stopped') el.pause()
        } catch {
          // noop
        }
      }, pauseAfter + UNLOCK_TIMEOUT_MS)
    }
    state.value = 'stopped'
  }

  function setEnabled(value: boolean): void {
    enabled.value = value
    if (!value) {
      // 關閉時立即 stop
      stop(200)
    }
  }

  return {
    // Actions
    unlock,
    play,
    duck,
    resume,
    stop,
    setEnabled,
    // Readonly state（給 UI debug）
    state,
    enabled,
  }
}
