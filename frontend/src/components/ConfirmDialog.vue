<script setup lang="ts">
defineProps<{
  show: boolean
  title?: string
  message: string
  confirmText?: string
  confirmClass?: string
}>()

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()
</script>

<template>
  <Teleport to="body">
    <div v-if="show" class="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-[60]">
      <div class="bg-slate-800 border border-slate-700 rounded-2xl p-6 w-full max-w-sm shadow-2xl">
        <h3 class="text-lg font-bold text-slate-100 mb-2">{{ title || '確認操作' }}</h3>
        <p class="text-sm text-slate-400 mb-6">{{ message }}</p>
        <div class="flex justify-end gap-3">
          <button @click="emit('cancel')" class="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">取消</button>
          <button
            @click="emit('confirm')"
            class="px-4 py-2 text-sm font-medium text-white rounded-lg transition-colors"
            :class="confirmClass || 'bg-red-500 hover:bg-red-600'"
          >
            {{ confirmText || '確認' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
