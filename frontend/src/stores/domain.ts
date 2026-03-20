import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { config } from '../config'

export const useDomainStore = defineStore('domain', () => {
  const API = config.apiUrl

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
      const res = await fetch(`${API}/api/v1/domain/current?hostname=${encodeURIComponent(hostname)}`)
      if (res.ok) {
        const data = await res.json()
        domain.value = data.domain
      }
    } catch (e) {
      console.warn('Domain resolution failed:', e)
    }
    resolved.value = true
  }

  const requireLogin = computed(() => domain.value?.require_login ?? false)
  const showOnboarding = computed(() => domain.value?.show_onboarding ?? true)

  return { domain, resolved, requireLogin, showOnboarding, resolve }
})
