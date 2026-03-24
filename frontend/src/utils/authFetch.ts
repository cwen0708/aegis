/**
 * 帶 auth token 的 fetch wrapper，用於各頁面直接 fetch 的場景
 */
export function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const token = localStorage.getItem('aegis-token')
  const headers: Record<string, string> = { ...extra }
  if (token) headers['Authorization'] = `Bearer ${token}`
  return headers
}

export function handle401(res: Response) {
  if (res.status === 401) {
    localStorage.removeItem('aegis-token')
    localStorage.removeItem('aegis-admin-auth')
    window.location.href = '/login'
  }
}
