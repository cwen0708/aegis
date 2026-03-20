/**
 * 帶 auth token 的 fetch wrapper，用於各頁面直接 fetch 的場景
 */
export function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const token = sessionStorage.getItem('aegis-token')
  const headers: Record<string, string> = { ...extra }
  if (token) headers['Authorization'] = `Bearer ${token}`
  return headers
}

export function handle401(res: Response) {
  if (res.status === 401) {
    sessionStorage.removeItem('aegis-token')
    sessionStorage.removeItem('aegis-admin-auth')
    window.location.href = '/login'
  }
}
