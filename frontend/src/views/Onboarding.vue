<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { Rocket, CheckCircle2, ChevronRight, Terminal, Users, Kanban, Clock, Sparkles } from 'lucide-vue-next'
import { useAegisStore } from '../stores/aegis'

const router = useRouter()
const store = useAegisStore()
const currentStep = ref(0)
const completing = ref(false)

interface Step {
  id: string
  title: string
  description: string
  icon: any
  details: string[]
  action?: { label: string; route: string }
}

const steps: Step[] = [
  {
    id: 'welcome',
    title: '歡迎使用 Aegis',
    description: 'Aegis 是一個 AI 代理管理儀表板，讓你可以視覺化管理多個 AI 助手協同工作。',
    icon: Rocket,
    details: [
      '管理多個 Claude 和 Gemini 帳號',
      '將任務分配給不同的 AI 代理',
      '監控用量和執行狀態',
      '排程自動化任務',
    ],
  },
  {
    id: 'cli',
    title: '安裝 CLI 工具',
    description: '確保伺服器已安裝必要的 CLI 工具，這是執行 AI 任務的基礎。',
    icon: Terminal,
    details: [
      'Claude CLI：用於執行 Claude Code 任務',
      'Gemini CLI：用於執行 Gemini 任務',
      '可在「設定」頁面一鍵安裝',
    ],
    action: { label: '前往設定', route: '/settings' },
  },
  {
    id: 'team',
    title: '建立 AI 團隊',
    description: '創建虛擬的 AI 團隊成員，每個成員可以綁定不同的帳號。',
    icon: Users,
    details: [
      '建立團隊成員（如：資深開發者、測試工程師）',
      '設定成員的角色和描述',
      '綁定 AI 帳號到成員',
      '成員會在辦公室場景中以角色呈現',
    ],
    action: { label: '前往團隊', route: '/team' },
  },
  {
    id: 'projects',
    title: '設定專案',
    description: '新增要管理的專案，指定專案路徑。',
    icon: Kanban,
    details: [
      '新增專案並設定名稱和路徑',
      '路徑是 AI 執行任務時的工作目錄',
      '可以在看板上建立任務卡片',
      '將卡片分配給團隊成員執行',
    ],
    action: { label: '前往看板', route: '/kanban' },
  },
  {
    id: 'cron',
    title: '排程任務（選用）',
    description: '設定定時執行的自動化任務。',
    icon: Clock,
    details: [
      '使用 Cron 表達式設定執行時間',
      '每個排程可以指定要執行的 prompt',
      '適合定期檢查、報告生成等任務',
    ],
    action: { label: '前往排程', route: '/cron' },
  },
  {
    id: 'ready',
    title: '準備就緒！',
    description: '你已經了解 Aegis 的基本功能，可以開始使用了。',
    icon: Sparkles,
    details: [
      '在辦公室查看 AI 成員的工作狀態',
      '透過看板管理和分配任務',
      '隨時可以在設定中調整配置',
      '這個引導頁面可以從選單再次進入',
    ],
  },
]

const progress = computed(() => ((currentStep.value + 1) / steps.length) * 100)
const currentStepData = computed(() => steps[currentStep.value]!)

function nextStep() {
  if (currentStep.value < steps.length - 1) {
    currentStep.value++
  }
}

function prevStep() {
  if (currentStep.value > 0) {
    currentStep.value--
  }
}

function goToStep(index: number) {
  currentStep.value = index
}

async function completeOnboarding() {
  completing.value = true
  try {
    await store.updateSettings({ onboarding_completed: 'true' })
    router.push('/dashboard')
  } finally {
    completing.value = false
  }
}

function skipOnboarding() {
  router.push('/dashboard')
}
</script>

