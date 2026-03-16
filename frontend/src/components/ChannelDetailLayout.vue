<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ArrowLeft, Save, Loader2 } from 'lucide-vue-next'

defineProps<{
  icon: string
  label: string
  loading: boolean
  saving: boolean
  enabled: boolean
}>()

const emit = defineEmits<{
  save: []
  'update:enabled': [val: boolean]
}>()

const router = useRouter()
</script>

<template>
  <div class="space-y-6">
    <!-- Back + Title -->
    <div class="flex items-center gap-3">
      <button
        @click="router.push('/settings/channels')"
        class="p-2 rounded-lg hover:bg-slate-800 transition-colors"
      >
        <ArrowLeft class="w-4 h-4 text-slate-400" />
      </button>
      <span class="text-lg">{{ icon }}</span>
      <h2 class="text-lg font-bold text-slate-200">{{ label }}</h2>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex justify-center py-12">
      <Loader2 class="w-8 h-8 animate-spin text-slate-400" />
    </div>

    <template v-else>
      <div class="bg-slate-900/50 rounded-xl border border-slate-700/50 p-6 space-y-5">
        <!-- Enable toggle -->
        <div class="flex items-center justify-between pb-4 border-b border-slate-700/50">
          <div>
            <span class="text-sm font-medium text-slate-200">啟用頻道</span>
            <p class="text-xs text-slate-500 mt-0.5">啟用後系統會嘗試連線此頻道</p>
          </div>
          <button
            @click="emit('update:enabled', !enabled)"
            :class="[
              'relative inline-flex h-6 w-11 items-center rounded-full transition-colors',
              enabled ? 'bg-emerald-600' : 'bg-slate-600'
            ]"
          >
            <span
              :class="[
                'inline-block h-4 w-4 transform rounded-full bg-white transition-transform',
                enabled ? 'translate-x-6' : 'translate-x-1'
              ]"
            />
          </button>
        </div>

        <!-- Slot: channel-specific fields -->
        <slot />
      </div>

      <!-- Slot: extra sections (below the main card) -->
      <slot name="extra" />

      <!-- Save Button -->
      <div class="flex justify-end">
        <button
          @click="emit('save')"
          :disabled="saving"
          class="flex items-center gap-2 px-5 py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-all"
        >
          <Loader2 v-if="saving" class="w-4 h-4 animate-spin" />
          <Save v-else class="w-4 h-4" />
          儲存設定
        </button>
      </div>
    </template>
  </div>
</template>
