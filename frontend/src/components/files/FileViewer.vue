<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="flex items-center gap-2 px-4 py-2 border-b border-slate-700/50 bg-slate-800/50">
      <FileIcon class="w-4 h-4 text-slate-500" />
      <span class="text-sm text-slate-300 font-mono">{{ path }}</span>
      <!-- Markdown preview toggle -->
      <button
        v-if="isMarkdown"
        @click="showPreview = !showPreview"
        class="ml-2 p-1 rounded hover:bg-slate-700/50 transition-colors"
        :class="showPreview ? 'text-emerald-400' : 'text-slate-500'"
        :title="showPreview ? '顯示原始碼' : '預覽 Markdown'"
      >
        <Eye v-if="showPreview" class="w-4 h-4" />
        <Code v-else class="w-4 h-4" />
      </button>
      <span v-if="fileData?.size" class="text-xs text-slate-600 ml-auto">
        {{ formatSize(fileData.size) }}
      </span>
    </div>

    <!-- Content -->
    <div v-if="loading" class="flex-1 flex items-center justify-center text-slate-600 text-sm">
      載入中...
    </div>

    <!-- Image preview -->
    <div v-else-if="isImage" class="flex-1 flex items-center justify-center p-6 overflow-auto bg-[#0c0e14]">
      <img :src="imageUrl" :alt="path" class="max-w-full max-h-full object-contain rounded-lg" />
    </div>

    <!-- Binary (non-image) -->
    <div v-else-if="fileData?.binary" class="flex-1 flex items-center justify-center text-slate-600 text-sm">
      二進位檔案，無法預覽
    </div>

    <div v-else-if="fileData?.content !== undefined" class="flex-1 overflow-auto custom-scrollbar">
      <div v-if="fileData.truncated" class="px-4 py-1.5 bg-amber-900/20 border-b border-amber-700/30 text-xs text-amber-400">
        檔案超過 1MB，僅顯示部分內容
      </div>

      <!-- Markdown preview -->
      <div v-if="isMarkdown && showPreview" class="p-6 prose prose-invert prose-sm max-w-none" v-html="renderedMarkdown"></div>

      <!-- Source code with syntax highlighting -->
      <div v-else class="flex text-[13px] font-mono leading-5">
        <!-- 行號 -->
        <div class="select-none text-right pr-3 pl-4 py-3 text-slate-600 border-r border-slate-700/50 bg-slate-850 shrink-0">
          <div v-for="n in lineCount" :key="n">{{ n }}</div>
        </div>
        <!-- 內容 -->
        <pre class="flex-1 py-3 px-4 overflow-x-auto m-0"><code class="hljs" v-html="highlightedCode"></code></pre>
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
import { File as FileIcon, Eye, Code } from 'lucide-vue-next'
import { marked } from 'marked'
import hljs from 'highlight.js/lib/common'
import { config } from '../../config'

const props = defineProps<{
  projectId: number
  path: string
}>()

const API = config.apiUrl

const IMAGE_EXTS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.bmp'])

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
const showPreview = ref(true)

const isMarkdown = computed(() => {
  return props.path?.toLowerCase().endsWith('.md')
})

const isImage = computed(() => {
  if (!props.path) return false
  const ext = '.' + props.path.split('.').pop()?.toLowerCase()
  return IMAGE_EXTS.has(ext)
})

const imageUrl = computed(() => {
  return `${API}/api/v1/projects/${props.projectId}/files/raw?path=${encodeURIComponent(props.path)}`
})

const renderedMarkdown = computed(() => {
  if (!fileData.value?.content) return ''
  return marked.parse(fileData.value.content) as string
})

const lineCount = computed(() => {
  if (!fileData.value?.content) return 0
  return fileData.value.content.split('\n').length
})

// highlight.js 不支援的語言做映射
const LANG_ALIAS: Record<string, string> = { vue: 'xml', svelte: 'xml', jsx: 'javascript' }

