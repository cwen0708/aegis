<script setup lang="ts">
import { useAegisStore } from '../stores/aegis'
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-vue-next'

const store = useAegisStore()

function removeToast(id: number) {
  store.toasts = store.toasts.filter(t => t.id !== id)
}
</script>

<template>
  <Teleport to="body">
    <div class="fixed top-4 right-4 z-[70] flex flex-col gap-2 pointer-events-none">
      <TransitionGroup name="toast">
        <div
          v-for="toast in store.toasts"
          :key="toast.id"
          class="pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-xl border shadow-xl backdrop-blur-md min-w-[280px] max-w-[400px]"
          :class="{
            'bg-emerald-900/80 border-emerald-500/30 text-emerald-200': toast.type === 'success',
            'bg-red-900/80 border-red-500/30 text-red-200': toast.type === 'error',
            'bg-blue-900/80 border-blue-500/30 text-blue-200': toast.type === 'info',
          }"
        >
          <CheckCircle2 v-if="toast.type === 'success'" class="w-5 h-5 shrink-0" />
          <AlertCircle v-else-if="toast.type === 'error'" class="w-5 h-5 shrink-0" />
          <Info v-else class="w-5 h-5 shrink-0" />
          <span class="text-sm font-medium flex-1">{{ toast.message }}</span>
          <button @click="removeToast(toast.id)" class="opacity-60 hover:opacity-100 shrink-0">
            <X class="w-4 h-4" />
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-enter-active {
  transition: all 0.3s ease-out;
}
.toast-leave-active {
  transition: all 0.2s ease-in;
}
.toast-enter-from {
  opacity: 0;
  transform: translateX(100px);
}
.toast-leave-to {
  opacity: 0;
  transform: translateX(100px);
}
</style>
