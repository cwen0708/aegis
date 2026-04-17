import { ref, onMounted } from 'vue'
import { useAegisStore } from '../stores/aegis'
import { apiClient } from '../services/api/client'

export interface ChannelField {
  key: string
  label: string
  type: 'text' | 'password' | 'checkbox' | 'select'
  placeholder?: string
  hint?: string
  options?: { value: string; label: string }[]
}

export function useChannelConfig(channelName: string) {
  const store = useAegisStore()

  const loading = ref(true)
  const saving = ref(false)
  const formData = ref<Record<string, any>>({ enabled: false })
  const visibleFields = ref<Record<string, boolean>>({})

  async function fetchConfig() {
    loading.value = true
    try {
      const allConfigs = await apiClient.get<Record<string, any>>('/api/v1/channels')
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
      await apiClient.put(`/api/v1/channels/${channelName}`, formData.value)
      store.addToast('頻道設定已儲存', 'success')
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

  return { loading, saving, formData, visibleFields, fetchConfig, saveConfig, toggleVisibility }
}
