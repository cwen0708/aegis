<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { X, CheckCircle, XCircle, Clock, Loader2, ListTodo, BookOpen, ChevronLeft, ChevronRight, Volume2, VolumeX } from 'lucide-vue-next'
import { useAegisStore } from '../stores/aegis'
import { config } from '../config'
import { apiClient } from '../services/api/client'

const store = useAegisStore()

const props = defineProps<{
  memberId: number
  name: string
  provider: string
  role?: string
  portrait?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

// 圖片比例檢測
const portraitAspect = ref<'tall' | 'square'>('tall')
function detectPortraitAspect() {
  if (!props.portrait) return
  const img = new Image()
  img.onload = () => {
    portraitAspect.value = img.height / img.width < 1.4 ? 'square' : 'tall'
  }
  img.src = props.portrait
}
watch(() => props.portrait, detectPortraitAspect, { immediate: true })

// ==========================================
// AVG 對話系統
// ==========================================
interface DialogueLine {
  id: number
  text: string
  dialogue_type: string
  card_title: string
  created_at: string
}

const dialogues = ref<DialogueLine[]>([])
const currentIndex = ref(0)
const displayedText = ref('')
const isTyping = ref(false)
let typewriterTimer: number | null = null
const CHAR_DELAY = 35

function startTypewriter(text: string) {
  stopTypewriter()
  stopTts()
  displayedText.value = ''
  isTyping.value = true
  playTts(text)  // 同步播放語音
  let i = 0
  typewriterTimer = window.setInterval(() => {
    if (i < text.length) {
      displayedText.value += text[i]
      i++
    } else {
      stopTypewriter()
    }
  }, CHAR_DELAY)
}

// TTS 語音播放 — 讀取 DB 設定（透過 store）
const ttsEnabled = ref(false)
const ttsProvider = ref('web')
let currentAudio: HTMLAudioElement | null = null

// 初始化：從 store settings 讀取（DB 來源）
watch(() => store.settings, (s) => {
  if (s) {
    ttsEnabled.value = s.tts_enabled === 'true'
    ttsProvider.value = s.tts_provider || (s.tts_gemini === 'true' ? 'gemini' : 'web')
  }
}, { immediate: true })

function toggleTts() {
  ttsEnabled.value = !ttsEnabled.value
  store.updateSettings({ tts_enabled: String(ttsEnabled.value) })
  if (!ttsEnabled.value) stopTts()
}

function stopTts() {
  if (currentAudio) {
    currentAudio.pause()
    currentAudio = null
  }
  window.speechSynthesis?.cancel()
}

async function playTts(text: string) {
  if (!ttsEnabled.value || !text) return
  stopTts()

  // Gemini 或 TTSMaker → 呼叫後端 TTS API
  if (ttsProvider.value !== 'web') {
    try {
      const res = await fetch(`${config.apiUrl}/api/v1/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })
      if (res.ok && res.status === 200) {
        const blob = await res.blob()
        currentAudio = new Audio(URL.createObjectURL(blob))
        currentAudio.play()
        return
      }
    } catch {}
  }

  // 降級 Web Speech
  if (window.speechSynthesis) {
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = 'zh-TW'
    utterance.rate = 1.0
    window.speechSynthesis.speak(utterance)
  }
}

function stopTypewriter() {
  if (typewriterTimer) {
    clearInterval(typewriterTimer)
    typewriterTimer = null
  }
  if (isTyping.value && currentIndex.value < dialogues.value.length) {
    displayedText.value = dialogues.value[currentIndex.value]?.text ?? ''
  }
  isTyping.value = false
}

const hasNextLine = computed(() => currentIndex.value < dialogues.value.length - 1)

function skipOrNext() {
  if (isWorking.value) return
  if (isTyping.value) {
    stopTypewriter()
    return
  }
  if (hasNextLine.value) {
    currentIndex.value++
    startTypewriter(dialogues.value[currentIndex.value]?.text ?? '')
  }
}

const hasPrevLine = computed(() => currentIndex.value > 0)
const currentDialogue = computed(() => dialogues.value[currentIndex.value] ?? null)

function goToPrev() {
  if (!hasPrevLine.value) return
  currentIndex.value--
  startTypewriter(dialogues.value[currentIndex.value]?.text ?? '')
}

function goToNext() {
  if (!hasNextLine.value) return
  currentIndex.value++
  startTypewriter(dialogues.value[currentIndex.value]?.text ?? '')
}

// 即時模式：成員正在工作
const isWorking = computed(() => {
  return store.runningTasks.some(t => t.member_id === props.memberId)
})

const activeCardId = computed(() => {
  const task = store.runningTasks.find(t => t.member_id === props.memberId)
  return task?.task_id ?? null
})

const liveLines = computed(() => {
  if (!activeCardId.value) return []
  const raw = store.taskLogs.get(activeCardId.value) ?? []
  const parsed: string[] = []
  for (const line of raw) {
    try {
      const obj = JSON.parse(line)
      if (obj.type === 'assistant' && obj.message?.content) {
        for (const block of obj.message.content) {
          if (block.type === 'text' && block.text) {
            parsed.push(block.text)
          } else if (block.type === 'tool_use') {
            // 顯示工具名稱 + 輸入摘要
            const input = block.input || {}
            let detail = ''
            if (block.name === 'Read' && input.file_path) {
              detail = input.file_path
            } else if (block.name === 'Write' && input.file_path) {
              detail = input.file_path
            } else if (block.name === 'Edit' && input.file_path) {
              detail = input.file_path
            } else if (block.name === 'Bash' && input.command) {
              detail = input.command.length > 80 ? input.command.slice(0, 80) + '…' : input.command
            } else if (block.name === 'Glob' && input.pattern) {
              detail = input.pattern
            } else if (block.name === 'Grep' && input.pattern) {
              detail = input.pattern
            } else {
              const keys = Object.keys(input)
              if (keys.length > 0) detail = keys.join(', ')
            }
            parsed.push(detail ? `[${block.name}] ${detail}` : `[${block.name}]`)
          }
        }
      }
    } catch {
      // 過濾掉 worker 的處理中提示，只保留有意義的非 JSON 行
      const trimmed = line.trim()
      if (trimmed && !trimmed.startsWith('⏳')) parsed.push(trimmed)
    }
  }
  return parsed
})

// WebSocket 事件：即時新增對話
function onDialogueEvent(e: Event) {
  const detail = (e as CustomEvent).detail
  if (detail.member_id !== props.memberId) return

  dialogues.value.push({
    id: Date.now(),
    text: detail.text,
    dialogue_type: detail.dialogue_type,
    card_title: detail.card_title || '',
    created_at: new Date().toISOString(),
  })

  // 自動跳到最新對話
  setTimeout(() => {
    currentIndex.value = dialogues.value.length - 1
    startTypewriter(dialogues.value[currentIndex.value]?.text ?? '')
  }, 800)
}

// 載入對話
async function fetchDialogues() {
  try {
    dialogues.value = await apiClient.get<DialogueLine[]>(`/api/v1/members/${props.memberId}/dialogues?limit=30`)
    if (dialogues.value.length > 0 && !isWorking.value) {
      currentIndex.value = dialogues.value.length - 1
      startTypewriter(dialogues.value[currentIndex.value]?.text ?? '')
    }
  } catch (e) {
    console.error('Failed to fetch dialogues:', e)
  }
}

// Task history
interface TaskLogItem {
  id: number
  card_title: string
  project_name: string
  status: string
  duration_ms: number
  created_at: string
}

const history = ref<TaskLogItem[]>([])
const loading = ref(true)
const showTasks = ref(false)

// Skills
interface SkillInfo {
  name: string
  title: string
}
const skills = ref<SkillInfo[]>([])
const loadingSkills = ref(false)
const showSkills = ref(false)
const selectedSkill = ref<{ name: string; content: string } | null>(null)

async function fetchSkills() {
  loadingSkills.value = true
  try {
    skills.value = await apiClient.get<SkillInfo[]>(`/api/v1/members/${props.memberId}/skills`)
  } catch (e) {
    console.error('Failed to fetch skills:', e)
  }
  loadingSkills.value = false
}

async function viewSkill(skill: SkillInfo) {
  try {
    const data = await apiClient.get<{ content: string }>(`/api/v1/members/${props.memberId}/skills/${skill.name}`)
    selectedSkill.value = { name: skill.title, content: data.content }
  } catch (e) {
    console.error('Failed to fetch skill:', e)
  }
}

async function fetchHistory() {
  loading.value = true
  try {
    history.value = await apiClient.get<TaskLogItem[]>(`/api/v1/members/${props.memberId}/history?limit=8`)
  } catch (e) {
    console.error('Failed to fetch history:', e)
  }
  loading.value = false
}

function handleKeyDown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
  if (e.key === ' ' || e.key === 'Enter') {
    e.preventDefault()
    skipOrNext()
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
  window.addEventListener('aegis:member-dialogue', onDialogueEvent)
  fetchHistory()
  fetchSkills()
  fetchDialogues()
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
  window.removeEventListener('aegis:member-dialogue', onDialogueEvent)
  stopTypewriter()
  stopTts()
})

watch(() => props.memberId, () => {
  fetchHistory()
  fetchDialogues()
})

function providerColor(provider: string): string {
  if (provider === 'claude') return 'text-orange-400'
  if (provider === 'gemini') return 'text-blue-400'
  return 'text-slate-400'
}

function providerLabel(provider: string): string {
  if (provider === 'claude') return 'Claude'
  if (provider === 'gemini') return 'Gemini'
  return provider
}
</script>

<template>
  <!-- Backdrop - AVG Style -->
  <div class="fixed inset-0 z-50 pointer-events-auto" @click.self="emit('close')">
    <!-- Dark overlay with frosted glass -->
    <div class="absolute inset-0 bg-black/40 backdrop-blur-sm" @click="emit('close')" />

    <!-- Character portrait - large, left side -->
    <div class="absolute left-0 sm:left-8 bottom-36 sm:bottom-0 w-[260px] sm:w-[570px] h-[45vh] sm:h-[85vh]">
      <template v-if="portrait">
        <img
          :src="portrait.startsWith('http') ? portrait : `${portrait}`"
          :class="[
            'w-full h-full drop-shadow-2xl transition-all duration-300',
            portraitAspect === 'square'
              ? 'object-cover object-top'
              : 'object-contain object-bottom'
          ]"
        />
      </template>
      <template v-else>
        <div class="absolute bottom-0 left-1/2 -translate-x-1/2 w-48 h-72 rounded-t-full"
          :class="provider === 'claude' ? 'bg-orange-500/20' : 'bg-blue-500/20'"
        />
        <div class="absolute bottom-24 left-1/2 -translate-x-1/2 text-7xl">
          {{ provider === 'claude' ? '🟠' : '🔵' }}
        </div>
      </template>
    </div>

    <!-- Quest log - right side panel (toggle) -->
    <Transition name="slide-fade">
      <div v-if="showTasks" class="absolute right-4 sm:right-[50px] top-20 w-64 max-h-[40vh] overflow-hidden">
        <div class="bg-slate-900/40 backdrop-blur-sm rounded-lg border-2 border-slate-400/40 shadow-xl">
          <div class="p-3 max-h-[40vh] overflow-y-auto">
            <div v-if="loading" class="flex items-center justify-center py-4">
              <Loader2 class="w-5 h-5 text-slate-400 animate-spin" />
            </div>

            <div v-else-if="history.length === 0" class="text-center py-4 text-slate-500 text-sm">
              尚無任務記錄
            </div>

            <div v-else class="space-y-1">
              <div
                v-for="task in history"
                :key="task.id"
                class="flex items-center gap-2 py-1"
              >
                <div class="shrink-0">
                  <CheckCircle v-if="task.status === 'success'" class="w-4 h-4 text-emerald-400" />
                  <XCircle v-else-if="task.status === 'error' || task.status === 'timeout'" class="w-4 h-4 text-red-400" />
                  <Clock v-else class="w-4 h-4 text-amber-400" />
                </div>
                <div class="flex-1 min-w-0">
                  <p class="text-xs text-white truncate">{{ task.card_title }}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Skills panel - right side (toggle) -->
    <Transition name="slide-fade">
      <div v-if="showSkills" class="absolute right-4 sm:right-[50px] top-20 w-72 max-h-[50vh] overflow-hidden">
        <div class="bg-slate-900/40 backdrop-blur-sm rounded-lg border-2 border-purple-400/40 shadow-xl">
          <div class="p-3 max-h-[50vh] overflow-y-auto">
            <template v-if="!selectedSkill">
              <div v-if="loadingSkills" class="flex items-center justify-center py-4">
                <Loader2 class="w-5 h-5 text-purple-400 animate-spin" />
              </div>

              <div v-else-if="skills.length === 0" class="text-center py-4 text-slate-500 text-sm">
                尚未設定技能
              </div>

              <div v-else class="space-y-1">
                <button
                  v-for="skill in skills"
                  :key="skill.name"
                  @click="viewSkill(skill)"
                  class="w-full flex items-center gap-2 py-2 px-2 rounded hover:bg-purple-500/20 transition-colors text-left"
                >
                  <BookOpen class="w-4 h-4 text-purple-400 shrink-0" />
                  <div class="flex-1 min-w-0">
                    <p class="text-xs text-white truncate">{{ skill.title }}</p>
                    <p class="text-[10px] text-slate-500 font-mono">{{ skill.name }}.md</p>
                  </div>
                </button>
              </div>
            </template>

            <template v-else>
              <div class="flex items-center gap-2 mb-3">
                <button @click="selectedSkill = null" class="text-purple-400 hover:text-purple-300 text-xs">
                  ← 返回
                </button>
                <span class="text-white text-sm font-bold">{{ selectedSkill.name }}</span>
              </div>
              <pre class="text-xs text-slate-300 whitespace-pre-wrap font-mono bg-slate-900/50 rounded p-2 max-h-[35vh] overflow-y-auto">{{ selectedSkill.content }}</pre>
            </template>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Dialog box - bottom, full width with frame -->
    <div class="absolute bottom-24 sm:bottom-4 left-2 right-2 sm:left-[50px] sm:right-[50px]">
      <div class="bg-slate-900/40 backdrop-blur-sm rounded-lg border-2 border-slate-400/40 shadow-2xl">
        <!-- 左上：人物/身分 -->
        <div class="absolute -top-4 left-6">
          <div class="bg-slate-800 rounded px-4 py-1 border border-slate-500/50">
            <span class="text-white font-bold">{{ name }}</span>
            <span class="text-xs text-slate-400 ml-2">{{ role || '開發者' }}</span>
          </div>
        </div>

        <!-- 右上：上一頁/下一頁/關閉 -->
        <div class="absolute -top-4 right-6" @click.stop>
          <div class="bg-slate-800 rounded px-3 py-1 border border-slate-500/50 flex items-center gap-1">
            <template v-if="dialogues.length > 1 && !isWorking">
              <button
                @click="goToPrev"
                :disabled="!hasPrevLine"
                class="p-0.5 rounded transition-colors"
                :class="hasPrevLine ? 'text-white/70 hover:text-white hover:bg-white/10' : 'text-slate-700 cursor-default'"
              >
                <ChevronLeft class="w-3.5 h-3.5" />
              </button>
              <span class="text-[10px] text-slate-400 tabular-nums">{{ currentIndex + 1 }}/{{ dialogues.length }}</span>
              <button
                @click="goToNext"
                :disabled="!hasNextLine"
                class="p-0.5 rounded transition-colors"
                :class="hasNextLine ? 'text-white/70 hover:text-white hover:bg-white/10' : 'text-slate-700 cursor-default'"
              >
                <ChevronRight class="w-3.5 h-3.5" />
              </button>
              <span class="mx-0.5 text-slate-600">|</span>
            </template>
            <button
              @click="toggleTts"
              class="p-0.5 rounded transition-colors"
              :class="ttsEnabled ? 'text-emerald-400 hover:bg-white/10' : 'text-slate-600 hover:text-slate-400 hover:bg-white/10'"
              :title="ttsEnabled ? '語音開啟' : '語音關閉'"
            >
              <Volume2 v-if="ttsEnabled" class="w-3.5 h-3.5" />
              <VolumeX v-else class="w-3.5 h-3.5" />
            </button>
            <button
              @click="emit('close')"
              class="p-0.5 rounded text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
            >
              <X class="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <!-- Dialog content -->
        <div class="px-6 py-6 pt-8 min-h-[150px] flex flex-col cursor-pointer" @click="skipOrNext">
          <!-- 即時模式：工作中 -->
          <div v-if="isWorking" class="flex-1">
            <div class="font-mono text-sm text-emerald-300/90 overflow-y-auto max-h-[120px] leading-relaxed">
              <div v-for="(line, i) in liveLines.slice(-6)" :key="i" class="truncate">{{ line }}</div>
              <span class="animate-pulse text-emerald-400">_</span>
            </div>
          </div>

          <!-- 對話模式：AVG 打字機 -->
          <div v-else class="flex-1">
            <p class="text-white text-lg leading-relaxed font-bold" style="text-shadow: -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000;">
              {{ dialogues.length > 0 ? displayedText : (history.length > 0
                ? `已完成 ${history.filter(t => t.status === 'success').length} 個任務，隨時準備好接受新挑戰！`
                : '準備好開始工作了！') }}
              <span v-if="isTyping" class="animate-pulse">|</span>
            </p>

            <!-- 任務標題 + 時間戳 -->
            <p v-if="currentDialogue && !isTyping" class="text-xs text-white/80 mt-2 font-bold" style="text-shadow: -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000;">
              {{ currentDialogue.card_title }} · {{ new Date(currentDialogue.created_at.endsWith('Z') ? currentDialogue.created_at : currentDialogue.created_at + 'Z').toLocaleString('zh-TW', { timeZone: store.settings.timezone || 'Asia/Taipei' }) }}
            </p>
          </div>
        </div>

        <!-- 右下：任務/技能/模型名稱 -->
        <div class="absolute -bottom-3 right-4 sm:right-6 flex items-center gap-1 sm:gap-2">
          <button
            @click="showTasks = !showTasks; if (showTasks) showSkills = false"
            class="flex items-center justify-center gap-1 min-w-[44px] min-h-[44px] sm:min-w-0 sm:min-h-0 px-3 py-2 sm:py-1 bg-slate-700 text-slate-300 hover:text-white hover:bg-slate-600 rounded transition-colors text-xs"
            :class="showTasks ? 'bg-emerald-600 text-white' : ''"
          >
            <ListTodo :size="14" class="sm:w-3 sm:h-3" />
            <span class="hidden sm:inline">任務</span>
          </button>
          <button
            @click="showSkills = !showSkills; if (showSkills) { showTasks = false; selectedSkill = null }"
            class="flex items-center justify-center gap-1 min-w-[44px] min-h-[44px] sm:min-w-0 sm:min-h-0 px-3 py-2 sm:py-1 bg-slate-700 text-slate-300 hover:text-white hover:bg-slate-600 rounded transition-colors text-xs"
            :class="showSkills ? 'bg-purple-600 text-white' : ''"
          >
            <BookOpen :size="14" class="sm:w-3 sm:h-3" />
            <span class="hidden sm:inline">技能</span>
          </button>
          <div class="px-3 py-2 sm:py-1 bg-slate-700 rounded text-xs">
            <span :class="providerColor(provider)">{{ providerLabel(provider) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.slide-fade-enter-active,
.slide-fade-leave-active {
  transition: all 0.2s ease;
}
.slide-fade-enter-from,
.slide-fade-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
</style>
