import { defineStore } from 'pinia'
import { ref } from 'vue'
import { config } from '../config'

const API = config.apiUrl

export interface RunningTask {
  task_id: number
  project: string
  card_title: string
  started_at: number
  pid: number | null
  provider: string
  member_id: number | null
}

export interface SystemInfo {
  cpu_percent: number
  mem_percent: number
  mem_available_gb: number
  is_paused: boolean
  workstations_used: number
  workstations_total: number
}

export interface Toast {
  id: number
  message: string
  type: 'success' | 'error' | 'info'
}

export const useAegisStore = defineStore('aegis', () => {
  // 系統設定
  const settings = ref<Record<string, string>>({})

  // WebSocket 狀態
  const connected = ref(false)
  const runningTasks = ref<RunningTask[]>([])
  const systemInfo = ref<SystemInfo>({
    cpu_percent: 0,
    mem_percent: 0,
    mem_available_gb: 0,
    is_paused: false,
    workstations_used: 0,
    workstations_total: 3,
  })

  // Log streaming 緩衝
  const taskLogs = ref<Map<number, string[]>>(new Map())

  // Toast 通知
  const toasts = ref<Toast[]>([])
  let toastId = 0

  function addToast(message: string, type: Toast['type'] = 'info') {
    const id = ++toastId
    toasts.value.push({ id, message, type })
    setTimeout(() => removeToast(id), 5000)
  }

  function removeToast(id: number) {
    toasts.value = toasts.value.filter(t => t.id !== id)
  }

  function setConnected(val: boolean) {
    connected.value = val
  }

  function updateRunningTasks(tasks: RunningTask[]) {
    runningTasks.value = tasks
  }

  function updateSystemInfo(info: SystemInfo) {
    systemInfo.value = info
  }

  function appendTaskLog(cardId: number, line: string) {
    if (!taskLogs.value.has(cardId)) {
      taskLogs.value.set(cardId, [])
    }
    const logs = taskLogs.value.get(cardId)!
    logs.push(line)
    // 最多保留 2000 行
    if (logs.length > 2000) {
      logs.splice(0, logs.length - 2000)
    }
  }

  function clearTaskLog(cardId: number) {
    taskLogs.value.delete(cardId)
  }

  // Auth helpers
  function _authHeaders(extra?: Record<string, string>): Record<string, string> {
    const token = localStorage.getItem('aegis-token')
    const headers: Record<string, string> = { ...extra }
    if (token) headers['Authorization'] = `Bearer ${token}`
    return headers
  }

  function _handle401(res: Response) {
    if (res.status === 401) {
      localStorage.removeItem('aegis-token')
      localStorage.removeItem('aegis-admin-auth')
      window.location.href = '/settings'
    }
  }

  // API helpers
  async function apiPost(path: string, body?: any) {
    const res = await fetch(`${API}${path}`, {
      method: 'POST',
      headers: _authHeaders(body ? { 'Content-Type': 'application/json' } : {}),
      body: body ? JSON.stringify(body) : undefined,
    })
    if (!res.ok) {
      _handle401(res)
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || res.statusText)
    }
    return res.json()
  }

  async function apiDelete(path: string) {
    const res = await fetch(`${API}${path}`, {
      method: 'DELETE',
      headers: _authHeaders(),
    })
    if (!res.ok) {
      _handle401(res)
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || res.statusText)
    }
    return res.json()
  }

  async function pauseRunner() {
    await apiPost('/api/v1/runner/pause')
    systemInfo.value.is_paused = true
    addToast('Runner 已暫停', 'info')
  }

  async function resumeRunner() {
    await apiPost('/api/v1/runner/resume')
    systemInfo.value.is_paused = false
    addToast('Runner 已恢復', 'success')
  }

  async function triggerCard(cardId: number) {
    await apiPost(`/api/v1/cards/${cardId}/trigger`)
    addToast('任務已觸發', 'success')
  }

  async function abortCard(cardId: number) {
    await apiPost(`/api/v1/cards/${cardId}/abort`)
    addToast('任務已中止', 'info')
  }

  async function deleteCard(cardId: number) {
    await apiDelete(`/api/v1/cards/${cardId}`)
    addToast('卡片已刪除', 'success')
  }

  async function deleteCronJob(jobId: number) {
    await apiDelete(`/api/v1/cron-jobs/${jobId}`)
    addToast('排程已刪除', 'success')
  }

  async function pauseCron(projectId: number) {
    await apiPost('/api/v1/cron/pause', { project_id: projectId })
    addToast('此專案排程已暫停', 'info')
  }

  async function resumeCron(projectId: number) {
    await apiPost('/api/v1/cron/resume', { project_id: projectId })
    addToast('此專案排程已恢復', 'success')
  }

  async function fetchSettings() {
    try {
      const res = await fetch(`${API}/api/v1/settings`)
      if (res.ok) settings.value = await res.json()
    } catch (e) {
      console.error('Failed to fetch settings', e)
    }
  }

  async function updateSettings(data: Record<string, string>) {
    const res = await fetch(`${API}/api/v1/settings`, {
      method: 'PUT',
      headers: _authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(data),
    })
    if (!res.ok) {
      if (res.status === 401) {
        _handle401(res)
      }
      throw new Error(`設定儲存失敗 (${res.status})`)
    }
    settings.value = await res.json()
  }

  // 運行中任務數量（by project）
  function runningCountByProject(projectName: string) {
    return runningTasks.value.filter(t => t.project === projectName).length
  }

  return {
    settings,
    connected,
    runningTasks,
    systemInfo,
    taskLogs,
    toasts,
    addToast,
    removeToast,
    setConnected,
    updateRunningTasks,
    updateSystemInfo,
    appendTaskLog,
    clearTaskLog,
    pauseRunner,
    resumeRunner,
    triggerCard,
    abortCard,
    deleteCard,
    deleteCronJob,
    pauseCron,
    resumeCron,
    runningCountByProject,
    fetchSettings,
    updateSettings,
  }
})
