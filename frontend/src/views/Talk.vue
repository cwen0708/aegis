<script setup lang="ts">
/**
 * Talk.vue — /talk/:memberSlug 語音 + 立繪對話頁面
 *
 * 功能：
 * - 載入成員資料（by slug）
 * - WebSocket 連線 /api/v1/ws/talk/{slug}
 * - 按住說話（push-to-talk）錄音 → 送 WebSocket
 * - 顯示狀態徽章（idle/listening/thinking/speaking）
 * - 字幕區（transcript + llm_response）
 * - 測試模式：文字輸入直送 text_input
 *
 * 已知限制：
 * - iOS Safari 不支援 audio/webm;codecs=opus，已自動嘗試 audio/mp4 fallback
 *   （仍需伺服器端相應處理）
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Mic, Send, AlertTriangle, Ear, Hand } from 'lucide-vue-next'
import { getMemberBySlug, type MemberInfo } from '../services/api/members'
import { assetUrl, config } from '../config'
import { useTalkSocket, type TalkState } from '../composables/useTalkSocket'
import { usePushToTalk } from '../composables/usePushToTalk'
import { useVAD } from '../composables/useVAD'
import { useAmbientBgm } from '../composables/useAmbientBgm'

const THINKING_BGM_DELAY_MS = 3000

type TalkMode = 'ptt' | 'vad'
const TALK_MODE_STORAGE_KEY = 'aegis.talk.mode'

function loadTalkMode(): TalkMode {
  try {
    const v = localStorage.getItem(TALK_MODE_STORAGE_KEY)
    if (v === 'ptt' || v === 'vad') return v
  } catch {
    // ignore (private mode / disabled storage)
  }
  return 'ptt'
}

function saveTalkMode(m: TalkMode): void {
  try {
    localStorage.setItem(TALK_MODE_STORAGE_KEY, m)
  } catch {
    // ignore
  }
}

const route = useRoute()
const router = useRouter()

const memberSlug = computed(() => String(route.params.memberSlug || ''))

const member = ref<MemberInfo | null>(null)
const loading = ref(true)
const loadError = ref<string | null>(null)

// STT provider：決定 PTT 走 MediaRecorder（gemini）還是 PCM16 streaming（elevenlabs/deepgram）
type SttProvider = 'gemini' | 'elevenlabs' | 'deepgram'
const sttProvider = ref<SttProvider>('gemini')
const isStreamingStt = computed<boolean>(() => sttProvider.value !== 'gemini')

/** streaming provider 下的前端送音 format（後端目前僅看 stt_provider，但協議保留這個欄位） */
const PCM16_STREAM_FORMAT = 'pcm16;rate=16000'

// 立繪比例偵測
const portraitAspect = ref<'tall' | 'square'>('tall')
function detectPortraitAspect(url: string | undefined) {
  if (!url) return
  const img = new Image()
  img.onload = () => {
    portraitAspect.value = img.height / img.width < 1.4 ? 'square' : 'tall'
  }
  img.src = url
}

const portraitSrc = computed(() => {
  const p = member.value?.portrait
  if (!p) return ''
  return p.startsWith('http') ? p : assetUrl(p)
})

watch(portraitSrc, (url) => detectPortraitAspect(url), { immediate: true })

// ── 對話狀態 ──
const state = ref<TalkState>('idle')
const lastTranscript = ref('')
const lastLlmResponse = ref('')
// Partial STT（可被後續 seq 覆蓋，final 時清空）
const partialText = ref('')
const partialSeq = ref(-1)
const errorBanner = ref<string | null>(null)
const textInput = ref('')
const showTextInput = ref(false)

function clearPartial() {
  partialText.value = ''
  partialSeq.value = -1
}

function setError(msg: string) {
  errorBanner.value = msg
  setTimeout(() => {
    if (errorBanner.value === msg) errorBanner.value = null
  }, 5000)
}

// ── 背景音樂（AI thinking 時填補空白）──
const bgm = useAmbientBgm()
let thinkingBgmTimer: ReturnType<typeof setTimeout> | null = null

function clearThinkingBgmTimer() {
  if (thinkingBgmTimer !== null) {
    clearTimeout(thinkingBgmTimer)
    thinkingBgmTimer = null
  }
}

