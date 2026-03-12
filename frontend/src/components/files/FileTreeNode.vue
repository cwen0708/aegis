<template>
  <div>
    <button
      class="w-full flex items-center gap-1.5 py-1 px-2 rounded text-left transition-colors hover:bg-slate-700/50"
      :class="[
        entry.path === selectedPath ? 'bg-emerald-500/15 text-emerald-400' : 'text-slate-300',
      ]"
      :style="{ paddingLeft: `${depth * 16 + 8}px` }"
      @click="handleClick"
    >
      <!-- 展開箭頭（目錄） -->
      <ChevronRight
        v-if="entry.type === 'directory'"
        class="w-3.5 h-3.5 shrink-0 transition-transform"
        :class="expanded ? 'rotate-90' : ''"
      />
      <span v-else class="w-3.5 h-3.5 shrink-0" />

      <!-- Icon -->
      <component
        :is="entry.type === 'directory' ? (expanded ? FolderOpen : Folder) : FileIcon"
        class="w-4 h-4 shrink-0"
        :class="entry.type === 'directory' ? 'text-amber-400' : 'text-slate-500'"
      />

      <!-- Name -->
      <span class="truncate text-[13px]">{{ entry.name }}</span>
    </button>

    <!-- 子節點 -->
    <div v-if="expanded && children.length > 0">
      <FileTreeNode
        v-for="child in children"
        :key="child.path"
        :entry="child"
        :depth="depth + 1"
        :selected-path="selectedPath"
        :project-id="projectId"
        @select="$emit('select', $event)"
      />
    </div>
    <div v-if="expanded && loadingChildren" :style="{ paddingLeft: `${(depth + 1) * 16 + 8}px` }" class="py-1 text-xs text-slate-600">
      ...
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ChevronRight, Folder, FolderOpen, File as FileIcon } from 'lucide-vue-next'
import { config } from '../../config'
import type { FileEntry } from './FileTree.vue'

const props = defineProps<{
  entry: FileEntry
  depth: number
  selectedPath: string
  projectId: number
}>()

const emit = defineEmits<{
  select: [entry: FileEntry]
}>()

const API = config.apiUrl
const expanded = ref(false)
const children = ref<FileEntry[]>([])
const loadingChildren = ref(false)
const loaded = ref(false)

async function handleClick() {
  if (props.entry.type === 'directory') {
    if (!loaded.value) {
      loadingChildren.value = true
      try {
        const res = await fetch(`${API}/api/v1/projects/${props.projectId}/files?path=${encodeURIComponent(props.entry.path)}`)
        if (res.ok) {
          const data = await res.json()
          children.value = data.entries
        }
      } finally {
        loadingChildren.value = false
        loaded.value = true
      }
    }
    expanded.value = !expanded.value
  } else {
    emit('select', props.entry)
  }
}
</script>
