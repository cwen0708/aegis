<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import type Phaser from 'phaser'

const canvasRef = ref<HTMLDivElement>()
let game: Phaser.Game | null = null

onMounted(async () => {
  const { createRoom2Game } = await import('../game2/Room2Scene')
  if (canvasRef.value) {
    game = createRoom2Game(canvasRef.value.id)
  }
})

onUnmounted(() => {
  game?.destroy(true)
  game = null
})
</script>

<template>
  <div class="fixed inset-0 bg-[#1a1a2e]">
    <div id="room2-canvas" ref="canvasRef" class="w-full h-full" />
  </div>
</template>
