import { ref } from 'vue'
import { useEscapeKey } from './useEscapeKey'

/**
 * Composable for managing dialog open/close state
 * @param options.escapeToClose - 按 ESC 自動關閉（預設 true）
 */
export function useDialogState(options?: { escapeToClose?: boolean }) {
  const isOpen = ref(false)

  function open() {
    isOpen.value = true
  }

  function close() {
    isOpen.value = false
  }

  if (options?.escapeToClose !== false) {
    useEscapeKey(isOpen, close)
  }

  return { isOpen, open, close }
}
