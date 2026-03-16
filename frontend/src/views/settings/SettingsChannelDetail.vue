<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Save, Loader2, Eye, EyeOff } from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'
import { config as appConfig } from '../../config'
import { authHeaders } from '../../utils/authFetch'

const route = useRoute()
const router = useRouter()
const store = useAegisStore()
const API = appConfig.apiUrl

const channelName = route.params.name as string
const loading = ref(true)
const saving = ref(false)
const formData = ref<Record<string, any>>({ enabled: false })

// Password visibility toggles
const visibleFields = ref<Record<string, boolean>>({})

// 頻道定義
const channelDefsMap: Record<string, { label: string; icon: string; fields: any[] }> = {
  telegram: {
    label: 'Telegram',
    icon: '✈️',
    fields: [
      { key: 'bot_token', label: 'Bot Token', type: 'password', placeholder: '123456:ABC-DEF...', hint: '從 @BotFather 取得' },
    ],
  },
  line: {
    label: 'LINE',
    icon: '💬',
    fields: [
      { key: 'channel_secret', label: 'Channel Secret', type: 'password', placeholder: '' },
      { key: 'access_token', label: 'Access Token', type: 'password', placeholder: '' },
      { key: 'mode', label: '模式', type: 'select', options: [
        { value: 'active', label: '互動模式（收發訊息）' },
        { value: 'passive', label: '收集模式（只收不回）' },
      ], hint: 'Passive 模式會將訊息存入 RawMessage 表，不觸發 AI 回應' },
    ],
  },
  discord: {
    label: 'Discord',
    icon: '🎮',
    fields: [
      { key: 'bot_token', label: 'Bot Token', type: 'password', placeholder: '' },
    ],
  },
  slack: {
    label: 'Slack',
    icon: '💼',
    fields: [
      { key: 'bot_token', label: 'Bot Token (xoxb-)', type: 'password', placeholder: 'xoxb-...' },
      { key: 'app_token', label: 'App Token (xapp-)', type: 'password', placeholder: 'xapp-...' },
    ],
  },
  wecom: {
    label: '企業微信',
    icon: '🏢',
    fields: [
      { key: 'corp_id', label: '企業 ID', type: 'text', placeholder: '' },
      { key: 'corp_secret', label: '應用 Secret', type: 'password', placeholder: '' },
      { key: 'agent_id', label: 'Agent ID', type: 'text', placeholder: '1000001' },
    ],
  },
  feishu: {
    label: '飛書 / Lark',
    icon: '🐦',
    fields: [
      { key: 'app_id', label: 'App ID', type: 'text', placeholder: '' },
      { key: 'app_secret', label: 'App Secret', type: 'password', placeholder: '' },
      { key: 'is_lark', label: '使用 Lark 國際版', type: 'checkbox' },
    ],
  },
  email: {
    label: 'Email (IMAP/SMTP)',
    icon: '📧',
    fields: [
      { key: 'imap_host', label: 'IMAP Host', type: 'text', placeholder: 'imap.gmail.com' },
      { key: 'imap_port', label: 'IMAP Port', type: 'text', placeholder: '993' },
      { key: 'imap_user', label: 'IMAP 帳號', type: 'text', placeholder: 'user@example.com' },
      { key: 'imap_pass', label: 'IMAP 密碼', type: 'password', placeholder: '' },
      { key: 'smtp_host', label: 'SMTP Host', type: 'text', placeholder: 'smtp.gmail.com' },
      { key: 'smtp_port', label: 'SMTP Port', type: 'text', placeholder: '587' },
      { key: 'smtp_user', label: 'SMTP 帳號', type: 'text', placeholder: '' },
      { key: 'smtp_pass', label: 'SMTP 密碼', type: 'password', placeholder: '' },
      { key: 'poll_interval', label: '輪詢間隔 (秒)', type: 'text', placeholder: '60' },
      { key: 'auto_reply_enabled', label: '啟用自動回覆', type: 'checkbox' },
      { key: 'ai_classify_enabled', label: '啟用 AI 分類摘要', type: 'checkbox' },
    ],
  },
}

const channelDef = computed(() => channelDefsMap[channelName])

