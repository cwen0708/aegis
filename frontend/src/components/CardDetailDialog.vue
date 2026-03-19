<script setup lang="ts">
import { ref } from 'vue'
import { Zap, Square, Pencil, X } from 'lucide-vue-next'
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

const isEditing = ref(false)
const cardDetailTab = ref<'description' | 'prompt' | 'result'>('description')

// 備份原始值，取消時還原
let backupTitle = ''
let backupDescription = ''
let backupContent = ''

function startEdit() {
  backupTitle = props.card.title
  backupDescription = props.card.description || ''
  backupContent = props.card.content || ''
  isEditing.value = true
}

function cancelEdit() {
  props.card.title = backupTitle
  props.card.description = backupDescription
  props.card.content = backupContent
  isEditing.value = false
}

function handleSave() {
  emit('save', props.card)
  isEditing.value = false
}

const canEdit = () => props.card.status !== 'running' && props.card.status !== 'pending'
</script>

<template>
  <div class="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50">
    <div class="bg-slate-800 border border-slate-700 rounded-2xl w-full max-w-3xl mx-2 h-[80vh] flex flex-col shadow-2xl overflow-hidden">
      <!-- 第一行：標題 + 關閉 -->
      <div class="px-6 pt-5 pb-2 flex items-start justify-between gap-4">
        <div class="flex-1 min-w-0">
          <input v-if="isEditing" v-model="card.title" type="text" class="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-1.5 text-lg font-bold text-slate-100 focus:ring-2 focus:ring-emerald-500 outline-none">
          <h2 v-else class="text-lg font-bold text-slate-100 leading-snug truncate">{{ card.title }}</h2>
        </div>
        <button @click="emit('close')" class="text-slate-400 hover:text-slate-200 transition-colors p-1 rounded-lg hover:bg-slate-700 shrink-0">
          <X class="w-5 h-5" />
        </button>
      </div>

      <!-- 第二行：Tags + 按鈕 -->
      <div class="px-6 pb-3 flex items-center justify-between gap-2 border-b border-slate-700">
        <!-- 左：Tags -->
        <div class="flex items-center gap-2">
          <span class="bg-blue-500/10 border border-blue-500/20 text-blue-400 text-[10px] font-bold px-2 py-0.5 rounded-md uppercase tracking-wider">C-{{ card.id }}</span>
          <span class="text-[10px] font-bold px-2 py-0.5 rounded-md uppercase tracking-wider border"
            :class="{
              'bg-emerald-500/10 border-emerald-500/20 text-emerald-400': card.status === 'running',
              'bg-amber-500/10 border-amber-500/20 text-amber-400': card.status === 'pending',
              'bg-green-500/10 border-green-500/20 text-green-400': card.status === 'completed',
              'bg-red-500/10 border-red-500/20 text-red-400': card.status === 'failed',
              'bg-slate-700 border-slate-600 text-slate-300': !['running','pending','completed','failed'].includes(card.status),
            }"
          >{{ card.status }}</span>
        </div>

        <!-- 右：按鈕 -->
        <div class="flex items-center gap-2">
          <template v-if="isEditing">
            <button @click="cancelEdit" class="text-xs px-3 py-1.5 text-slate-400 hover:text-slate-200 transition-colors">取消</button>
            <button @click="handleSave" class="text-xs px-3 py-1.5 bg-emerald-500 hover:bg-emerald-600 text-white rounded-lg transition-colors font-medium">儲存</button>
          </template>
          <template v-else>
            <button
              v-if="canEdit()"
              @click="startEdit"
              class="text-xs px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-lg transition-colors"
            >
              <Pencil class="w-3 h-3 inline mr-1" />編輯
            </button>
            <button
              v-if="card.status !== 'running' && card.status !== 'pending'"
              @click="emit('trigger', card.id)"
              class="text-xs px-3 py-1.5 bg-emerald-500/10 text-emerald-400 rounded-lg border border-emerald-500/30 hover:bg-emerald-500/20 transition-colors"
            >
              <Zap class="w-3.5 h-3.5 inline mr-1" />觸發
            </button>
            <button
              v-if="card.status === 'running'"
              @click="emit('abort', card.id)"
              class="text-xs px-3 py-1.5 bg-red-500/10 text-red-400 rounded-lg border border-red-500/30 hover:bg-red-500/20 transition-colors"
            >
              <Square class="w-3.5 h-3.5 inline mr-1" />中止
            </button>
          </template>
        </div>
      </div>

      <!-- Tab 頁籤 -->
      <div class="flex border-b border-slate-700 bg-slate-800/50">
        <button
          @click="cardDetailTab = 'description'"
          class="flex-1 px-4 py-2 text-xs font-medium transition-colors relative"
          :class="cardDetailTab === 'description' ? 'text-emerald-400' : 'text-slate-400 hover:text-slate-200'"
        >
          描述
          <div v-if="cardDetailTab === 'description'" class="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-400" />
        </button>
        <button
          @click="cardDetailTab = 'prompt'"
          class="flex-1 px-4 py-2 text-xs font-medium transition-colors relative"
          :class="cardDetailTab === 'prompt' ? 'text-emerald-400' : 'text-slate-400 hover:text-slate-200'"
        >
          提示詞
          <div v-if="cardDetailTab === 'prompt'" class="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-400" />
        </button>
        <button
          @click="cardDetailTab = 'result'"
          class="flex-1 px-4 py-2 text-xs font-medium transition-colors relative"
          :class="cardDetailTab === 'result' ? 'text-emerald-400' : 'text-slate-400 hover:text-slate-200'"
        >
          結果
          <div v-if="cardDetailTab === 'result'" class="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-400" />
        </button>
      </div>

      <!-- Body -->
      <div class="flex-1 overflow-hidden">
        <!-- Tab 1: 任務描述 -->
        <div v-if="cardDetailTab === 'description'" class="h-full overflow-y-auto custom-scrollbar">
          <textarea v-if="isEditing" v-model="card.description" class="w-full h-full bg-transparent border-0 p-5 text-slate-200 text-sm font-mono focus:ring-0 outline-none resize-none" placeholder="輸入任務描述..."></textarea>
          <pre v-else class="p-5 whitespace-pre-wrap font-mono text-slate-300 text-xs">{{ card.description || '尚未提供任務描述。' }}</pre>
        </div>

        <!-- Tab 2: 提示詞 -->
        <div v-else-if="cardDetailTab === 'prompt'" class="h-full overflow-y-auto custom-scrollbar">
          <textarea v-if="isEditing" v-model="card.content" class="w-full h-full bg-transparent border-0 p-5 text-slate-200 text-sm font-mono focus:ring-0 outline-none resize-none" placeholder="輸入提示詞內容..."></textarea>
          <pre v-else class="p-5 whitespace-pre-wrap font-mono text-slate-300 text-xs">{{ card.content || '尚未提供提示詞內容。' }}</pre>
        </div>

        <!-- Tab 3: 執行結果 -->
        <div v-else class="h-full bg-slate-800/30 p-6 overflow-y-auto custom-scrollbar flex flex-col">
          <div v-if="isRunning" class="flex-1">
            <TerminalViewer :card-id="card.id" />
          </div>
          <div v-else-if="store.taskLogs.has(card.id)" class="flex-1">
            <TerminalViewer :card-id="card.id" />
          </div>
          <div v-else class="flex-1 flex flex-col items-center justify-center gap-4">
            <div class="text-xs text-slate-500 text-center">尚無執行記錄。</div>
            <button
              v-if="canEdit()"
              @click="emit('trigger', card.id)"
              class="text-xs px-3 py-1.5 bg-emerald-500/10 text-emerald-400 rounded-lg border border-emerald-500/30 hover:bg-emerald-500/20 transition-colors"
            >
              <Zap class="w-3.5 h-3.5 inline mr-1" />觸發執行
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
