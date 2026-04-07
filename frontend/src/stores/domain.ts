import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { apiClient } from '../services/api/client'

export const useDomainStore = defineStore('domain', () => {
  interface DomainInfo {
    id: number
    hostname: string
    name: string
    is_default: boolean
    require_login: boolean
    show_onboarding: boolean
  }

  const domain = ref<DomainInfo | null>(null)
  const resolved = ref(false)

  async function resolve() {
    try {
      const hostname = window.location.hostname
      const data = await apiClient.get<{ domain: DomainInfo }>(
        `/api/v1/domain/current?hostname=${encodeURIComponent(hostname)}`,
      )
      domain.value = data.domain
    } catch (e) {
      console.warn('Domain resolution failed:', e)
    }
    resolved.value = true
  }

  const requireLogin = computed(() => domain.value?.require_login ?? false)
  const showOnboarding = computed(() => domain.value?.show_onboarding ?? true)

  return { domain, resolved, requireLogin, showOnboarding, resolve }
})
