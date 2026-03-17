import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { config } from '../config'

export const useDomainStore = defineStore('domain', () => {
  const API = config.apiUrl

  interface RoomInfo {
    id: number
    name: string
    description: string
    project_ids: number[]
    member_ids: number[]
  }

  interface DomainInfo {
    id: number
    hostname: string
    name: string
    is_default: boolean
    require_login: boolean
    show_onboarding: boolean
  }

  const domain = ref<DomainInfo | null>(null)
  const rooms = ref<RoomInfo[]>([])
  const resolved = ref(false)

  const visibleProjectIds = computed(() => {
    if (!resolved.value || rooms.value.length === 0) return null // null = show all
    const ids = new Set<number>()
    rooms.value.forEach(r => r.project_ids.forEach(id => ids.add(id)))
    return ids
  })

  const visibleMemberIds = computed(() => {
    if (!resolved.value || rooms.value.length === 0) return null
    const ids = new Set<number>()
    rooms.value.forEach(r => r.member_ids.forEach(id => ids.add(id)))
    return ids
  })

  function isProjectVisible(id: number): boolean {
    return visibleProjectIds.value === null || visibleProjectIds.value.has(id)
  }

  function isMemberVisible(id: number): boolean {
    return visibleMemberIds.value === null || visibleMemberIds.value.has(id)
  }

  async function resolve() {
    try {
      const hostname = window.location.hostname
      const res = await fetch(`${API}/api/v1/domain/current?hostname=${encodeURIComponent(hostname)}`)
      if (res.ok) {
        const data = await res.json()
        domain.value = data.domain
        rooms.value = data.rooms || []
      }
    } catch (e) {
      console.warn('Domain resolution failed:', e)
    }
    resolved.value = true
  }

  const requireLogin = computed(() => domain.value?.require_login ?? false)
  const showOnboarding = computed(() => domain.value?.show_onboarding ?? true)

  return { domain, rooms, resolved, visibleProjectIds, visibleMemberIds, isProjectVisible, isMemberVisible, requireLogin, showOnboarding, resolve }
})
