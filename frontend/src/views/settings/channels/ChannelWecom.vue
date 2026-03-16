<script setup lang="ts">
import ChannelDetailLayout from '../../../components/ChannelDetailLayout.vue'
import ChannelFormFields from '../../../components/ChannelFormFields.vue'
import { useChannelConfig, type ChannelField } from '../../../composables/useChannelConfig'

const { loading, saving, formData, visibleFields, saveConfig, toggleVisibility } = useChannelConfig('wecom')

const fields: ChannelField[] = [
  { key: 'corp_id', label: '企業 ID', type: 'text', placeholder: '' },
  { key: 'corp_secret', label: '應用 Secret', type: 'password', placeholder: '' },
  { key: 'agent_id', label: 'Agent ID', type: 'text', placeholder: '1000001' },
]
</script>

<template>
  <ChannelDetailLayout
    icon="🏢" label="企業微信"
    :loading="loading" :saving="saving" :enabled="formData.enabled"
    @update:enabled="formData.enabled = $event" @save="saveConfig"
  >
    <ChannelFormFields :fields="fields" :form-data="formData" :visible-fields="visibleFields" @toggle-visibility="toggleVisibility" />
  </ChannelDetailLayout>
</template>
