<script setup lang="ts">
import ChannelDetailLayout from '../../../components/ChannelDetailLayout.vue'
import ChannelFormFields from '../../../components/ChannelFormFields.vue'
import { useChannelConfig, type ChannelField } from '../../../composables/useChannelConfig'

const { loading, saving, formData, visibleFields, saveConfig, toggleVisibility } = useChannelConfig('feishu')

const fields: ChannelField[] = [
  { key: 'app_id', label: 'App ID', type: 'text', placeholder: '' },
  { key: 'app_secret', label: 'App Secret', type: 'password', placeholder: '' },
  { key: 'is_lark', label: '使用 Lark 國際版', type: 'checkbox' },
]
</script>

<template>
  <ChannelDetailLayout
    icon="🐦" label="飛書 / Lark"
    :loading="loading" :saving="saving" :enabled="formData.enabled"
    @update:enabled="formData.enabled = $event" @save="saveConfig"
  >
    <ChannelFormFields :fields="fields" :form-data="formData" :visible-fields="visibleFields" @toggle-visibility="toggleVisibility" />
  </ChannelDetailLayout>
</template>
