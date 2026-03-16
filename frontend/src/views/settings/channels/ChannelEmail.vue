<script setup lang="ts">
import ChannelDetailLayout from '../../../components/ChannelDetailLayout.vue'
import ChannelFormFields from '../../../components/ChannelFormFields.vue'
import { useChannelConfig, type ChannelField } from '../../../composables/useChannelConfig'

const { loading, saving, formData, visibleFields, saveConfig, toggleVisibility } = useChannelConfig('email')

const imapFields: ChannelField[] = [
  { key: 'imap_host', label: 'IMAP Host', type: 'text', placeholder: 'imap.gmail.com' },
  { key: 'imap_port', label: 'IMAP Port', type: 'text', placeholder: '993' },
  { key: 'imap_user', label: 'IMAP 帳號', type: 'text', placeholder: 'user@example.com' },
  { key: 'imap_pass', label: 'IMAP 密碼', type: 'password', placeholder: '' },
]

const smtpFields: ChannelField[] = [
  { key: 'smtp_host', label: 'SMTP Host', type: 'text', placeholder: 'smtp.gmail.com' },
  { key: 'smtp_port', label: 'SMTP Port', type: 'text', placeholder: '587' },
  { key: 'smtp_user', label: 'SMTP 帳號', type: 'text', placeholder: '' },
  { key: 'smtp_pass', label: 'SMTP 密碼', type: 'password', placeholder: '' },
]

const optionFields: ChannelField[] = [
  { key: 'poll_interval', label: '輪詢間隔 (秒)', type: 'text', placeholder: '60' },
  { key: 'auto_reply_enabled', label: '啟用自動回覆', type: 'checkbox' },
  { key: 'ai_classify_enabled', label: '啟用 AI 分類摘要', type: 'checkbox' },
]
</script>

<template>
  <ChannelDetailLayout
    icon="📧" label="Email (IMAP/SMTP)"
    :loading="loading" :saving="saving" :enabled="formData.enabled"
    @update:enabled="formData.enabled = $event" @save="saveConfig"
  >
    <!-- IMAP Section -->
    <div class="space-y-1">
      <p class="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">收件 (IMAP)</p>
      <ChannelFormFields :fields="imapFields" :form-data="formData" :visible-fields="visibleFields" @toggle-visibility="toggleVisibility" />
    </div>

    <!-- Divider -->
    <div class="border-t border-slate-700/50" />

    <!-- SMTP Section -->
    <div class="space-y-1">
      <p class="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">寄件 (SMTP)</p>
      <ChannelFormFields :fields="smtpFields" :form-data="formData" :visible-fields="visibleFields" @toggle-visibility="toggleVisibility" />
    </div>

    <!-- Divider -->
    <div class="border-t border-slate-700/50" />

    <!-- Options -->
    <div class="space-y-1">
      <p class="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">選項</p>
      <ChannelFormFields :fields="optionFields" :form-data="formData" :visible-fields="visibleFields" @toggle-visibility="toggleVisibility" />
    </div>
  </ChannelDetailLayout>
</template>