// ── WebSocket ──
// 句子級 streaming：onLlmPartial 即時累加字幕，onLlmResponse 在結尾覆蓋成完整版
const talk = useTalkSocket(memberSlug.value, {
  onState: (s) => { state.value = s },
  onTranscript: (text) => {
    lastTranscript.value = text
    // final 到達 → 清掉 partial 顯示
    clearPartial()
    // 新一輪 → 清空上一輪字幕
    lastLlmResponse.value = ''
  },
  onTranscriptPartial: (text, seq) => {
    // seq 單調遞增，舊封包忽略（防 out-of-order）
    if (seq >= partialSeq.value) {
      partialText.value = text
      partialSeq.value = seq
    }
  },
  onLlmPartial: (text) => {
    // 中文句子直接累加
    lastLlmResponse.value = (lastLlmResponse.value || '') + text
  },
  onLlmResponse: (text) => { lastLlmResponse.value = text },
  onAudioEnd: () => {
    if (state.value === 'speaking') state.value = 'idle'
    // TTS 結束：若仍在 thinking（多輪工具呼叫）→ resume；否則 stop
    if (state.value === 'thinking') {
      bgm.resume()
    } else {
      bgm.stop()
    }
  },
  onError: (err) => {
    setError(err)
    state.value = 'error'
    clearThinkingBgmTimer()
    bgm.stop()
  },
  onOpen: () => { state.value = 'idle' },
  onClose: () => { state.value = 'disconnected' },
})

// 狀態變化 → BGM 控制
// - thinking 持續 3 秒 → play（淡入）
// - speaking → duck（TTS 音訊開始播放，降音量）
// - idle/disconnected → stop
watch(state, (next, prev) => {
  // 進入 thinking → 排程 3 秒後 play
  if (next === 'thinking' && prev !== 'thinking') {
    clearThinkingBgmTimer()
    thinkingBgmTimer = setTimeout(() => {
      thinkingBgmTimer = null
      if (state.value === 'thinking') {
        bgm.play()
      }
    }, THINKING_BGM_DELAY_MS)
    return
  }

  // 離開 thinking → 取消排程
  if (prev === 'thinking' && next !== 'thinking') {
    clearThinkingBgmTimer()
  }

  // 進入 speaking（TTS 播放）→ duck
  if (next === 'speaking' && prev !== 'speaking') {
    bgm.duck()
    return
  }

  // 回到 idle / disconnected → stop
  if (next === 'idle' || next === 'disconnected') {
    bgm.stop()
  }
})

// ── 錄音模式 ──
const mode = ref<TalkMode>(loadTalkMode())

watch(mode, (m) => saveTalkMode(m))

function sendRecordedAudio(buffer: ArrayBuffer, mimeType: string) {
  const ok = talk.sendAudio(buffer, mimeType)
  if (!ok) {
    setError('尚未連線，無法送出音訊')
    return
  }
  state.value = 'thinking'
}

// ── Push-to-talk 錄音 ──
const ptt = usePushToTalk({
  onRecorded: ({ buffer, mimeType }) => sendRecordedAudio(buffer, mimeType),
  onError: (msg) => setError(msg),
})

async function onPressStart(e: Event) {
  // iOS Safari BGM 解鎖：必須在 user gesture 同步鏈第一行（不可在 await 後呼叫）
  bgm.unlock()
  e.preventDefault()
  if (!talk.connected.value) {
    setError('尚未連線伺服器')
    return
  }
  // 新一輪錄音：清掉殘留的 partial 字幕
  clearPartial()
  state.value = 'listening'

  if (isStreamingStt.value) {
    // Streaming provider（ElevenLabs / Deepgram）：先送 audio_start，再 PCM16 即時串流
    const started = talk.startAudioStream(PCM16_STREAM_FORMAT)
    if (!started) {
      setError('尚未連線，無法送出音訊')
      state.value = 'idle'
      return
    }
    await ptt.startPCM16((chunk) => {
      // chunk 已是 Int16Array.buffer（ArrayBuffer），直接以 binary frame 送
      talk.sendAudioChunk(chunk)
    })
    return
  }

  // Gemini 路徑：MediaRecorder webm/opus 整段
  await ptt.start()
}

function onPressEnd(e: Event) {
  e.preventDefault()
  if (!ptt.recording.value) return

  if (isStreamingStt.value) {
    // Streaming：先停 worklet，再通知後端 commit + close STT session
    ptt.stop()
    const ok = talk.endAudioStream()
    if (!ok) {
      setError('尚未連線，無法結束音訊')
      state.value = 'idle'
      return
    }
    // 後端 STT final 會觸發 transcript → thinking，這邊先樂觀切到 thinking
    state.value = 'thinking'
    return
  }

  // Gemini：onstop 內會把整段 webm buffer 透過 sendRecordedAudio → audio_start+binary+audio_end
  ptt.stop()
}

