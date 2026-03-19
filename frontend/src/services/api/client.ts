import { config } from '../../config'

const BASE = config.apiUrl

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const token = sessionStorage.getItem('aegis-token')
  const headers: Record<string, string> = { ...extra }
  if (token) headers['Authorization'] = `Bearer ${token}`
  return headers
}

function handle401(res: Response) {
  if (res.status === 401) {
    sessionStorage.removeItem('aegis-token')
    sessionStorage.removeItem('aegis-admin-auth')
    window.location.href = '/settings'
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    handle401(res)
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}

export const apiClient = {
  async get<T = any>(path: string): Promise<T> {
    const res = await fetch(`${BASE}${path}`, {
      headers: authHeaders(),
    })
    return handleResponse<T>(res)
  },

  async post<T = any>(path: string, body?: any): Promise<T> {
    const res = await fetch(`${BASE}${path}`, {
      method: 'POST',
      headers: authHeaders(body ? { 'Content-Type': 'application/json' } : {}),
      body: body ? JSON.stringify(body) : undefined,
    })
    return handleResponse<T>(res)
  },

  async put<T = any>(path: string, body?: any): Promise<T> {
    const res = await fetch(`${BASE}${path}`, {
      method: 'PUT',
      headers: authHeaders(body ? { 'Content-Type': 'application/json' } : {}),
      body: body ? JSON.stringify(body) : undefined,
    })
    return handleResponse<T>(res)
  },

  /** PUT with raw string body (e.g. pre-serialized JSON) */
  async putRaw<T = any>(path: string, rawBody: string): Promise<T> {
    const res = await fetch(`${BASE}${path}`, {
      method: 'PUT',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: rawBody,
    })
    return handleResponse<T>(res)
  },

  async patch<T = any>(path: string, body?: any): Promise<T> {
    const res = await fetch(`${BASE}${path}`, {
      method: 'PATCH',
      headers: authHeaders(body ? { 'Content-Type': 'application/json' } : {}),
      body: body ? JSON.stringify(body) : undefined,
    })
    return handleResponse<T>(res)
  },

  async delete<T = any>(path: string): Promise<T> {
    const res = await fetch(`${BASE}${path}`, {
      method: 'DELETE',
      headers: authHeaders(),
    })
    return handleResponse<T>(res)
  },

  /** POST with FormData (for file uploads) */
  async upload<T = any>(path: string, formData: FormData): Promise<T> {
    const res = await fetch(`${BASE}${path}`, {
      method: 'POST',
      headers: authHeaders(),
      body: formData,
    })
    if (res.status === 413) throw new Error('檔案過大，請壓縮後再試（上限 10MB）')
    return handleResponse<T>(res)
  },
}
