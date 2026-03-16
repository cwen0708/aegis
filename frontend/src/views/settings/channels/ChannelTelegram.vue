<script setup lang="ts">
import ChannelDetailLayout from '../../../components/ChannelDetailLayout.vue'
import ChannelFormFields from '../../../components/ChannelFormFields.vue'
import { useChannelConfig, type ChannelField } from '../../../composables/useChannelConfig'

const { loading, saving, formData, visibleFields, saveConfig, toggleVisibility } = useChannelConfig('telegram')

const fields: ChannelField[] = [
  { key: 'bot_token', label: 'Bot Token', type: 'password', placeholder: '123456:ABC-DEF...', hint: '從 @BotFather 取得' },
]
</script>

<template>
  <ChannelDetailLayout
    icon="✈️" label="Telegram"
    :loading="loading" :saving="saving" :enabled="formData.enabled"
    @update:enabled="formData.enabled = $event" @save="saveConfig"
  >
    <ChannelFormFields :fields="fields" :form-data="formData" :visible-fields="visibleFields" @toggle-visibility="toggleVisibility" />
  </ChannelDetailLayout>
</template>