// ── VAD / 免持對話 ──
// - gemini provider：VAD 自己收音訊（MediaRecorder），onSpeechEnd 整段送
// - streaming provider（elevenlabs/deepgram）：VAD 只做偵測（detectionOnly），
//   PCM16 由 usePushToTalk.startPCM16 持續送 WS；Eleven server VAD 自動切句。
//   VAD 的角色變成 barge-in：TTS 播放中偵測到使用者說話 → duck BGM + 清 TTS 佇列。

// 免持模式下是否仍在 PCM16 streaming（用於清理判斷）
const handsFreeActive = ref(false)

const vad = useVAD({
  onSpeechStart: () => {
    // 新一輪語音：清掉殘留的 partial 字幕
    clearPartial()
    // Barge-in：若 TTS 正在播放（speaking）→ duck BGM + 清 playbackQueue 打斷
    if (state.value === 'speaking') {
      bgm.duck()
      talk.clearPlaybackQueue()
    }
    state.value = 'listening'
  },
  onSpeechEnd: (audio) => {
    // detectionOnly 模式 audio 為 undefined — Eleven server 自己 commit，前端啥都不做
    if (!audio) return
    // gemini 整段路徑：一如以往把 buffer 送到後端
    sendRecordedAudio(audio.buffer, audio.mimeType)
  },
  onError: (msg) => setError(msg),
  silenceDurationMs: 800,
  threshold: 0.02,
  speechOnsetMs: 100,
  minSpeechMs: 300,
})

/**
 * 衍生狀態（effectiveState）— 把 `state` + 使用者輸入動作合成出 9 種 UI 狀態：
 * - disconnected / error / idle：來自 state
 * - recording：PTT 正在錄音
 * - armed：VAD 已啟動但還沒偵測到說話（streaming 免持 idle / gemini VAD idle）
 * - listening：streaming session 開著、VAD 偵測中且未說話（綠 ring）
 * - speaking-user：VAD 偵測到使用者正在說話（紅脈衝，barge-in / VAD 正收音）
 * - thinking / speaking：AI 思考 / TTS 回應
 *
 * 對照表見 golden-jingling-galaxy.md Step 4。
 */
type EffectiveState =
  | 'disconnected'
  | 'error'
  | 'idle'
  | 'recording'
  | 'armed'
  | 'listening'
  | 'speaking-user'
  | 'thinking'
  | 'speaking'

const effectiveState = computed<EffectiveState>(() => {
  if (state.value === 'disconnected') return 'disconnected'
  if (state.value === 'error') return 'error'
  if (state.value === 'speaking') return 'speaking'
  if (state.value === 'thinking') return 'thinking'
  // PTT 錄音 → recording
  if (ptt.recording.value && mode.value === 'ptt') return 'recording'
  // VAD 聆聽中且偵測到說話 → speaking-user（紅脈衝）
  if (vad.isListening.value && vad.isSpeaking.value) return 'speaking-user'
  // listening state（免持 session 開著但尚未說話，或 gemini VAD 啟動中）
  if (state.value === 'listening') {
    // streaming 免持：VAD 運作中但安靜 → listening（綠）
    if (handsFreeActive.value) return 'listening'
    // gemini VAD：偵測器啟動中、等待說話 → armed（淡綠）
    if (vad.isListening.value) return 'armed'
    return 'listening'
  }
  // VAD 啟動但 state 仍 idle（罕見 race）→ armed
  if (vad.isListening.value) return 'armed'
  return 'idle'
})

const stateLabel = computed(() => {
  switch (effectiveState.value) {
    case 'disconnected': return '未連線'
    case 'error': return '錯誤'
    case 'recording': return '錄音中'
    case 'armed': return '聆聽中'
    case 'listening': return '聆聽中'
    case 'speaking-user': return '你說話中'
    case 'thinking': return '思考中'
    case 'speaking': return '回應中'
    default: return '待命中'
  }
})

