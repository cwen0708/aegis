import { ref } from 'vue'
import { useEscapeKey } from './useEscapeKey'

export interface UseDialogStateOptions<T extends Record<string, any> = Record<string, any>> {
  /** 按 ESC 自動關閉（預設 true） */
  escapeToClose?: boolean
  /** 表單初始值 */
  initialForm?: T
  /** 提交處理函式（可選） */
  onSubmit?: (form: T) => Promise<void>
}

/**
 * Composable for managing dialog state and form data
 *
 * 支援兩種用法：
 * 1. Dialog 模式：管理對話框開關 + 表單資料
 * 2. Form 模式：直接管理表單資料和加載狀態
 *
 * @param options - 配置選項
 * @returns 包含 isOpen, form, loading, open, close, resetForm, submit 的物件
 */
export function useDialogState<T extends Record<string, any> = Record<string, any>>(
  options?: UseDialogStateOptions<T>
) {
  const isOpen = ref(false)
  const form = ref<T>(options?.initialForm ? { ...options.initialForm } : ({} as T))
  const loading = ref(false)

  function open(initialData?: Partial<T>) {
    if (initialData) {
      form.value = { ...form.value, ...initialData } as T
    }
    isOpen.value = true
  }

  function close() {
    isOpen.value = false
  }

  function resetForm(initialData?: T) {
    form.value = initialData ? { ...initialData } : ({} as T)
  }

  async function submit() {
    if (!options?.onSubmit) {
      console.warn('useDialogState: no onSubmit handler provided')
      return
    }
    loading.value = true
    try {
      await options.onSubmit(form.value)
    } finally {
      loading.value = false
    }
  }

  if (options?.escapeToClose !== false) {
    useEscapeKey(isOpen, close)
  }

  return {
    isOpen,
    form,
    loading,
    open,
    close,
    resetForm,
    submit,
  }
}
