import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { config } from '../config'

const API = config.apiUrl
const TOKEN_KEY = 'aegis-token'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(sessionStorage.getItem(TOKEN_KEY))
  const requireLoginToView = ref(false)
  const policyLoaded = ref(false)

  const isAuthenticated = computed(() => !!token.value)

  async function fetchAuthPolicy() {
    try {
      const res = await fetch(`${API}/api/v1/settings`)
      if (res.ok) {
        const data = await res.json()
        requireLoginToView.value = data.require_login_to_view === 'true'
      }
    } catch { /* ignore */ }
    policyLoaded.value = true
  }

  function login(newToken: string) {
    token.value = newToken
    sessionStorage.setItem(TOKEN_KEY, newToken)
    // 相容舊機制
    sessionStorage.setItem('aegis-admin-auth', 'true')
  }

  function logout() {
    token.value = null
    sessionStorage.removeItem(TOKEN_KEY)
    sessionStorage.removeItem('aegis-admin-auth')
  }

  function getAuthHeaders(): Record<string, string> {
    if (token.value) {
      return { Authorization: `Bearer ${token.value}` }
    }
    return {}
  }

  async function verifyPassword(password: string): Promise<boolean> {
    try {
      const res = await fetch(`${API}/api/v1/auth/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      })
      if (res.ok) {
        const data = await res.json()
        if (data.token) {
          login(data.token)
        }
        return true
      }
      return false
    } catch {
      return false
    }
  }

  return {
    token,
    isAuthenticated,
    requireLoginToView,
    policyLoaded,
    login,
    logout,
    getAuthHeaders,
    verifyPassword,
    fetchAuthPolicy,
  }
})
