import { ref, onMounted } from 'vue'
import { useAegisStore } from '../stores/aegis'
import { config as appConfig } from '../config'
import { authHeaders } from '../utils/authFetch'

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
  const API = appConfig.apiUrl

  const loading = ref(true)
  const saving = ref(false)
  const formData = ref<Record<string, any>>({ enabled: false })
  const visibleFields = ref<Record<string, boolean>>({})

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

  return { loading, saving, formData, visibleFields, fetchConfig, saveConfig, toggleVisibility }
}
