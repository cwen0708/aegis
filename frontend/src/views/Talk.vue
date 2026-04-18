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
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Mic, Send, AlertTriangle, Ear } from 'lucide-vue-next'
import { getMemberBySlug, type MemberInfo } from '../services/api/members'
import { assetUrl, config } from '../config'
import { useTalkSocket, type TalkState } from '../composables/useTalkSocket'
import { usePushToTalk } from '../composables/usePushToTalk'
import { useVAD } from '../composables/useVAD'
import { useAmbientBgm } from '../composables/useAmbientBgm'

const THINKING_BGM_DELAY_MS = 3000

type TalkMode = 'ptt' | 'vad' | 'text'
const TALK_MODE_STORAGE_KEY = 'aegis.talk.mode'

function loadTalkMode(): TalkMode {
  try {
    const v = localStorage.getItem(TALK_MODE_STORAGE_KEY)
    if (v === 'ptt' || v === 'vad' || v === 'text') return v
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
// AI 回覆字幕容器 — 用於 streaming 時自動捲到最新一段
const llmResponseRef = ref<HTMLParagraphElement | null>(null)
watch(lastLlmResponse, async () => {
  await nextTick()
  const el = llmResponseRef.value
  if (!el) return
  // 若使用者已手動捲上去（離底 > 40px），就不打擾；否則自動貼底
  const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
  if (distanceFromBottom < 40) {
    el.scrollTop = el.scrollHeight
  }
})
// Partial STT（可被後續 seq 覆蓋，final 時清空）
const partialText = ref('')
const partialSeq = ref(-1)
const errorBanner = ref<string | null>(null)
const textInput = ref('')

/**
 * 有效狀態：融合前端 active 狀態（錄音中、VAD 傾聽中）與 WS 遠端狀態。
 * 前端動作狀態優先（使用者一眼就看到自己的操作結果），遠端狀態次之。
 */
const effectiveState = computed<
  'recording' | 'armed' | 'listening' | 'thinking' | 'speaking' | 'disconnected' | 'error' | 'idle'
>(() => {
  if (ptt.recording.value) return 'recording'
  if (vad.isListening.value) {
    return vad.isSpeaking.value ? 'listening' : 'armed'
  }
  if (state.value === 'listening') return 'listening'
  if (state.value === 'thinking') return 'thinking'
  if (state.value === 'speaking') return 'speaking'
  if (state.value === 'disconnected') return 'disconnected'
  if (state.value === 'error') return 'error'
  return 'idle'
})

function clearPartial() {
  partialText.value = ''
  partialSeq.value = -1
}

const stateLabel = computed(() => {
  switch (effectiveState.value) {
    case 'recording': return '錄音中'
    case 'armed': return '傾聽中…'
    case 'listening': return '聆聽中'
    case 'thinking': return '思考中'
    case 'speaking': return '回應中'
    case 'disconnected': return '未連線'
    case 'error': return '錯誤'
    default: return '待命中'
  }
})

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

// ── VAD 自動斷句錄音 ──
const vad = useVAD({
  onSpeechStart: () => {
    // 新一輪語音：清掉殘留的 partial 字幕
    clearPartial()
    state.value = 'listening'
  },
  onSpeechEnd: ({ buffer, mimeType }) => {
    sendRecordedAudio(buffer, mimeType)
  },
  onError: (msg) => setError(msg),
  // 抗噪調校：提高閾值、延長 onset/min 長度，避免環境雜音與短促聲響誤判為說話
  silenceDurationMs: 900,   // 停頓 0.9 秒才結束（中文字間較易誤切）
  threshold: 0.04,          // RMS 閾值提高（0.02 → 0.04）抗背景噪音
  speechOnsetMs: 220,       // 連續 220ms 才算開始（抗瞬時噪音）
  minSpeechMs: 600,         // 短於 0.6 秒丟棄（減少單音節誤觸）
})

/**
 * 停掉當前模式正在執行的工作（錄音／傾聽），保留模式值不動。
 * 切換模式前先呼叫，避免兩個輸入源同時工作。
 */
function stopCurrentActivity() {
  if (mode.value === 'vad' && vad.isListening.value) vad.stop()
  if (mode.value === 'ptt' && ptt.recording.value) ptt.stop()
  if (state.value === 'listening') state.value = 'idle'
}

// 三個底部按鈕 = 模式切換 + 動作觸發
async function toggleRecord() {
  // iOS Safari BGM 解鎖：必須在 user gesture 同步鏈第一行（不可在 await 後呼叫）
  bgm.unlock()
  if (!talk.connected.value) { setError('尚未連線伺服器'); return }
  // 正在錄 → 停止送出
  if (mode.value === 'ptt' && ptt.recording.value) {
    ptt.stop()
    return
  }
  // 其他模式 → 先停、切到 ptt、開始錄
  if (mode.value !== 'ptt') {
    stopCurrentActivity()
    mode.value = 'ptt'
  }
  state.value = 'listening'
  await ptt.start()
}

async function toggleListen() {
  // iOS Safari BGM 解鎖：同步鏈第一行
  bgm.unlock()
  if (!talk.connected.value) { setError('尚未連線伺服器'); return }
  if (mode.value === 'vad' && vad.isListening.value) {
    vad.stop()
    if (state.value === 'listening') state.value = 'idle'
    return
  }
  if (mode.value !== 'vad') {
    stopCurrentActivity()
    mode.value = 'vad'
  }
  await vad.start()
}

function toggleText() {
  // iOS Safari BGM 解鎖：同步鏈第一行（切到文字也算 user gesture）
  bgm.unlock()
  if (mode.value === 'text') return
  stopCurrentActivity()
  mode.value = 'text'
}

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

async function loadBgmSetting() {
  try {
    const res = await fetch(`${config.apiUrl}/api/v1/settings`)
    if (!res.ok) return
    const data = await res.json() as Record<string, string>
    if (data.talk_bgm_enabled === 'false') {
      bgm.setEnabled(false)
    }
  } catch (err) {
    console.warn('[Talk] load bgm setting failed', err)
  }
}

onMounted(async () => {
  await loadMember()
  // 並行載入 bgm 設定（不擋主流程）
  void loadBgmSetting()
  if (member.value) {
    talk.connect()
  }
})

onUnmounted(() => {
  clearThinkingBgmTimer()
  bgm.stop()
  if (vad.isListening.value) vad.stop()
  talk.disconnect()
})

// slug 變更時重新載入
watch(memberSlug, async (slug) => {
  if (!slug) return
  if (vad.isListening.value) vad.stop()
  talk.disconnect()
  await loadMember()
  if (member.value) talk.connect()
})
</script>

<template>
  <div class="talk-page fixed z-40 top-16 bottom-0 left-0 right-0 sm:top-0 bg-gradient-to-b from-slate-900 via-slate-900 to-black overflow-hidden">
    <!-- 頂部使用全局 mobile nav（64px），桌面版顯示 sidebar。此頁不再自繪 top bar。成員名稱見底部工具列。 -->

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
      <div class="absolute inset-0 flex items-end justify-center pointer-events-none">
        <div class="relative h-full aspect-[3/4] max-w-full flex items-end justify-center">
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

      <!-- 字幕區（壓在立繪上方，工具列上緣）。長文自動捲到最新一段 -->
      <div
        v-if="lastTranscript || lastLlmResponse || (partialText && !lastTranscript)"
        class="absolute left-2 right-2 bottom-[72px] z-10 space-y-2 max-h-[55vh] flex flex-col"
      >
        <!-- Partial（streaming STT 即時字幕，淡色斜體，final 到達後清掉） -->
        <div
          v-if="partialText && !lastTranscript"
          class="bg-slate-900/40 backdrop-blur-sm border border-slate-500/30 rounded-lg px-4 py-2 shrink-0"
        >
          <div class="text-[10px] uppercase tracking-wider text-slate-400 mb-1">你正在說…</div>
          <p class="text-slate-300 text-sm italic leading-relaxed">{{ partialText }}</p>
        </div>
        <div
          v-if="lastTranscript"
          class="bg-slate-900/70 backdrop-blur-sm border border-sky-400/30 rounded-lg px-4 py-2 shrink-0"
        >
          <div class="text-[10px] uppercase tracking-wider text-sky-300 mb-1">你說</div>
          <p class="text-white text-sm leading-relaxed line-clamp-2">{{ lastTranscript }}</p>
        </div>
        <div
          v-if="lastLlmResponse"
          class="bg-slate-900/70 backdrop-blur-sm border border-emerald-400/30 rounded-lg px-4 py-2 min-h-0 flex flex-col"
        >
          <div class="text-[10px] uppercase tracking-wider text-emerald-300 mb-1 shrink-0">
            {{ member.name }} 說
          </div>
          <p
            ref="llmResponseRef"
            class="text-white text-sm leading-relaxed overflow-y-auto custom-scrollbar"
          >{{ lastLlmResponse }}</p>
        </div>
      </div>

      <!-- 底部工具列：[● 名字·狀態] .... [錄音｜傾聽｜輸入] [頭像] -->
      <div class="absolute left-0 right-0 bottom-0 z-20 h-16 bg-slate-900/85 backdrop-blur-md border-t border-slate-700/50 px-2 flex items-center gap-2">
        <!-- 狀態徽章（成員名 · 狀態，顏色同步錄音/傾聽實際狀態） -->
        <div
          class="flex items-center gap-2 border rounded-full px-3 py-1.5 text-xs min-w-0 max-w-[50%]"
          :class="[
            effectiveState === 'recording' ? 'border-red-400/70 text-red-200 bg-red-500/10' :
            effectiveState === 'listening' ? 'border-sky-400/70 text-sky-200 bg-sky-500/10' :
            effectiveState === 'armed' ? 'border-sky-400/50 text-sky-300' :
            effectiveState === 'thinking' ? 'border-amber-400/60 text-amber-200' :
            effectiveState === 'speaking' ? 'border-emerald-400/60 text-emerald-200' :
            effectiveState === 'error' ? 'border-red-400/60 text-red-200' :
            effectiveState === 'disconnected' ? 'border-slate-500/60 text-slate-400' :
            'border-slate-500/60 text-slate-300'
          ]"
        >
          <span class="w-2 h-2 rounded-full shrink-0"
            :class="[
              effectiveState === 'recording' ? 'bg-red-400 animate-pulse' :
              effectiveState === 'listening' ? 'bg-sky-400 animate-pulse' :
              effectiveState === 'armed' ? 'bg-sky-400 animate-pulse' :
              effectiveState === 'thinking' ? 'bg-amber-400 animate-pulse' :
              effectiveState === 'speaking' ? 'bg-emerald-400 animate-pulse' :
              effectiveState === 'error' ? 'bg-red-400' :
              effectiveState === 'disconnected' ? 'bg-slate-500' :
              'bg-slate-400'
            ]"
          />
          <span class="truncate">{{ member.name }} · {{ stateLabel }}</span>
        </div>

        <div class="ml-auto flex items-center gap-1.5">
          <!-- 互動三鈕：錄音（大）/ 傾聽 / 輸入 -->
          <div class="flex items-center rounded-xl bg-slate-800/60 border border-slate-700 overflow-hidden text-sm shadow-lg">
            <!-- 錄音（主要動作，視覺最顯眼） -->
            <button
              @click="toggleRecord"
              :disabled="!talk.connected.value"
              :class="[
                'px-5 py-2.5 flex items-center gap-1.5 font-semibold transition-colors',
                ptt.recording.value
                  ? 'bg-red-500 text-white animate-pulse'
                  : mode === 'ptt'
                    ? 'bg-emerald-600/80 text-white'
                    : 'text-white/70 hover:text-white hover:bg-slate-700/50 disabled:opacity-40'
              ]"
              :title="ptt.recording.value ? '點擊停止錄音' : '點擊開始錄音'"
              aria-label="錄音"
            >
              <Mic class="w-5 h-5" />
              <span>{{ ptt.recording.value ? '停止' : '錄音' }}</span>
            </button>
            <!-- 傾聽（VAD toggle） -->
            <button
              @click="toggleListen"
              :disabled="!talk.connected.value"
              :class="[
                'px-3.5 py-2.5 flex items-center gap-1 transition-colors',
                vad.isListening.value
                  ? 'bg-sky-500 text-white animate-pulse'
                  : mode === 'vad'
                    ? 'bg-emerald-600/80 text-white'
                    : 'text-white/70 hover:text-white hover:bg-slate-700/50 disabled:opacity-40'
              ]"
              :title="vad.isListening.value ? '點擊關閉傾聽' : '點擊開啟自動斷句傾聽'"
              aria-label="傾聽"
            >
              <Ear class="w-4 h-4" />
              <span class="hidden sm:inline">傾聽</span>
            </button>
            <!-- 文字輸入 -->
            <button
              @click="toggleText"
              :class="[
                'px-3.5 py-2.5 flex items-center gap-1 transition-colors',
                mode === 'text' ? 'bg-emerald-600/80 text-white' : 'text-white/70 hover:text-white hover:bg-slate-700/50'
              ]"
              title="文字輸入模式"
              aria-label="文字輸入"
            >
              <Send class="w-4 h-4" />
              <span class="hidden sm:inline">輸入</span>
            </button>
          </div>

        </div>
      </div>

      <!-- 底部文字輸入框（僅測試模式，浮在工具列上方） -->
      <Transition name="fade">
        <div
          v-if="mode === 'text'"
          class="absolute bottom-[72px] left-2 right-2 sm:left-1/2 sm:-translate-x-1/2 sm:w-[480px] z-30 flex items-center gap-2"
        >
          <input
            v-model="textInput"
            @keydown.enter="submitText"
            type="text"
            placeholder="輸入文字測試（跳過 STT）"
            class="flex-1 bg-slate-800/90 border border-slate-600 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-emerald-400"
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
