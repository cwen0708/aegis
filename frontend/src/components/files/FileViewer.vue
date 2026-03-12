<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="flex items-center gap-2 px-4 py-2 border-b border-slate-700/50 bg-slate-800/50">
      <FileIcon class="w-4 h-4 text-slate-500" />
      <span class="text-sm text-slate-300 font-mono">{{ path }}</span>
      <span v-if="fileData?.size" class="text-xs text-slate-600 ml-auto">
        {{ formatSize(fileData.size) }}
      </span>
    </div>

    <!-- Content -->
    <div v-if="loading" class="flex-1 flex items-center justify-center text-slate-600 text-sm">
      載入中...
    </div>

    <div v-else-if="fileData?.binary" class="flex-1 flex items-center justify-center text-slate-600 text-sm">
      二進位檔案，無法預覽
    </div>

    <div v-else-if="fileData?.content !== undefined" class="flex-1 overflow-auto custom-scrollbar">
      <div v-if="fileData.truncated" class="px-4 py-1.5 bg-amber-900/20 border-b border-amber-700/30 text-xs text-amber-400">
        檔案超過 1MB，僅顯示部分內容
      </div>
      <div class="flex text-[13px] font-mono leading-5">
        <!-- 行號 -->
        <div class="select-none text-right pr-3 pl-4 py-3 text-slate-600 border-r border-slate-700/50 bg-slate-850 shrink-0">
          <div v-for="n in lineCount" :key="n">{{ n }}</div>
        </div>
        <!-- 內容 -->
        <pre class="flex-1 py-3 px-4 text-slate-300 overflow-x-auto"><code>{{ fileData.content }}</code></pre>
      </div>
    </div>

    <!-- Empty state -->
    <div v-else class="flex-1 flex items-center justify-center text-slate-600 text-sm">
      選擇檔案以查看內容
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { File as FileIcon } from 'lucide-vue-next'
import { config } from '../../config'

const props = defineProps<{
  projectId: number
  path: string
}>()

const API = config.apiUrl

interface FileData {
  path: string
  content: string | null
  size: number
  binary: boolean
  truncated: boolean
  language?: string
}

const fileData = ref<FileData | null>(null)
const loading = ref(false)

const lineCount = computed(() => {
  if (!fileData.value?.content) return 0
  return fileData.value.content.split('\n').length
})

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

async function loadFile() {
  if (!props.path) {
    fileData.value = null
    return
  }
  loading.value = true
  try {
    const res = await fetch(`${API}/api/v1/projects/${props.projectId}/files/content?path=${encodeURIComponent(props.path)}`)
    if (res.ok) {
      fileData.value = await res.json()
    }
  } finally {
    loading.value = false
  }
}

watch(() => props.path, loadFile)
watch(() => props.projectId, () => { fileData.value = null })
</script>
