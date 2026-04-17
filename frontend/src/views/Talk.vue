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
import { ArrowLeft, Mic, Send, AlertTriangle } from 'lucide-vue-next'
import { getMemberBySlug, type MemberInfo } from '../services/api/members'
import { assetUrl } from '../config'
import { useTalkSocket, type TalkState } from '../composables/useTalkSocket'
import { usePushToTalk } from '../composables/usePushToTalk'

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
const errorBanner = ref<string | null>(null)
const textInput = ref('')
const showTextInput = ref(false)

const stateLabel = computed(() => {
  switch (state.value) {
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

// ── WebSocket ──
const talk = useTalkSocket(memberSlug.value, {
  onState: (s) => { state.value = s },
  onTranscript: (text) => { lastTranscript.value = text },
  onLlmResponse: (text) => { lastLlmResponse.value = text },
  onAudioEnd: () => {
    if (state.value === 'speaking') state.value = 'idle'
  },
  onError: (err) => {
    setError(err)
    state.value = 'error'
  },
  onOpen: () => { state.value = 'idle' },
  onClose: () => { state.value = 'disconnected' },
})

// ── 錄音 ──
const ptt = usePushToTalk({
  onRecorded: ({ buffer, mimeType }) => {
    const ok = talk.sendAudio(buffer, mimeType)
    if (!ok) {
      setError('尚未連線，無法送出音訊')
      return
    }
    state.value = 'thinking'
  },
  onError: (msg) => setError(msg),
})

async function onPressStart(e: Event) {
  e.preventDefault()
  if (!talk.connected.value) {
    setError('尚未連線伺服器')
    return
  }
  state.value = 'listening'
  await ptt.start()
}

function onPressEnd(e: Event) {
  e.preventDefault()
  if (ptt.recording.value) {
    ptt.stop()
  }
}

// 文字測試輸入
function submitText() {
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

onMounted(async () => {
  await loadMember()
  if (member.value) {
    talk.connect()
  }
})

onUnmounted(() => {
  talk.disconnect()
})

// slug 變更時重新載入
watch(memberSlug, async (slug) => {
  if (!slug) return
  talk.disconnect()
  await loadMember()
  if (member.value) talk.connect()
})
</script>

<template>
  <div class="talk-page fixed inset-0 bg-gradient-to-b from-slate-900 via-slate-900 to-black overflow-hidden">
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

      <button
        @click="showTextInput = !showTextInput"
        class="text-white/70 hover:text-white bg-slate-800/60 hover:bg-slate-700/80 backdrop-blur-sm rounded-lg px-3 py-2 text-xs transition-colors"
        :class="{ 'bg-emerald-600/80 text-white': showTextInput }"
        title="切換文字測試輸入模式"
      >
        測試輸入
      </button>
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

      <!-- State badge (below portrait) -->
      <div class="absolute left-1/2 -translate-x-1/2 bottom-[260px] sm:bottom-[240px] z-10">
        <div
          class="flex items-center gap-2 bg-slate-900/70 backdrop-blur-sm border rounded-full px-4 py-1.5 text-sm"
          :class="[
            state === 'listening' ? 'border-sky-400/60 text-sky-200' :
            state === 'thinking' ? 'border-amber-400/60 text-amber-200' :
            state === 'speaking' ? 'border-emerald-400/60 text-emerald-200' :
            state === 'error' ? 'border-red-400/60 text-red-200' :
            state === 'disconnected' ? 'border-slate-500/60 text-slate-400' :
            'border-slate-500/60 text-slate-300'
          ]"
        >
          <span class="w-2 h-2 rounded-full"
            :class="[
              state === 'listening' ? 'bg-sky-400 animate-pulse' :
              state === 'thinking' ? 'bg-amber-400 animate-pulse' :
              state === 'speaking' ? 'bg-emerald-400 animate-pulse' :
              state === 'error' ? 'bg-red-400' :
              state === 'disconnected' ? 'bg-slate-500' :
              'bg-slate-400'
            ]"
          />
          {{ stateLabel }}
        </div>
      </div>

      <!-- Subtitle / Dialog box (bottom right) -->
      <div class="absolute bottom-[132px] sm:bottom-[120px] right-2 left-2 sm:left-auto sm:right-6 sm:w-[480px] max-w-[calc(100vw-1rem)] z-10 space-y-2">
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

        <!-- Push-to-talk button -->
        <div class="flex items-center justify-center">
          <button
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
            :title="talk.connected.value ? '按住說話' : '尚未連線'"
          >
            <Mic class="w-8 h-8 sm:w-10 sm:h-10" />
          </button>
        </div>
        <p class="text-center text-slate-400 text-xs mt-2">
          {{ ptt.recording.value ? '放開結束錄音…' : '按住說話' }}
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
</style>