const highlightedCode = computed(() => {
  if (!fileData.value?.content) return ''
  let lang = fileData.value.language || 'text'
  lang = LANG_ALIAS[lang] || lang
  try {
    if (lang !== 'text' && hljs.getLanguage(lang)) {
      return hljs.highlight(fileData.value.content, { language: lang }).value
    }
  } catch { /* fallback */ }
  return hljs.highlightAuto(fileData.value.content).value
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
  // Image files don't need content API
  if (isImage.value) {
    fileData.value = null
    loading.value = false
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

<style scoped>
.prose {
  color: #cbd5e1;
}
.prose :deep(h1) { font-size: 1.5em; font-weight: 700; margin: 1em 0 0.5em; color: #e2e8f0; border-bottom: 1px solid #334155; padding-bottom: 0.3em; }
.prose :deep(h2) { font-size: 1.25em; font-weight: 600; margin: 1em 0 0.5em; color: #e2e8f0; border-bottom: 1px solid #1e293b; padding-bottom: 0.2em; }
.prose :deep(h3) { font-size: 1.1em; font-weight: 600; margin: 0.8em 0 0.4em; color: #e2e8f0; }
.prose :deep(p) { margin: 0.5em 0; line-height: 1.7; }
.prose :deep(ul), .prose :deep(ol) { margin: 0.5em 0; padding-left: 1.5em; }
.prose :deep(li) { margin: 0.25em 0; }
.prose :deep(code) { background: #1e293b; padding: 0.15em 0.4em; border-radius: 4px; font-size: 0.9em; color: #f472b6; }
.prose :deep(pre) { background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 1em; overflow-x: auto; margin: 0.75em 0; }
.prose :deep(pre code) { background: none; padding: 0; color: #e2e8f0; }
.prose :deep(blockquote) { border-left: 3px solid #475569; padding-left: 1em; color: #94a3b8; margin: 0.75em 0; }
.prose :deep(a) { color: #60a5fa; text-decoration: none; }
.prose :deep(a:hover) { text-decoration: underline; }
.prose :deep(table) { width: 100%; border-collapse: collapse; margin: 0.75em 0; }
.prose :deep(th), .prose :deep(td) { border: 1px solid #334155; padding: 0.5em 0.75em; text-align: left; }
.prose :deep(th) { background: #1e293b; font-weight: 600; }
.prose :deep(hr) { border: none; border-top: 1px solid #334155; margin: 1.5em 0; }
.prose :deep(img) { max-width: 100%; border-radius: 8px; }

/* highlight.js dark theme (GitHub Dark style) */
.hljs { color: #c9d1d9; background: transparent; }
.hljs :deep(.hljs-keyword) { color: #ff7b72; }
.hljs :deep(.hljs-built_in) { color: #ffa657; }
.hljs :deep(.hljs-type) { color: #ffa657; }
.hljs :deep(.hljs-literal) { color: #79c0ff; }
.hljs :deep(.hljs-number) { color: #79c0ff; }
.hljs :deep(.hljs-string) { color: #a5d6ff; }
.hljs :deep(.hljs-comment) { color: #8b949e; font-style: italic; }
.hljs :deep(.hljs-function) { color: #d2a8ff; }
.hljs :deep(.hljs-title) { color: #d2a8ff; }
.hljs :deep(.hljs-params) { color: #c9d1d9; }
.hljs :deep(.hljs-attr) { color: #79c0ff; }
.hljs :deep(.hljs-attribute) { color: #79c0ff; }
.hljs :deep(.hljs-selector-tag) { color: #7ee787; }
.hljs :deep(.hljs-selector-class) { color: #d2a8ff; }
.hljs :deep(.hljs-selector-id) { color: #ffa657; }
.hljs :deep(.hljs-variable) { color: #ffa657; }
.hljs :deep(.hljs-template-variable) { color: #ffa657; }
.hljs :deep(.hljs-tag) { color: #7ee787; }
.hljs :deep(.hljs-name) { color: #7ee787; }
.hljs :deep(.hljs-meta) { color: #79c0ff; }
.hljs :deep(.hljs-symbol) { color: #79c0ff; }
.hljs :deep(.hljs-regexp) { color: #a5d6ff; }
.hljs :deep(.hljs-deletion) { color: #ffa198; background: #490202; }
.hljs :deep(.hljs-addition) { color: #aff5b4; background: #04260f; }
.hljs :deep(.hljs-section) { color: #d2a8ff; font-weight: bold; }
.hljs :deep(.hljs-bullet) { color: #ffa657; }
.hljs :deep(.hljs-subst) { color: #c9d1d9; }
.hljs :deep(.hljs-property) { color: #79c0ff; }
.hljs :deep(.hljs-doctag) { color: #ff7b72; }
</style>