<template>
  <div class="h-full flex flex-col bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
    <!-- Header -->
    <div class="h-16 shrink-0 border-b border-slate-700/50 px-8 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-400 to-cyan-500 flex items-center justify-center">
          <Rocket class="w-5 h-5 text-white" />
        </div>
        <div>
          <h1 class="text-lg font-bold text-slate-100">開始使用 Aegis</h1>
          <p class="text-xs text-slate-400">設定引導 · 步驟 {{ currentStep + 1 }} / {{ steps.length }}</p>
        </div>
      </div>
      <button
        @click="skipOnboarding"
        class="text-sm text-slate-400 hover:text-slate-200 transition-colors"
      >
        跳過引導
      </button>
    </div>

    <!-- Progress bar -->
    <div class="h-1 bg-slate-800">
      <div
        class="h-full bg-gradient-to-r from-emerald-400 to-cyan-500 transition-all duration-500"
        :style="{ width: `${progress}%` }"
      ></div>
    </div>

    <!-- Content -->
    <div class="flex-1 overflow-auto">
      <div class="max-w-4xl mx-auto p-4 sm:p-8">
        <!-- Step indicators (horizontal numbers) -->
        <div class="flex items-center justify-center gap-2 sm:gap-4 mb-6">
          <button
            v-for="(step, index) in steps"
            :key="step.id"
            @click="goToStep(index)"
            class="flex flex-col items-center gap-1 transition-all"
          >
            <div :class="[
              'w-8 h-8 sm:w-9 sm:h-9 rounded-full flex items-center justify-center text-xs sm:text-sm font-bold transition-all',
              index < currentStep
                ? 'bg-emerald-500 text-white'
                : index === currentStep
                ? 'bg-cyan-500 text-white ring-2 ring-cyan-400/30 ring-offset-2 ring-offset-slate-900'
                : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
            ]">
              <CheckCircle2 v-if="index < currentStep" class="w-4 h-4" />
              <span v-else>{{ index + 1 }}</span>
            </div>
            <span :class="[
              'hidden sm:block text-xs font-medium whitespace-nowrap',
              index === currentStep ? 'text-cyan-400' : index < currentStep ? 'text-emerald-400' : 'text-slate-500'
            ]">{{ step.title }}</span>
          </button>
        </div>

        <!-- Step content -->
        <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-5 sm:p-8">
          <div class="flex items-start gap-3 sm:gap-4 mb-6">
            <div class="w-12 h-12 sm:w-14 sm:h-14 shrink-0 rounded-2xl bg-gradient-to-br from-emerald-400/20 to-cyan-500/20 flex items-center justify-center">
              <component :is="currentStepData.icon" class="w-6 h-6 sm:w-7 sm:h-7 text-cyan-400" />
            </div>
            <div class="min-w-0">
              <h2 class="text-xl sm:text-2xl font-bold text-slate-100 mb-1 sm:mb-2">{{ currentStepData.title }}</h2>
              <p class="text-sm sm:text-base text-slate-400">{{ currentStepData.description }}</p>
            </div>
          </div>

          <div class="space-y-2 sm:space-y-3 mb-6 sm:mb-8">
            <div
              v-for="(detail, i) in currentStepData.details"
              :key="i"
              class="flex items-start gap-3 p-3 bg-slate-900/50 rounded-lg"
            >
              <div class="w-5 h-5 rounded-full bg-emerald-500/20 flex items-center justify-center mt-0.5 shrink-0">
                <CheckCircle2 class="w-3 h-3 text-emerald-400" />
              </div>
              <span class="text-sm text-slate-300">{{ detail }}</span>
            </div>
          </div>

          <!-- Action button for step -->
          <div v-if="currentStepData.action" class="mb-6 sm:mb-8">
            <router-link
              :to="currentStepData.action!.route"
              class="inline-flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg text-sm font-medium transition-colors"
            >
              {{ currentStepData.action!.label }}
              <ChevronRight class="w-4 h-4" />
            </router-link>
          </div>

          <!-- Navigation -->
          <div class="flex items-center justify-between pt-4 sm:pt-6 border-t border-slate-700">
            <button
              v-if="currentStep > 0"
              @click="prevStep"
              class="px-4 py-2 text-slate-400 hover:text-slate-200 text-sm font-medium transition-colors"
            >
              上一步
            </button>
            <div v-else></div>

            <div class="flex gap-3">
              <button
                v-if="currentStep < steps.length - 1"
                @click="nextStep"
                class="flex items-center gap-2 px-5 sm:px-6 py-2.5 bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-600 hover:to-cyan-600 text-white rounded-lg font-bold text-sm transition-all shadow-lg shadow-emerald-500/20"
              >
                下一步
                <ChevronRight class="w-4 h-4" />
              </button>
              <button
                v-else
                @click="completeOnboarding"
                :disabled="completing"
                class="flex items-center gap-2 px-5 sm:px-6 py-2.5 bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-600 hover:to-cyan-600 disabled:opacity-50 text-white rounded-lg font-bold text-sm transition-all shadow-lg shadow-emerald-500/20"
              >
                <Sparkles class="w-4 h-4" />
                {{ completing ? '處理中...' : '完成設定' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
