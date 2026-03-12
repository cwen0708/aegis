<template>
  <div class="flex items-center gap-2 sm:gap-4 px-4 sm:px-6 py-3 border-b border-slate-700/50 shrink-0 min-w-0">
    <!-- Icon + Project selector -->
    <div class="flex items-center gap-2 min-w-0 relative">
      <button
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

      <!-- Dropdown -->
      <Teleport to="body">
        <div
          v-if="showDropdown"
          class="fixed inset-0 z-40"
          @click="showDropdown = false"
        />
      </Teleport>
      <div
        v-if="showDropdown"
        class="absolute top-full left-0 mt-2 w-64 bg-slate-800 rounded-lg border border-slate-700 shadow-xl z-50 max-h-72 overflow-y-auto"
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
    </div>

    <!-- 右側 slot -->
    <div class="ml-auto flex items-center gap-2">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { FolderOpen, ChevronDown } from 'lucide-vue-next'
import { useProjectSelector } from '../composables/useProjectSelector'
import type { Component } from 'vue'

defineProps<{
  icon: Component
}>()

const { projects, selectedProjectId, currentProject, selectProject } = useProjectSelector()
const showDropdown = ref(false)

function onSelect(id: number) {
  selectProject(id)
  showDropdown.value = false
}
</script>
