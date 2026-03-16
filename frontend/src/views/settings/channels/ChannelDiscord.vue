<script setup lang="ts">
import ChannelDetailLayout from '../../../components/ChannelDetailLayout.vue'
import ChannelFormFields from '../../../components/ChannelFormFields.vue'
import { useChannelConfig, type ChannelField } from '../../../composables/useChannelConfig'

const { loading, saving, formData, visibleFields, saveConfig, toggleVisibility } = useChannelConfig('discord')

const fields: ChannelField[] = [
  { key: 'bot_token', label: 'Bot Token', type: 'password', placeholder: '' },
]
</script>

<template>
  <ChannelDetailLayout
    icon="🎮" label="Discord"
    :loading="loading" :saving="saving" :enabled="formData.enabled"
    @update:enabled="formData.enabled = $event" @save="saveConfig"
  >
    <ChannelFormFields :fields="fields" :form-data="formData" :visible-fields="visibleFields" @toggle-visibility="toggleVisibility" />
  </ChannelDetailLayout>
</template>
