<script setup lang="ts">
import ChannelDetailLayout from '../../../components/ChannelDetailLayout.vue'
import ChannelFormFields from '../../../components/ChannelFormFields.vue'
import { useChannelConfig, type ChannelField } from '../../../composables/useChannelConfig'

const { loading, saving, formData, visibleFields, saveConfig, toggleVisibility } = useChannelConfig('line')

const fields: ChannelField[] = [
  { key: 'channel_secret', label: 'Channel Secret', type: 'password', placeholder: '' },
  { key: 'access_token', label: 'Access Token', type: 'password', placeholder: '' },
  { key: 'mode', label: '模式', type: 'select', options: [
    { value: 'active', label: '互動模式（收發訊息）' },
    { value: 'passive', label: '收集模式（只收不回）' },
  ], hint: 'Passive 模式會將訊息存入 RawMessage 表，不觸發 AI 回應' },
]
</script>

<template>
  <ChannelDetailLayout
    icon="💬" label="LINE"
    :loading="loading" :saving="saving" :enabled="formData.enabled"
    @update:enabled="formData.enabled = $event" @save="saveConfig"
  >
    <ChannelFormFields :fields="fields" :form-data="formData" :visible-fields="visibleFields" @toggle-visibility="toggleVisibility" />

    <!-- LINE-specific: Webhook URL hint -->
    <template #extra>
      <div class="bg-slate-800/30 rounded-xl border border-slate-700/30 p-4 text-sm text-slate-400 space-y-1">
        <p class="font-medium text-slate-300">Webhook URL</p>
        <code class="block text-xs text-teal-400 bg-slate-900 px-3 py-2 rounded-lg select-all">
          https://aegis.greenshepherd.com.tw/api/v1/webhooks/line
        </code>
        <p class="text-xs text-slate-500">在 LINE Developers Console → Messaging API → Webhook settings 中設定</p>
      </div>
    </template>
  </ChannelDetailLayout>
</template>