/** 狀態環顏色（Tailwind ring class，套在 portrait 外圍圓環） */
const stateRingClass = computed(() => {
  switch (effectiveState.value) {
    case 'disconnected': return 'ring-slate-500/40'
    case 'error': return 'ring-red-500/70 animate-pulse'
    case 'recording': return 'ring-sky-500/70 animate-pulse'
    case 'armed': return 'ring-emerald-300/60'
    case 'listening': return 'ring-emerald-500/70'
    case 'speaking-user': return 'ring-red-500/80 animate-pulse'
    case 'thinking': return 'ring-amber-400/70 animate-pulse'
    case 'speaking': return 'ring-purple-500/70 animate-pulse'
    default: return 'ring-slate-500/40'
  }
})

/** 狀態徽章配色（邊框 + 文字）*/
const stateBadgeClass = computed(() => {
  switch (effectiveState.value) {
    case 'disconnected': return 'border-slate-500/60 text-slate-400'
    case 'error': return 'border-red-400/60 text-red-200'
    case 'recording': return 'border-sky-400/60 text-sky-200'
    case 'armed': return 'border-emerald-300/60 text-emerald-200'
    case 'listening': return 'border-emerald-400/60 text-emerald-200'
    case 'speaking-user': return 'border-red-400/70 text-red-200'
    case 'thinking': return 'border-amber-400/60 text-amber-200'
    case 'speaking': return 'border-purple-400/60 text-purple-200'
    default: return 'border-slate-500/60 text-slate-300'
  }
})

/** 徽章指示燈 */
const stateDotClass = computed(() => {
  switch (effectiveState.value) {
    case 'disconnected': return 'bg-slate-500'
    case 'error': return 'bg-red-400'
    case 'recording': return 'bg-sky-400 animate-pulse'
    case 'armed': return 'bg-emerald-300'
    case 'listening': return 'bg-emerald-400'
    case 'speaking-user': return 'bg-red-400 animate-pulse'
    case 'thinking': return 'bg-amber-400 animate-pulse'
    case 'speaking': return 'bg-purple-400 animate-pulse'
    default: return 'bg-slate-400'
  }
})

/** 免持模式 — 進入：建立 streaming session + detectionOnly VAD */
async function enterHandsFreeStreaming(): Promise<boolean> {
  // 1) 建 audio_start session
  const started = talk.startAudioStream(PCM16_STREAM_FORMAT)
  if (!started) {
    setError('尚未連線，無法進入免持模式')
    return false
  }
  // 2) 啟動 PCM16 持續送 chunk（session 直到離開才 endAudioStream）
  try {
    await ptt.startPCM16((chunk) => {
      talk.sendAudioChunk(chunk)
    })
  } catch (e) {
    setError(`免持模式初始化失敗：${e instanceof Error ? e.message : String(e)}`)
    talk.endAudioStream()
    return false
  }
  // 3) 啟動 detectionOnly VAD（只做 barge-in 偵測，threshold 拉高抗 TTS 回饋）
  await vad.start({ detectionOnly: true, threshold: 0.08 })
  handsFreeActive.value = true
  state.value = 'listening'
  return true
}

/** 免持模式 — 離開：停 VAD + 停 PCM16 + endAudioStream */
function exitHandsFreeStreaming() {
  if (vad.isListening.value) vad.stop()
  if (ptt.recording.value) ptt.stop()
  if (handsFreeActive.value) {
    talk.endAudioStream()
    handsFreeActive.value = false
  }
  if (state.value === 'listening') state.value = 'idle'
}

async function toggleVad() {
  // iOS Safari BGM 解鎖：同步鏈第一行
  bgm.unlock()
  if (!talk.connected.value) {
    setError('尚未連線伺服器')
    return
  }

  // 已在 VAD / 免持模式中 → 關閉
  if (vad.isListening.value) {
    if (isStreamingStt.value) {
      exitHandsFreeStreaming()
    } else {
      vad.stop()
      if (state.value === 'listening') state.value = 'idle'
    }
    return
  }

  // 清掉殘留
  clearPartial()

  // 進入模式：streaming 走免持；gemini 走舊 VAD
  if (isStreamingStt.value) {
    await enterHandsFreeStreaming()
  } else {
    await vad.start()
  }
}

function switchMode(target: TalkMode) {
  if (target === mode.value) return
  // 切換前停掉當前模式的錄音
  if (mode.value === 'vad' && vad.isListening.value) {
    if (isStreamingStt.value) {
      exitHandsFreeStreaming()
    } else {
      vad.stop()
    }
  }
  if (mode.value === 'ptt' && ptt.recording.value) ptt.stop()
  mode.value = target
  if (state.value === 'listening') state.value = 'idle'
}

