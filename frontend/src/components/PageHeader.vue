<template>
  <div ref="headerEl" class="h-16 flex items-center gap-2 sm:gap-4 px-4 sm:px-6 border-b border-slate-700 shrink-0 min-w-0">
    <!-- Icon + Project selector -->
    <div class="flex items-center gap-2 min-w-0">
      <button
        @click="selectAdjacentProject(-1)"
        :disabled="!canGoPrev"
        class="p-1 rounded transition-colors"
        :class="canGoPrev ? 'text-slate-400 hover:text-emerald-400 hover:bg-slate-700' : 'text-slate-700 cursor-default'"
      >
        <ChevronLeft class="w-3.5 sm:w-4 h-3.5 sm:h-4" />
      </button>
      <button
        ref="triggerEl"
        @click="showDropdown = !showDropdown"
        class="flex items-center gap-1.5 sm:gap-2 min-w-0 group"
      >
        <component :is="icon" class="w-4 sm:w-5 h-4 sm:h-5 text-emerald-400 shrink-0" />
        <span class="text-sm sm:text-lg font-bold text-slate-100 truncate group-hover:text-emerald-400 transition-colors max-w-[140px] sm:max-w-none">
          {{ currentProject()?.name || '選擇專案' }}
        </span>
        <ChevronDown
          class="w-3 sm:w-4 h-3 sm:h-4 text-slate-500 shrink-0 transition-transform"
          :class="{ 'rotate-180': showDropdown }"
        />
      </button>
      <button
        @click="selectAdjacentProject(1)"
        :disabled="!canGoNext"
        class="p-1 rounded transition-colors"
        :class="canGoNext ? 'text-slate-400 hover:text-emerald-400 hover:bg-slate-700' : 'text-slate-700 cursor-default'"
      >
        <ChevronRight class="w-3.5 sm:w-4 h-3.5 sm:h-4" />
      </button>
    </div>

    <!-- 右側 slot -->
    <div class="ml-auto flex items-center gap-2">
      <slot />
    </div>

    <!-- Dropdown (Teleport to body) -->
    <Teleport to="body">
      <template v-if="showDropdown">
        <div class="fixed inset-0 z-40" @click="showDropdown = false" />
        <div
          class="fixed z-50 w-64 bg-slate-800 rounded-lg border border-slate-700 shadow-xl max-h-72 overflow-y-auto"
          :style="dropdownStyle"
        >
          <div class="py-1">
            <button
              v-for="p in projects"
              :key="p.id"
              @click="onSelect(p.id)"
              class="w-full flex items-center gap-2 px-3 py-2.5 text-sm transition-colors"
              :class="selectedProjectId === p.id
                ? 'bg-emerald-500/20 text-emerald-400'
                : 'text-slate-300 hover:bg-slate-700'"
            >
              <FolderOpen class="w-4 h-4 shrink-0" :class="selectedProjectId === p.id ? 'text-emerald-400' : 'text-slate-500'" />
              <span class="truncate">{{ p.name }}</span>
              <span v-if="p.is_system" class="ml-auto text-[10px] text-slate-600">系統</span>
            </button>
          </div>
        </div>
      </template>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { FolderOpen, ChevronDown, ChevronLeft, ChevronRight } from 'lucide-vue-next'
import { useProjectSelector } from '../composables/useProjectSelector'
import type { Component } from 'vue'

defineProps<{
  icon: Component
}>()

const { projects, selectedProjectId, currentProject, selectProject, selectAdjacentProject } = useProjectSelector()

const canGoPrev = computed(() => {
  const idx = projects.value.findIndex(p => p.id === selectedProjectId.value)
  return idx > 0
})
const canGoNext = computed(() => {
  const idx = projects.value.findIndex(p => p.id === selectedProjectId.value)
  return idx >= 0 && idx < projects.value.length - 1
})
const showDropdown = ref(false)
const triggerEl = ref<HTMLElement | null>(null)

const dropdownStyle = computed(() => {
  if (!triggerEl.value) return {}
  const rect = triggerEl.value.getBoundingClientRect()
  return {
    top: `${rect.bottom + 8}px`,
    left: `${rect.left}px`,
  }
})

function onSelect(id: number) {
  selectProject(id)
  showDropdown.value = false
}
</script>
