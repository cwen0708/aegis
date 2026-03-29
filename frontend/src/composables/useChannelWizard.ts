import { ref, computed } from 'vue'

export interface PlatformOption {
  name: string
  label: string
  icon: string
  iconColor: string
}

const platforms: PlatformOption[] = [
  { name: 'slack', label: 'Slack', icon: '💼', iconColor: 'bg-purple-500/20' },
  { name: 'discord', label: 'Discord', icon: '🎮', iconColor: 'bg-indigo-500/20' },
  { name: 'telegram', label: 'Telegram', icon: '✈️', iconColor: 'bg-sky-500/20' },
  { name: 'wecom', label: '企業微信', icon: '🏢', iconColor: 'bg-blue-500/20' },
  { name: 'email', label: 'Email (IMAP/SMTP)', icon: '📧', iconColor: 'bg-amber-500/20' },
  { name: 'feishu', label: '飛書 / Lark', icon: '🐦', iconColor: 'bg-cyan-500/20' },
  { name: 'line', label: 'LINE', icon: '💬', iconColor: 'bg-green-500/20' },
]

export function useChannelWizard() {
  const currentStep = ref(0)
  const selectedPlatform = ref<string | null>(null)

  const canGoNext = computed(() => {
    if (currentStep.value === 0) return selectedPlatform.value !== null
    return false
  })

  function next() {
    if (canGoNext.value) currentStep.value++
  }

  function back() {
    if (currentStep.value > 0) currentStep.value--
  }

  function reset() {
    currentStep.value = 0
    selectedPlatform.value = null
  }

  function selectPlatform(name: string) {
    selectedPlatform.value = name
  }

  return {
    platforms,
    currentStep,
    selectedPlatform,
    canGoNext,
    next,
    back,
    reset,
    selectPlatform,
  }
}
