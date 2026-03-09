<script setup lang="ts">
import { ref, computed } from 'vue'
import { Loader2, Check, ChevronDown, ChevronUp } from 'lucide-vue-next'

interface ChannelConfig {
  enabled: boolean
  [key: string]: any
}

interface FieldDef {
  key: string
  label: string
  type: 'text' | 'password' | 'checkbox'
  placeholder?: string
  hint?: string
}

const props = defineProps<{
  name: string
  label: string
  icon: string
  iconColor: string
  config: ChannelConfig
  fields: FieldDef[]
  status?: { connected: boolean; error?: string } | null
  saving?: boolean
}>()

const emit = defineEmits<{
  (e: 'update', config: ChannelConfig): void
}>()

const expanded = ref(false)
const localConfig = ref<ChannelConfig>({ ...props.config })

// 當 props.config 變化時，同步到 localConfig
// watchEffect(() => {
//   localConfig.value = { ...props.config }
// })

const statusColor = computed(() => {
  if (!props.config.enabled) return 'bg-slate-500'
  if (props.status?.connected) return 'bg-emerald-400'
  if (props.status?.error) return 'bg-red-400'
  return 'bg-amber-400'
})

const statusText = computed(() => {
  if (!props.config.enabled) return '停用'
  if (props.status?.connected) return '已連線'
  if (props.status?.error) return props.status.error
  return '等待連線'
})

function toggleEnabled() {
  localConfig.value.enabled = !localConfig.value.enabled
  emit('update', { ...localConfig.value })
}

function updateField(key: string, value: any) {
  localConfig.value[key] = value
}

function saveConfig() {
  emit('update', { ...localConfig.value })
}

</script>

<template>
  <div class="bg-slate-900 rounded-xl border border-slate-700/50 overflow-hidden">
    <!-- 頂部：圖標 + 名稱 + 狀態 + 開關 -->
    <div
      class="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-slate-800/50 transition-colors"
      @click="expanded = !expanded"
    >
      <div class="flex items-center gap-3">
        <!-- 狀態燈 -->
        <div :class="['w-2 h-2 rounded-full', statusColor]"></div>
        <!-- 圖標 -->
        <div :class="['w-8 h-8 rounded-lg flex items-center justify-center', iconColor]">
          <span class="text-lg">{{ icon }}</span>
        </div>
        <!-- 名稱與狀態 -->
        <div>
          <div class="text-sm font-medium text-slate-200">{{ label }}</div>
          <div class="text-xs text-slate-500">{{ statusText }}</div>
        </div>
      </div>
      <div class="flex items-center gap-3">
        <!-- 啟用/停用開關 -->
        <button
          @click.stop="toggleEnabled"
          :class="[
            'relative w-10 h-5 rounded-full transition-colors',
            config.enabled ? 'bg-emerald-500' : 'bg-slate-600'
          ]"
        >
          <div
            :class="[
              'absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow',
              config.enabled ? 'left-5' : 'left-0.5'
            ]"
          ></div>
        </button>
        <!-- 展開/收合 -->
        <ChevronDown v-if="!expanded" class="w-4 h-4 text-slate-500" />
        <ChevronUp v-else class="w-4 h-4 text-slate-500" />
      </div>
    </div>

    <!-- 展開內容：設定欄位 -->
    <div v-if="expanded" class="px-4 pb-4 pt-2 border-t border-slate-700/50 space-y-3">
      <div v-for="field in fields" :key="field.key">
        <template v-if="field.type === 'checkbox'">
          <label class="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              :checked="localConfig[field.key]"
              @change="updateField(field.key, ($event.target as HTMLInputElement).checked)"
              class="w-4 h-4 rounded border-slate-600 bg-slate-800 text-emerald-500 focus:ring-emerald-500"
            />
            <span class="text-xs text-slate-300">{{ field.label }}</span>
          </label>
        </template>
        <template v-else>
          <label class="block text-xs font-medium text-slate-400 mb-1">{{ field.label }}</label>
          <input
            :type="field.type"
            :value="localConfig[field.key]"
            @input="updateField(field.key, ($event.target as HTMLInputElement).value)"
            :placeholder="field.placeholder"
            class="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:ring-2 focus:ring-emerald-500 outline-none font-mono"
          />
          <p v-if="field.hint" class="text-[10px] text-slate-500 mt-0.5">{{ field.hint }}</p>
        </template>
      </div>

      <!-- 儲存按鈕 -->
      <div class="flex justify-end pt-2">
        <button
          @click="saveConfig"
          :disabled="saving"
          class="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-lg text-xs font-medium transition-all"
        >
          <Loader2 v-if="saving" class="w-3 h-3 animate-spin" />
          <Check v-else class="w-3 h-3" />
          儲存
        </button>
      </div>
    </div>
  </div>
</template>