async function fetchConfig() {
  loading.value = true
  try {
    const res = await fetch(`${API}/api/v1/channels`)
    const allConfigs = await res.json()
    formData.value = allConfigs[channelName] || { enabled: false }
  } catch {
    formData.value = { enabled: false }
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  saving.value = true
  try {
    const res = await fetch(`${API}/api/v1/channels/${channelName}`, {
      method: 'PUT',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(formData.value),
    })
    if (res.ok) {
      store.addToast('頻道設定已儲存', 'success')
    } else {
      store.addToast('儲存失敗', 'error')
    }
  } catch {
    store.addToast('儲存失敗', 'error')
  } finally {
    saving.value = false
  }
}

function toggleVisibility(key: string) {
  visibleFields.value[key] = !visibleFields.value[key]
}

onMounted(fetchConfig)
</script>

<template>
  <div class="space-y-6">
    <!-- Back + Title -->
    <div class="flex items-center gap-3">
      <button
        @click="router.push('/settings/channels')"
        class="p-2 rounded-lg hover:bg-slate-800 transition-colors"
      >
        <ArrowLeft class="w-4 h-4 text-slate-400" />
      </button>
      <div v-if="channelDef" class="flex items-center gap-2">
        <span class="text-lg">{{ channelDef.icon }}</span>
        <h2 class="text-lg font-bold text-slate-200">{{ channelDef.label }}</h2>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex justify-center py-12">
      <Loader2 class="w-8 h-8 animate-spin text-slate-400" />
    </div>

    <!-- Form -->
    <template v-else-if="channelDef">
      <div class="bg-slate-900/50 rounded-xl border border-slate-700/50 p-6 space-y-5">
        <!-- Enable toggle -->
        <div class="flex items-center justify-between pb-4 border-b border-slate-700/50">
          <div>
            <span class="text-sm font-medium text-slate-200">啟用頻道</span>
            <p class="text-xs text-slate-500 mt-0.5">啟用後系統會嘗試連線此頻道</p>
          </div>
          <button
            @click="formData.enabled = !formData.enabled"
            :class="[
              'relative inline-flex h-6 w-11 items-center rounded-full transition-colors',
              formData.enabled ? 'bg-emerald-600' : 'bg-slate-600'
            ]"
          >
            <span
              :class="[
                'inline-block h-4 w-4 transform rounded-full bg-white transition-transform',
                formData.enabled ? 'translate-x-6' : 'translate-x-1'
              ]"
            />
          </button>
        </div>

        <!-- Fields -->
        <div v-for="field in channelDef.fields" :key="field.key" class="space-y-1">
          <!-- Text / Password -->
          <template v-if="field.type === 'text' || field.type === 'password'">
            <label class="block text-sm text-slate-400">{{ field.label }}</label>
            <div class="relative">
              <input
                v-model="formData[field.key]"
                :type="field.type === 'password' && !visibleFields[field.key] ? 'password' : 'text'"
                :placeholder="field.placeholder"
                class="w-full px-3 py-2 bg-slate-800 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-600 pr-10"
              />
              <button
                v-if="field.type === 'password'"
                @click="toggleVisibility(field.key)"
                class="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
              >
                <EyeOff v-if="visibleFields[field.key]" class="w-4 h-4" />
                <Eye v-else class="w-4 h-4" />
              </button>
            </div>
            <p v-if="field.hint" class="text-[11px] text-slate-600">{{ field.hint }}</p>
          </template>

          <!-- Checkbox -->
          <template v-else-if="field.type === 'checkbox'">
            <label class="flex items-center gap-3 cursor-pointer py-1">
              <button
                @click="formData[field.key] = !formData[field.key]"
                :class="[
                  'relative inline-flex h-5 w-9 items-center rounded-full transition-colors',
                  formData[field.key] ? 'bg-emerald-600' : 'bg-slate-600'
                ]"
              >
                <span
                  :class="[
                    'inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform',
                    formData[field.key] ? 'translate-x-4' : 'translate-x-0.5'
                  ]"
                />
              </button>
              <span class="text-sm text-slate-300">{{ field.label }}</span>
            </label>
          </template>

          <!-- Select -->
          <template v-else-if="field.type === 'select'">
            <label class="block text-sm text-slate-400">{{ field.label }}</label>
            <select
              v-model="formData[field.key]"
              class="w-full px-3 py-2 bg-slate-800 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500"
            >
              <option v-for="opt in field.options" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
            <p v-if="field.hint" class="text-[11px] text-slate-600">{{ field.hint }}</p>
          </template>
        </div>
      </div>

      <!-- Save Button -->
      <div class="flex justify-end">
        <button
          @click="saveConfig"
          :disabled="saving"
          class="flex items-center gap-2 px-5 py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-all"
        >
          <Loader2 v-if="saving" class="w-4 h-4 animate-spin" />
          <Save v-else class="w-4 h-4" />
          儲存設定
        </button>
      </div>
    </template>

    <!-- Unknown channel -->
    <div v-else class="text-center py-12 text-slate-500">
      未知的頻道：{{ channelName }}
    </div>
  </div>
</template>
