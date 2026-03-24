import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { config } from '../config'

const API = config.apiUrl
const TOKEN_KEY = 'aegis-token'

interface UserInfo {
  id: number
  username: string
  display_name: string
  level: number
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))
  const requireLoginToView = ref(false)
  const policyLoaded = ref(false)

  // 用戶身份
  const userType = ref<'admin' | 'user' | null>(null) // admin=管理員密碼, user=BotUser帳號
  const userInfo = ref<UserInfo | null>(null)
  const userProjectIds = ref<number[] | null>(null) // null=不限（admin）

  const isAuthenticated = computed(() => !!token.value)
  const isAdmin = computed(() => userType.value === 'admin')

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

  // 取得當前用戶資訊（token 已存在時呼叫）
  async function fetchMe() {
    if (!token.value) return
    try {
      const res = await fetch(`${API}/api/v1/auth/me`, {
        headers: { Authorization: `Bearer ${token.value}` },
      })
      if (res.ok) {
        const data = await res.json()
        if (data.authenticated) {
          userType.value = data.type
          userInfo.value = data.user || null
          userProjectIds.value = data.project_ids || null
        } else {
          // token 無效，通知後登出
          const { useAegisStore } = await import('./aegis')
          useAegisStore().addToast('登入已過期，請重新登入', 'error')
          logout()
        }
      } else if (res.status === 401) {
        // 未授權，通知後登出
        const { useAegisStore } = await import('./aegis')
        useAegisStore().addToast('登入已過期，請重新登入', 'error')
        logout()
      }
      // 其他伺服器錯誤（5xx 等）不登出，可能是暫時性問題
    } catch (e) {
      // 網路錯誤不登出，避免離線時意外清除 session
      console.warn('[auth] fetchMe 網路錯誤，保留登入狀態', e)
    }
  }

  function login(newToken: string, type: 'admin' | 'user' = 'admin', user?: UserInfo, projectIds?: number[]) {
    token.value = newToken
    userType.value = type
    userInfo.value = user || null
    userProjectIds.value = projectIds || null
    localStorage.setItem(TOKEN_KEY, newToken)
    // 相容舊機制
    if (type === 'admin') {
      localStorage.setItem('aegis-admin-auth', 'true')
    }
  }

  function logout() {
    token.value = null
    userType.value = null
    userInfo.value = null
    userProjectIds.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem('aegis-admin-auth')
  }

  function getAuthHeaders(): Record<string, string> {
    if (token.value) {
      return { Authorization: `Bearer ${token.value}` }
    }
    return {}
  }

  // 管理員密碼登入
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
          login(data.token, 'admin')
        }
        return true
      }
      return false
    } catch {
      return false
    }
  }

  // 用戶帳密登入
  async function userLogin(username: string, password: string): Promise<string | null> {
    try {
      const res = await fetch(`${API}/api/v1/auth/user-login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      if (res.ok) {
        const data = await res.json()
        if (data.token) {
          login(data.token, 'user', data.user)
          // 取得授權專案
          await fetchMe()
          return null // 成功
        }
      }
      const err = await res.json().catch(() => ({ detail: '登入失敗' }))
      return err.detail || '登入失敗'
    } catch {
      return '網路錯誤'
    }
  }

  // 檢查用戶是否能看某個專案
  function canViewProject(projectId: number): boolean {
    if (!isAuthenticated.value) return true // 未登入走 domain 過濾
    if (isAdmin.value) return true
    if (userProjectIds.value === null) return true
    return userProjectIds.value.includes(projectId)
  }

  return {
    token,
    isAuthenticated,
    isAdmin,
    userType,
    userInfo,
    userProjectIds,
    requireLoginToView,
    policyLoaded,
    login,
    logout,
    getAuthHeaders,
    verifyPassword,
    userLogin,
    fetchAuthPolicy,
    fetchMe,
    canViewProject,
  }
})
