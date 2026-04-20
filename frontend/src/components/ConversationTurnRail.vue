<script setup lang="ts">
import { computed } from 'vue'

export interface TurnItem {
  id: string | number
  label?: string
}

const props = withDefaults(
  defineProps<{
    turns: ReadonlyArray<TurnItem>
    activeTurnIndex?: number
    ariaLabel?: string
  }>(),
  {
    activeTurnIndex: -1,
    ariaLabel: '對話輪次導航',
  },
)

const emit = defineEmits<{
  navigate: [index: number]
}>()

const items = computed(() =>
  props.turns.map((turn, index) => ({
    index,
    id: turn.id,
    label: turn.label ?? `#${index + 1}`,
    active: index === props.activeTurnIndex,
  })),
)

function onClick(index: number): void {
  emit('navigate', index)
}

function onKeydown(event: KeyboardEvent, index: number): void {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    emit('navigate', index)
  }
}
</script>

<template>
  <nav
    class="group/rail pointer-events-auto flex h-full select-none items-center"
    :aria-label="ariaLabel"
  >
    <ul
      class="flex flex-col gap-1.5 rounded-full border border-slate-700/40 bg-slate-900/60 px-1.5 py-2 backdrop-blur transition-all duration-200 group-hover/rail:gap-2 group-hover/rail:px-2"
    >
      <li
        v-for="item in items"
        :key="item.id"
        class="relative flex items-center justify-end"
      >
        <button
          type="button"
          :data-turn-index="item.index"
          :aria-label="`跳到 ${item.label}`"
          :aria-current="item.active ? 'true' : undefined"
          class="flex items-center gap-2 rounded-full outline-none transition-all duration-150 focus-visible:ring-2 focus-visible:ring-sky-400/60"
          :class="[
            item.active
              ? 'text-sky-300'
              : 'text-slate-500 hover:text-slate-200',
          ]"
          @click="onClick(item.index)"
          @keydown="onKeydown($event, item.index)"
        >
          <span
            class="pointer-events-none max-w-0 overflow-hidden whitespace-nowrap text-xs font-medium opacity-0 transition-all duration-200 group-hover/rail:max-w-[10rem] group-hover/rail:pl-1 group-hover/rail:pr-2 group-hover/rail:opacity-100"
          >
            {{ item.label }}
          </span>
          <span
            class="block rounded-full transition-all duration-150"
            :class="[
              item.active
                ? 'h-2.5 w-2.5 bg-sky-400 shadow-[0_0_0_3px_rgba(56,189,248,0.18)]'
                : 'h-1.5 w-1.5 bg-slate-500 hover:h-2 hover:w-2 hover:bg-slate-200',
            ]"
          />
        </button>
      </li>
    </ul>
  </nav>
</template>