// 麥克風周圍聲波圓圈：以 currentVolume（0–1）換算 scale（1.0–1.6）
const volumeScale = computed(() => {
  const v = Math.min(Math.max(vad.currentVolume.value, 0), 1)
  return 1 + Math.min(v * 6, 0.6)
})

// 文字測試輸入
function submitText() {
  // iOS Safari BGM 解鎖：同步鏈第一行（文字輸入也算 user gesture）
  bgm.unlock()
  const text = textInput.value.trim()
  if (!text) return
  if (!talk.connected.value) {
    setError('尚未連線伺服器')
    return
  }
  const ok = talk.sendText(text)
  if (!ok) {
    setError('送出文字失敗')
    return
  }
  lastTranscript.value = text
  lastLlmResponse.value = ''
  textInput.value = ''
  state.value = 'thinking'
}

function goBack() {
  router.back()
}

// ── 生命週期 ──
async function loadMember() {
  loading.value = true
  loadError.value = null
  try {
    member.value = await getMemberBySlug(memberSlug.value)
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function coerceSttProvider(raw: string | undefined): SttProvider {
  const v = (raw || '').trim().toLowerCase()
  if (v === 'elevenlabs' || v === 'deepgram' || v === 'gemini') return v
  return 'gemini'
}

async function loadTalkSettings() {
  try {
    const res = await fetch(`${config.apiUrl}/api/v1/settings`)
    if (!res.ok) return
    const data = await res.json() as Record<string, string>
    if (data.talk_bgm_enabled === 'false') {
      bgm.setEnabled(false)
    }
    sttProvider.value = coerceSttProvider(data.stt_provider)
    // streaming provider 下「傾聽」即「免持對話」（detectionOnly VAD + 常駐 PCM16）
    // 不再強制切回 PTT
  } catch (err) {
    console.warn('[Talk] load talk settings failed', err)
  }
}

onMounted(async () => {
  await loadMember()
  // 並行載入 bgm + stt_provider 設定（不擋主流程）
  void loadTalkSettings()
  if (member.value) {
    talk.connect()
  }
})

onUnmounted(() => {
  clearThinkingBgmTimer()
  bgm.stop()
  if (handsFreeActive.value) {
    exitHandsFreeStreaming()
  } else if (vad.isListening.value) {
    vad.stop()
  }
  talk.disconnect()
})

// slug 變更時重新載入
watch(memberSlug, async (slug) => {
  if (!slug) return
  if (handsFreeActive.value) {
    exitHandsFreeStreaming()
  } else if (vad.isListening.value) {
    vad.stop()
  }
  talk.disconnect()
  await loadMember()
  if (member.value) talk.connect()
})
</script>

<template>
  <div class="talk-page fixed inset-0 z-[60] bg-gradient-to-b from-slate-900 via-slate-900 to-black overflow-hidden">
    <!-- Top bar -->
    <div class="absolute top-0 left-0 right-0 z-20 flex items-center justify-between px-4 py-3">
      <button
        @click="goBack"
        class="flex items-center gap-1 text-white/80 hover:text-white bg-slate-800/60 hover:bg-slate-700/80 backdrop-blur-sm rounded-lg px-3 py-2 transition-colors"
      >
        <ArrowLeft class="w-4 h-4" />
        <span class="text-sm">返回</span>
      </button>

      <div class="flex items-center gap-2">
        <span class="text-white font-bold text-lg" style="text-shadow: -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000;">
          {{ member?.name || memberSlug }}
        </span>
      </div>

      <div class="flex items-center gap-2">
        <!-- 模式切換 -->
        <div class="flex items-center rounded-lg bg-slate-800/60 backdrop-blur-sm border border-slate-700 overflow-hidden text-xs">
          <button
            @click="switchMode('ptt')"
            :class="[
              'px-2.5 py-2 flex items-center gap-1 transition-colors',
              mode === 'ptt' ? 'bg-emerald-600/80 text-white' : 'text-white/60 hover:text-white'
            ]"
            title="錄音 — 點擊開始 / 再點停止"
            aria-label="切換到錄音模式"
          >
            <Hand class="w-3.5 h-3.5" />
            <span class="hidden sm:inline">錄音</span>
          </button>
          <button
            @click="switchMode('vad')"
            :class="[
              'px-2.5 py-2 flex items-center gap-1 transition-colors',
              mode === 'vad' ? 'bg-emerald-600/80 text-white' : 'text-white/60 hover:text-white',
            ]"
            :title="isStreamingStt ? '免持對話 — 持續聆聽，講完 AI 自動回應' : '傾聽中 — 自動斷句'"
            :aria-label="isStreamingStt ? '切換到免持對話模式' : '切換到自動斷句模式'"
          >
            <Ear class="w-3.5 h-3.5" />
            <span class="hidden sm:inline">傾聽</span>
          </button>
        </div>

        <button
          @click="showTextInput = !showTextInput"
          class="text-white/70 hover:text-white bg-slate-800/60 hover:bg-slate-700/80 backdrop-blur-sm rounded-lg px-3 py-2 text-xs transition-colors"
          :class="{ 'bg-emerald-600/80 text-white': showTextInput }"
          title="切換文字測試輸入模式"
        >
          測試輸入
        </button>
      </div>
    </div>

    <!-- Error banner -->
    <Transition name="fade">
      <div
        v-if="errorBanner"
        class="absolute top-16 left-1/2 -translate-x-1/2 z-30 bg-red-900/80 backdrop-blur-sm text-white text-sm rounded-lg px-4 py-2 flex items-center gap-2 shadow-xl"
      >
        <AlertTriangle class="w-4 h-4 shrink-0" />
        <span>{{ errorBanner }}</span>
      </div>
    </Transition>

    <!-- Loading / Load Error -->
    <div v-if="loading" class="absolute inset-0 flex items-center justify-center">
      <div class="text-slate-400 text-sm">載入成員資料中…</div>
    </div>
    <div
      v-else-if="loadError"
      class="absolute inset-0 flex flex-col items-center justify-center gap-3 text-center px-4"
    >
      <AlertTriangle class="w-12 h-12 text-red-400" />
      <p class="text-white text-lg">無法載入成員</p>
      <p class="text-slate-400 text-sm">{{ loadError }}</p>
      <button
        @click="goBack"
        class="mt-2 bg-slate-700 hover:bg-slate-600 text-white rounded px-4 py-2 text-sm"
      >
        返回
      </button>
    </div>

    <!-- Main content -->
    <template v-else-if="member">
      <!-- Portrait -->
      <div class="absolute inset-0 flex items-center justify-center pt-16 pb-64 sm:pb-56 pointer-events-none">
        <div class="relative h-full max-h-[70vh] aspect-[3/4] flex items-end justify-center">
          <template v-if="portraitSrc">
            <img
              :src="portraitSrc"
              :class="[
                'h-full drop-shadow-2xl transition-all duration-300',
                portraitAspect === 'square' ? 'object-cover object-top' : 'object-contain object-bottom',
                'portrait',
                `portrait-${state}`,
              ]"
              :alt="member.name"
            />
          </template>
          <template v-else>
            <div class="w-48 h-72 rounded-t-full flex items-end justify-center pb-10 text-7xl portrait"
              :class="[
                member.provider === 'claude' ? 'bg-orange-500/20' : 'bg-blue-500/20',
                `portrait-${state}`,
              ]"
            >
              {{ member.provider === 'claude' ? '🟠' : '🔵' }}
            </div>
          </template>
        </div>
      </div>

      <!--
        狀態環 + 徽章（一體，放在立繪下方、麥克風上方）
        - 6 色 ring 以 effectiveState 驅動，涵蓋 9 個子狀態（armed/listening/speaking-user 共享部分配色）
        - role="status" aria-live="polite" 讓螢幕閱讀器即時讀出狀態變化
        - :aria-label 帶入中文 stateLabel，徽章本身也顯示文字給視覺使用者
      -->
      <div
        class="absolute left-1/2 -translate-x-1/2 bottom-[260px] sm:bottom-[240px] z-10 flex flex-col items-center gap-2"
        role="status"
        aria-live="polite"
        :aria-label="`目前狀態：${stateLabel}`"
      >
        <!-- 狀態環（portrait 基座的視覺錨點；用 ring utility 在圓形容器外圍畫環） -->
        <div
          class="w-14 h-14 rounded-full bg-slate-900/50 backdrop-blur-sm ring-4 ring-offset-2 ring-offset-slate-900/30 flex items-center justify-center transition-all duration-300"
          :class="stateRingClass"
        >
          <span
            class="w-3 h-3 rounded-full"
            :class="stateDotClass"
            aria-hidden="true"
          />
        </div>
        <!-- 徽章（文字狀態） -->
        <div
          class="flex items-center gap-2 bg-slate-900/70 backdrop-blur-sm border rounded-full px-4 py-1 text-xs"
          :class="stateBadgeClass"
        >
          {{ stateLabel }}
        </div>
      </div>

      <!-- Subtitle / Dialog box (bottom right) -->
      <div class="absolute bottom-[132px] sm:bottom-[120px] right-2 left-2 sm:left-auto sm:right-6 sm:w-[480px] max-w-[calc(100vw-1rem)] z-10 space-y-2">
        <!-- Partial（streaming STT 即時字幕，淡色斜體，final 到達後清掉） -->
        <div
          v-if="partialText && !lastTranscript"
          class="bg-slate-900/40 backdrop-blur-sm border border-slate-500/30 rounded-lg px-4 py-2"
        >
          <div class="text-[10px] uppercase tracking-wider text-slate-400 mb-1">你正在說…</div>
          <p class="text-slate-300 text-sm italic leading-relaxed">{{ partialText }}</p>
        </div>
        <div
          v-if="lastTranscript"
          class="bg-slate-900/60 backdrop-blur-sm border border-sky-400/30 rounded-lg px-4 py-2"
        >
          <div class="text-[10px] uppercase tracking-wider text-sky-300 mb-1">你說</div>
          <p class="text-white text-sm leading-relaxed">{{ lastTranscript }}</p>
        </div>
        <div
          v-if="lastLlmResponse"
          class="bg-slate-900/60 backdrop-blur-sm border border-emerald-400/30 rounded-lg px-4 py-2"
        >
          <div class="text-[10px] uppercase tracking-wider text-emerald-300 mb-1">
            {{ member.name }} 說
          </div>
          <p class="text-white text-sm leading-relaxed">{{ lastLlmResponse }}</p>
        </div>
      </div>

      <!-- Bottom control area -->
      <div class="absolute bottom-0 left-0 right-0 z-20 px-4 pb-6 pt-3 bg-gradient-to-t from-black/80 to-transparent">
        <!-- Text input (test mode) -->
        <Transition name="fade">
          <div v-if="showTextInput" class="mb-3 flex items-center gap-2 max-w-2xl mx-auto">
            <input
              v-model="textInput"
              @keydown.enter="submitText"
              type="text"
              placeholder="輸入文字測試（跳過 STT）"
              class="flex-1 bg-slate-800/80 border border-slate-600 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-emerald-400"
            />
            <button
              @click="submitText"
              :disabled="!textInput.trim() || !talk.connected.value"
              class="bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 disabled:text-slate-500 text-white rounded-lg p-2 transition-colors"
            >
              <Send class="w-4 h-4" />
            </button>
          </div>
        </Transition>

        <!-- Mic button: Push-to-talk 或 VAD -->
        <div class="flex items-center justify-center">
          <!-- PTT 模式 -->
          <button
            v-if="mode === 'ptt'"
            @mousedown="onPressStart"
            @mouseup="onPressEnd"
            @mouseleave="onPressEnd"
            @touchstart.prevent="onPressStart"
            @touchend.prevent="onPressEnd"
            @touchcancel.prevent="onPressEnd"
            :disabled="!talk.connected.value"
            class="flex items-center justify-center gap-3 select-none transition-all rounded-full font-bold shadow-2xl"
            :class="[
              ptt.recording.value
                ? 'bg-red-500 scale-110 shadow-red-500/50'
                : talk.connected.value
                  ? 'bg-emerald-600 hover:bg-emerald-500 active:scale-95'
                  : 'bg-slate-700 text-slate-400 cursor-not-allowed',
              'w-20 h-20 sm:w-24 sm:h-24 text-white',
            ]"
            :title="talk.connected.value ? '錄音 — 點擊開始 / 再點停止' : '尚未連線'"
            :aria-label="ptt.recording.value ? '停止錄音' : '開始錄音'"
          >
            <Mic class="w-8 h-8 sm:w-10 sm:h-10" />
          </button>

          <!-- VAD 模式：單擊 toggle -->
          <div v-else class="relative flex items-center justify-center w-28 h-28 sm:w-32 sm:h-32">
            <!-- 音量脈動圓圈（只在聆聽中且有聲音時顯示） -->
            <span
              v-if="vad.isListening.value"
              class="vad-ring absolute inset-0 rounded-full pointer-events-none"
              :class="vad.isSpeaking.value ? 'vad-ring-speaking' : 'vad-ring-listening'"
              :style="{ transform: `scale(${volumeScale})` }"
            />
            <span
              v-if="vad.isListening.value"
              class="vad-ring-soft absolute inset-2 rounded-full pointer-events-none"
            />
            <button
              @click="toggleVad"
              :disabled="!talk.connected.value"
              class="relative flex items-center justify-center select-none transition-all rounded-full font-bold shadow-2xl w-20 h-20 sm:w-24 sm:h-24 text-white"
              :class="[
                vad.isSpeaking.value
                  ? 'bg-red-500 scale-105 shadow-red-500/50'
                  : vad.isListening.value
                    ? 'bg-sky-500 shadow-sky-500/40 animate-pulse-slow'
                    : talk.connected.value
                      ? 'bg-emerald-600 hover:bg-emerald-500 active:scale-95'
                      : 'bg-slate-700 text-slate-400 cursor-not-allowed'
              ]"
              :title="
                !talk.connected.value ? '尚未連線' :
                vad.isListening.value ? (isStreamingStt ? '停止免持對話' : '點擊關閉傾聽')
                                      : (isStreamingStt ? '免持對話 — 持續聆聽，講完 AI 自動回應' : '傾聽中 — 自動斷句')
              "
              :aria-label="
                vad.isListening.value ? '關閉傾聽'
                                      : (isStreamingStt ? '開啟免持對話' : '開啟傾聽模式')
              "
            >
              <Ear v-if="vad.isListening.value && !vad.isSpeaking.value" class="w-8 h-8 sm:w-10 sm:h-10" />
              <Mic v-else class="w-8 h-8 sm:w-10 sm:h-10" />
            </button>
          </div>
        </div>
        <p class="text-center text-slate-400 text-xs mt-2">
          <template v-if="mode === 'ptt'">
            {{ ptt.recording.value ? '放開結束錄音…' : '按住說話' }}
          </template>
          <template v-else>
            <template v-if="!vad.isListening.value">
              {{ isStreamingStt ? '點擊開啟免持對話（持續聆聽）' : '點擊開啟傾聽模式（自動斷句）' }}
            </template>
            <template v-else-if="vad.isSpeaking.value">偵測到語音…</template>
            <template v-else>
              {{ isStreamingStt ? '免持中（再按一次停止）' : '聆聽中（再按一次關閉）' }}
            </template>
          </template>
        </p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.portrait {
  transition: filter 0.3s ease, opacity 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
}

