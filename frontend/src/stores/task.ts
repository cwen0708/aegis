import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface RunningTask {
  task_id: number
  project: string
  card_title: string
  started_at: number
  pid: number | null
  provider: string
  member_id: number | null
}

export const useTaskStore = defineStore('task', () => {
  const runningTasks = ref<RunningTask[]>([])
  const taskLogs = ref<Map<number, string[]>>(new Map())

  function updateRunningTasks(tasks: RunningTask[]) {
    runningTasks.value = tasks
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

  function runningCountByProject(projectName: string) {
    return runningTasks.value.filter(t => t.project === projectName).length
  }

  return {
    runningTasks,
    taskLogs,
    updateRunningTasks,
    appendTaskLog,
    clearTaskLog,
    runningCountByProject,
  }
})
