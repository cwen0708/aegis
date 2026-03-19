<script setup lang="ts">
import { ref } from 'vue'
import { Zap, Square } from 'lucide-vue-next'
import TerminalViewer from './TerminalViewer.vue'
import { useAegisStore } from '../stores/aegis'

const store = useAegisStore()

const props = defineProps<{
  card: any
  isRunning: boolean
}>()

const emit = defineEmits<{
  close: []
  save: [card: any]
  trigger: [cardId: number]
  abort: [cardId: number]
}>()

const isEditingContent = ref(false)
const cardDetailTab = ref<'description' | 'prompt' | 'result'>('description')

function handleSave() {
  emit('save', props.card)
  isEditingContent.value = false
}
</script>

<template>
  <div class="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50">
    <div class="bg-slate-800 border border-slate-700 rounded-2xl w-full max-w-3xl mx-2 h-[80vh] flex flex-col shadow-2xl overflow-hidden">
      <!-- Header -->
      <div class="p-6 border-b border-slate-700 bg-slate-800/80">
        <!-- 標題列 -->
        <div class="mb-3">
          <div class="flex items-center gap-3 mb-2">
            <span class="bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-bold px-2.5 py-0.5 rounded-md uppercase tracking-wider">Card-{{ card.id }}</span>
            <span class="bg-slate-700 text-slate-300 text-xs font-bold px-2.5 py-0.5 rounded-md uppercase tracking-wider">{{ card.status }}</span>
          </div>
          <input v-if="isEditingContent" v-model="card.title" type="text" class="w-full bg-slate-900 border border-slate-600 rounded-lg p-2 text-xl font-bold text-slate-100 focus:ring-2 focus:ring-emerald-500 outline-none">
          <h2 v-else class="text-xl font-bold text-slate-100 leading-snug">{{ card.title }}</h2>
        </div>
        <!-- 按鈕列 -->
        <div class="flex items-center gap-2 justify-end">
          <button
            v-if="card.status !== 'running'"
            @click="emit('trigger', card.id)"
            class="text-xs px-3 py-1.5 bg-emerald-500/10 text-emerald-400 rounded-lg border border-emerald-500/30 hover:bg-emerald-500/20 transition-colors"
          >
            <Zap class="w-3.5 h-3.5 inline mr-1" />觸發執行
          </button>
          <button
            v-else
            @click="emit('abort', card.id)"
            class="text-xs px-3 py-1.5 bg-red-500/10 text-red-400 rounded-lg border border-red-500/30 hover:bg-red-500/20 transition-colors"
          >
            <Square class="w-3.5 h-3.5 inline mr-1" />中止
          </button>
          <button @click="emit('close')" class="text-slate-400 hover:text-slate-200 transition-colors p-1 rounded-lg hover:bg-slate-700">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
        </div>
      </div>

      <!-- Tab 頁籤 -->
      <div class="flex border-b border-slate-700 bg-slate-800/50">
        <button
          @click="cardDetailTab = 'description'"
          class="flex-1 px-4 py-2.5 text-sm font-medium transition-colors relative"
          :class="cardDetailTab === 'description' ? 'text-emerald-400' : 'text-slate-400 hover:text-slate-200'"
        >
          任務描述
          <div v-if="cardDetailTab === 'description'" class="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-400" />
        </button>
        <button
          @click="cardDetailTab = 'prompt'"
          class="flex-1 px-4 py-2.5 text-sm font-medium transition-colors relative"
          :class="cardDetailTab === 'prompt' ? 'text-emerald-400' : 'text-slate-400 hover:text-slate-200'"
        >
          提示詞
          <div v-if="cardDetailTab === 'prompt'" class="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-400" />
        </button>
        <button
          @click="cardDetailTab = 'result'"
          class="flex-1 px-4 py-2.5 text-sm font-medium transition-colors relative"
          :class="cardDetailTab === 'result' ? 'text-emerald-400' : 'text-slate-400 hover:text-slate-200'"
        >
          執行記錄
          <div v-if="cardDetailTab === 'result'" class="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-400" />
        </button>
      </div>

      <!-- Body -->
      <div class="flex-1 overflow-hidden">
        <!-- Tab 1: 任務描述 -->
        <div v-if="cardDetailTab === 'description'" class="h-full p-6 overflow-y-auto custom-scrollbar flex flex-col">
          <h3 class="text-sm font-semibold text-slate-400 tracking-wider mb-4">任務描述</h3>
          <div class="flex-1 bg-slate-900/50 border border-slate-700/50 rounded-xl p-5 overflow-y-auto custom-scrollbar prose prose-invert prose-sm max-w-none">
            <pre class="whitespace-pre-wrap font-mono text-slate-300 text-xs">{{ card.description || '尚未提供任務描述。' }}</pre>
          </div>
        </div>

        <!-- Tab 2: 提示詞 -->
        <div v-else-if="cardDetailTab === 'prompt'" class="h-full p-6 overflow-y-auto custom-scrollbar flex flex-col">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-sm font-semibold text-slate-400 tracking-wider">AI 提示詞</h3>
            <button @click="isEditingContent = !isEditingContent" class="text-xs bg-slate-700 hover:bg-slate-600 text-slate-300 px-3 py-1.5 rounded-md transition-colors font-medium">
              {{ isEditingContent ? '取消編輯' : '編輯提示詞' }}
            </button>
          </div>

          <div v-if="isEditingContent" class="flex-1 flex flex-col gap-4">
            <div>
              <label class="block text-xs font-medium text-slate-400 mb-1">描述</label>
              <textarea v-model="card.description" rows="2" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-slate-200 text-sm font-mono focus:ring-2 focus:ring-emerald-500 outline-none custom-scrollbar"></textarea>
            </div>
            <div class="flex-1 flex flex-col">
              <label class="block text-xs font-medium text-slate-400 mb-1">Markdown 內容（上下文）</label>
              <textarea v-model="card.content" class="flex-1 w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-slate-200 text-sm font-mono focus:ring-2 focus:ring-emerald-500 outline-none custom-scrollbar resize-none"></textarea>
            </div>
          </div>
          <div v-else class="flex-1 bg-slate-900/50 border border-slate-700/50 rounded-xl p-5 overflow-y-auto custom-scrollbar prose prose-invert prose-sm max-w-none">
            <pre class="whitespace-pre-wrap font-mono text-slate-300 text-xs">{{ card.content || '尚未提供提示詞內容。' }}</pre>
          </div>
        </div>

        <!-- Tab 3: 執行記錄 -->
        <div v-else class="h-full bg-slate-800/30 p-6 overflow-y-auto custom-scrollbar flex flex-col">
          <h3 class="text-sm font-semibold text-slate-400 tracking-wider mb-4">執行記錄</h3>
          <div v-if="isRunning" class="flex-1">
            <TerminalViewer :card-id="card.id" />
          </div>
          <div v-else-if="store.taskLogs.has(card.id)" class="flex-1">
            <TerminalViewer :card-id="card.id" />
          </div>
          <div v-else class="flex-1 flex flex-col items-center justify-center gap-4">
            <div class="text-xs text-slate-500 text-center">尚無執行記錄。</div>
            <button
              v-if="card.status !== 'running' && card.status !== 'pending'"
              @click="emit('trigger', card.id)"
              class="text-xs px-3 py-1.5 bg-emerald-500/10 text-emerald-400 rounded-lg border border-emerald-500/30 hover:bg-emerald-500/20 transition-colors"
            >
              <Zap class="w-3.5 h-3.5 inline mr-1" />觸發執行
            </button>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div v-if="isEditingContent" class="p-4 border-t border-slate-700 bg-slate-800 flex justify-end gap-3">
        <button @click="isEditingContent = false" class="px-4 py-2 text-sm font-medium text-slate-400 hover:text-slate-200">取消</button>
        <button @click="handleSave" class="px-5 py-2 text-sm font-medium bg-emerald-500 hover:bg-emerald-600 text-white rounded-lg transition-colors shadow-lg shadow-emerald-500/20">
          儲存變更
        </button>
      </div>
    </div>
  </div>
</template>
