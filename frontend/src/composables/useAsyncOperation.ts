import { ref } from 'vue'

interface AsyncOpOptions {
  name?: string // 用於調試
}

export function useAsyncOp() {
  const loading = ref(true)
  const saving = ref(false)

  async function run<T>(fn: () => Promise<T>, options?: AsyncOpOptions): Promise<T | null> {
    saving.value = true
    try {
      return await fn()
    } catch (error) {
      console.error(`Async operation failed${options?.name ? ` [${options.name}]` : ''}:`, error)
      throw error
    } finally {
      saving.value = false
    }
  }

  return { loading, saving, run }
}