.portrait-listening {
  filter: drop-shadow(0 0 40px rgba(100, 180, 255, 0.6));
}

.portrait-thinking {
  opacity: 0.8;
  filter: drop-shadow(0 0 20px rgba(251, 191, 36, 0.4));
}

.portrait-speaking {
  animation: breathe 2s ease-in-out infinite;
  filter: drop-shadow(0 0 30px rgba(52, 211, 153, 0.5));
}

.portrait-error {
  filter: grayscale(0.4) drop-shadow(0 0 20px rgba(239, 68, 68, 0.4));
}

.portrait-disconnected {
  filter: grayscale(0.6);
  opacity: 0.6;
}

@keyframes breathe {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.015); }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* ── VAD 麥克風聲波視覺化 ── */
.vad-ring {
  background: radial-gradient(circle, rgba(56, 189, 248, 0.25) 0%, rgba(56, 189, 248, 0) 70%);
  transition: transform 80ms ease-out;
  will-change: transform;
}
.vad-ring-speaking {
  background: radial-gradient(circle, rgba(239, 68, 68, 0.35) 0%, rgba(239, 68, 68, 0) 70%);
}
.vad-ring-listening {
  background: radial-gradient(circle, rgba(56, 189, 248, 0.25) 0%, rgba(56, 189, 248, 0) 70%);
}
.vad-ring-soft {
  border: 2px solid rgba(125, 211, 252, 0.25);
  animation: vad-soft-pulse 2s ease-in-out infinite;
}
@keyframes vad-soft-pulse {
  0%, 100% { opacity: 0.3; transform: scale(1); }
  50% { opacity: 0.7; transform: scale(1.08); }
}

.animate-pulse-slow {
  animation: pulse-slow 1.8s ease-in-out infinite;
}
@keyframes pulse-slow {
  0%, 100% { box-shadow: 0 0 0 0 rgba(56, 189, 248, 0.5); }
  50% { box-shadow: 0 0 0 14px rgba(56, 189, 248, 0); }
}
</style>
