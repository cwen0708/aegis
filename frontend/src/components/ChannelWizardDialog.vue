<script setup lang="ts">
import { watch } from 'vue'
import { useChannelWizard } from '../composables/useChannelWizard'
import { useRouter } from 'vue-router'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ close: [] }>()

const router = useRouter()
const { platforms, currentStep, selectedPlatform, canGoNext, next, back, reset, selectPlatform } =
  useChannelWizard()

watch(
  () => props.show,
  (v) => {
    if (v) reset()
  },
)

function handleNext() {
  if (currentStep.value === 0 && selectedPlatform.value) {
    router.push(`/settings/channels/${selectedPlatform.value}`)
    emit('close')
  } else {
    next()
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="show"
      class="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-[60]"
      @click.self="emit('close')"
    >
      <div class="bg-slate-800 border border-slate-700 rounded-2xl w-full max-w-md shadow-2xl">
        <!-- Header -->
        <div class="flex items-center justify-between px-6 pt-5 pb-3">
          <h3 class="text-lg font-bold text-slate-100">新增頻道</h3>
          <button @click="emit('close')" class="text-slate-500 hover:text-slate-300 text-xl leading-none">&times;</button>
        </div>

        <!-- Step indicator -->
        <div class="px-6 pb-4">
          <p class="text-sm text-slate-400">選擇要連接的通訊平台</p>
        </div>

        <!-- Step 0: Platform selection -->
        <div v-if="currentStep === 0" class="px-6 pb-2 space-y-2 max-h-[50vh] overflow-y-auto">
          <button
            v-for="p in platforms"
            :key="p.name"
            @click="selectPlatform(p.name)"
            :class="[
              'w-full flex items-center gap-3 px-4 py-3 rounded-xl border transition-all text-left',
              selectedPlatform === p.name
                ? 'border-teal-500 bg-teal-500/10'
                : 'border-slate-700/50 hover:border-slate-600 hover:bg-slate-700/30',
            ]"
          >
            <div :class="['w-9 h-9 rounded-lg flex items-center justify-center text-base shrink-0', p.iconColor]">
              {{ p.icon }}
            </div>
            <span class="font-medium text-slate-200">{{ p.label }}</span>
          </button>
        </div>

        <!-- Footer -->
        <div class="flex justify-between px-6 py-4 border-t border-slate-700/50 mt-2">
          <button
            v-if="currentStep > 0"
            @click="back"
            class="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
          >
            上一步
          </button>
          <span v-else />
          <div class="flex gap-3">
            <button @click="emit('close')" class="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors">
              取消
            </button>
            <button
              @click="handleNext"
              :disabled="!canGoNext"
              class="px-5 py-2 text-sm font-medium text-white bg-teal-600 hover:bg-teal-500 disabled:opacity-40 disabled:cursor-not-allowed rounded-lg transition-colors"
            >
              下一步
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
