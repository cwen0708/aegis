import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiClient } from '../services/api/client'

// RunningTask 已移至 task store，此處 re-export 保持向後相容
export type { RunningTask } from './task'

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

export interface Directive {
  action: string
  params: Record<string, any>
  card_id?: number | null
}

export const useAegisStore = defineStore('aegis', () => {
  // 系統設定
  const settings = ref<Record<string, string>>({})

  // WebSocket 狀態
  const connected = ref(false)
  const systemInfo = ref<SystemInfo>({
    cpu_percent: 0,
    mem_percent: 0,
    mem_available_gb: 0,
    is_paused: false,
    workstations_used: 0,
    workstations_total: 3,
  })

  // Directive 佇列
  const directiveQueue = ref<Directive[]>([])

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

  function handleDirective(data: Directive) {
    directiveQueue.value.push(data)
    // 限制佇列長度
    if (directiveQueue.value.length > 100) {
      directiveQueue.value.splice(0, directiveQueue.value.length - 100)
    }

    switch (data.action) {
      case 'notify': {
        const p = data.params || {}
        const message = p.message || 'Directive notification'
        const level = p.level || 'info'
        const type = level === 'error' ? 'error' : level === 'success' ? 'success' : 'info'
        addToast(message, type as Toast['type'])
        break
      }
      default:
        console.warn(`[Directive] Unknown action: ${data.action}`)
    }
  }

  function setConnected(val: boolean) {
    connected.value = val
  }

  function updateSystemInfo(info: SystemInfo) {
    systemInfo.value = info
  }

  async function pauseRunner() {
    await apiClient.post('/api/v1/runner/pause')
    systemInfo.value.is_paused = true
    addToast('Runner 已暫停', 'info')
  }

  async function resumeRunner() {
    await apiClient.post('/api/v1/runner/resume')
    systemInfo.value.is_paused = false
    addToast('Runner 已恢復', 'success')
  }

  async function triggerCard(cardId: number) {
    await apiClient.post(`/api/v1/cards/${cardId}/trigger`)
    addToast('任務已觸發', 'success')
  }

  async function abortCard(cardId: number) {
    await apiClient.post(`/api/v1/cards/${cardId}/abort`)
    addToast('任務已中止', 'info')
  }

  async function deleteCard(cardId: number) {
    await apiClient.delete(`/api/v1/cards/${cardId}`)
    addToast('卡片已刪除', 'success')
  }

  async function deleteCronJob(jobId: number) {
    await apiClient.delete(`/api/v1/cron-jobs/${jobId}`)
    addToast('排程已刪除', 'success')
  }

  async function pauseCron(projectId: number) {
    await apiClient.post('/api/v1/cron/pause', { project_id: projectId })
    addToast('此專案排程已暫停', 'info')
  }

  async function resumeCron(projectId: number) {
    await apiClient.post('/api/v1/cron/resume', { project_id: projectId })
    addToast('此專案排程已恢復', 'success')
  }

  async function fetchSettings() {
    try {
      settings.value = await apiClient.get<Record<string, string>>('/api/v1/settings')
    } catch (e) {
      console.error('Failed to fetch settings', e)
    }
  }

  async function updateSettings(data: Record<string, string>) {
    settings.value = await apiClient.put<Record<string, string>>('/api/v1/settings', data)
  }

  return {
    settings,
    connected,
    systemInfo,
    toasts,
    directiveQueue,
    addToast,
    removeToast,
    handleDirective,
    setConnected,
    updateSystemInfo,
    pauseRunner,
    resumeRunner,
    triggerCard,
    abortCard,
    deleteCard,
    deleteCronJob,
    pauseCron,
    resumeCron,
    fetchSettings,
    updateSettings,
  }
})
