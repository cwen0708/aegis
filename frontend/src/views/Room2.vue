<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import type Phaser from 'phaser'

const canvasRef = ref<HTMLDivElement>()
const error = ref('')
let game: Phaser.Game | null = null

onMounted(async () => {
  try {
    const { createRoom2Game } = await import('../game2/Room2Scene')
    if (canvasRef.value) {
      game = createRoom2Game('room2-canvas')
    } else {
      error.value = 'Canvas element not found'
    }
  } catch (e: any) {
    error.value = e.message || String(e)
    console.error('[Room2] Failed to create game:', e)
  }
})

onUnmounted(() => {
  game?.destroy(true)
  game = null
})
</script>

<template>
  <div class="w-full h-full bg-[#1a1a2e] relative">
    <div v-if="error" class="absolute inset-0 flex items-center justify-center z-10">
      <div class="bg-red-900/50 border border-red-500/30 rounded-lg p-6 max-w-md">
        <p class="text-red-400 text-sm font-mono">{{ error }}</p>
      </div>
    </div>
    <div id="room2-canvas" ref="canvasRef" class="w-full h-full" />
  </div>
</template>
