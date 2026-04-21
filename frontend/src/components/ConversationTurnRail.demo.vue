<script setup lang="ts">
import { computed, ref } from 'vue'
import ConversationTurnRail, { type TurnItem } from './ConversationTurnRail.vue'
import { useTurnObserver } from '../composables/useTurnObserver'

const TURN_COUNT = 100

const turns = computed<TurnItem[]>(() =>
  Array.from({ length: TURN_COUNT }, (_, i) => ({
    id: `turn-${i}`,
    label: `Turn ${i + 1}`,
  })),
)

const scrollContainer = ref<HTMLElement | null>(null)
const { activeTurnIndex } = useTurnObserver(scrollContainer)

function onNavigate(index: number): void {
  const root = scrollContainer.value
  if (!root) return
  const target = root.querySelector<HTMLElement>(
    `[data-turn-index="${index}"]`,
  )
  target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const lastEmittedIndex = ref<number>(-1)
function onRailNavigate(index: number): void {
  lastEmittedIndex.value = index
  onNavigate(index)
}
</script>

<template>
  <div class="flex h-screen w-full bg-slate-950 text-slate-200">
    <aside class="w-64 border-r border-slate-800 p-4 text-sm">
      <h1 class="mb-2 text-base font-semibold text-slate-100">
        ConversationTurnRail Demo
      </h1>
      <p class="mb-4 text-xs text-slate-400">
        100 個假資料 turn，驗證軌道 + IntersectionObserver 行為。
      </p>
      <dl class="space-y-1 text-xs">
        <div class="flex justify-between">
          <dt class="text-slate-500">Active turn</dt>
          <dd class="font-mono text-sky-300">{{ activeTurnIndex }}</dd>
        </div>
        <div class="flex justify-between">
          <dt class="text-slate-500">Last emitted</dt>
          <dd class="font-mono text-emerald-300">{{ lastEmittedIndex }}</dd>
        </div>
      </dl>
    </aside>

    <main class="relative flex-1">
      <div
        ref="scrollContainer"
        class="h-full overflow-y-auto px-8 py-6"
      >
        <section
          v-for="(turn, index) in turns"
          :key="turn.id"
          :data-turn-index="index"
          class="mb-4 rounded-xl border border-slate-800 bg-slate-900/50 p-6"
        >
          <h2 class="mb-2 text-sm font-semibold text-slate-100">
            {{ turn.label }}
          </h2>
          <p class="text-xs text-slate-400">
            模擬一段長對話的 turn 內容。捲動時右側 rail 會亮起對應的點。
          </p>
          <div class="mt-4 h-48 rounded bg-slate-800/40" />
        </section>
      </div>

      <div class="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2">
        <ConversationTurnRail
          :turns="turns"
          :active-turn-index="activeTurnIndex"
          @navigate="onRailNavigate"
        />
      </div>
    </main>
  </div>
</template>
