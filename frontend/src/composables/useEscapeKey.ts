import { onUnmounted, watch, type Ref } from 'vue'

/**
 * Composable for handling ESC key to close modals/dialogs
 * @param isOpen - Reactive ref indicating if the modal is open
 * @param onClose - Callback function to close the modal
 */
export function useEscapeKey(isOpen: Ref<boolean>, onClose: () => void) {
  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === 'Escape' && isOpen.value) {
      e.preventDefault()
      onClose()
    }
  }

  // Add/remove listener based on modal state
  watch(isOpen, (open) => {
    if (open) {
      window.addEventListener('keydown', handleKeyDown)
    } else {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, { immediate: true })

  // Cleanup on unmount
  onUnmounted(() => {
    window.removeEventListener('keydown', handleKeyDown)
  })
}

/**
 * Composable for handling ESC key with multiple modals (stack-based)
 * Only the topmost modal should respond to ESC
 */
const modalStack: Array<() => void> = []

export function useEscapeKeyStack(isOpen: Ref<boolean>, onClose: () => void) {
  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === 'Escape' && modalStack.length > 0) {
      e.preventDefault()
      // Close the topmost modal
      const topClose = modalStack[modalStack.length - 1]
      if (topClose) {
        topClose()
      }
    }
  }

  watch(isOpen, (open) => {
    if (open) {
      modalStack.push(onClose)
      // Only add listener once (when stack becomes non-empty)
      if (modalStack.length === 1) {
        window.addEventListener('keydown', handleKeyDown)
      }
    } else {
      const idx = modalStack.indexOf(onClose)
      if (idx !== -1) {
        modalStack.splice(idx, 1)
      }
      // Remove listener when stack is empty
      if (modalStack.length === 0) {
        window.removeEventListener('keydown', handleKeyDown)
      }
    }
  }, { immediate: true })

  onUnmounted(() => {
    const idx = modalStack.indexOf(onClose)
    if (idx !== -1) {
      modalStack.splice(idx, 1)
    }
    if (modalStack.length === 0) {
      window.removeEventListener('keydown', handleKeyDown)
    }
  })
}
