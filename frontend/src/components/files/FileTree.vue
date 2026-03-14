<template>
  <div class="text-sm select-none">
    <div v-if="loading && entries.length === 0" class="text-slate-500 text-xs px-2 py-4">
      載入中...
    </div>
    <template v-else>
      <FileTreeNode
        v-for="entry in entries"
        :key="entry.path"
        :entry="entry"
        :depth="0"
        :selected-path="selectedPath"
        :project-id="projectId"
        @select="$emit('select', $event)"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { config } from '../../config'
import { authHeaders } from '../../utils/authFetch'
import FileTreeNode from './FileTreeNode.vue'

export interface FileEntry {
  name: string
  path: string
  type: 'file' | 'directory'
  size: number | null
  modified: string | null
}

const props = defineProps<{
  projectId: number
  selectedPath: string
}>()

defineEmits<{
  select: [entry: FileEntry]
}>()

const API = config.apiUrl
const entries = ref<FileEntry[]>([])
const loading = ref(false)

async function loadDir(path: string = '') {
  loading.value = true
  try {
    const res = await fetch(`${API}/api/v1/projects/${props.projectId}/files?path=${encodeURIComponent(path)}`, { headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      entries.value = data.entries
    }
  } finally {
    loading.value = false
  }
}

watch(() => props.projectId, () => {
  entries.value = []
  loadDir()
})

onMounted(() => loadDir())
</script>
