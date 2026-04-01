import { ref, computed } from 'vue'

/**
 * usePagination — 通用分頁 composable
 *
 * 用法：
 *   const { currentPage, pageSize, totalPages, paginate, nextPage, prevPage, hasNext, hasPrev } = usePagination()
 *   const pageItems = computed(() => paginate(allItems.value))
 */
export function usePagination(initialPageSize = 10) {
  const currentPage = ref(1)
  const pageSize = ref(initialPageSize)
  const total = ref(0)

  const totalPages = computed(() => {
    if (total.value === 0 || pageSize.value <= 0) return 1
    return Math.ceil(total.value / pageSize.value)
  })

  const hasNext = computed(() => currentPage.value < totalPages.value)
  const hasPrev = computed(() => currentPage.value > 1)

  /**
   * 對陣列進行分頁切片，同時更新 total
   */
  function paginate<T>(items: T[]): T[] {
    total.value = items.length
    const start = (currentPage.value - 1) * pageSize.value
    return items.slice(start, start + pageSize.value)
  }

  function nextPage() {
    if (hasNext.value) currentPage.value++
  }

  function prevPage() {
    if (hasPrev.value) currentPage.value--
  }

  function goToPage(page: number) {
    const clamped = Math.max(1, Math.min(page, totalPages.value))
    currentPage.value = clamped
  }

  function reset() {
    currentPage.value = 1
  }

  return {
    currentPage,
    pageSize,
    total,
    totalPages,
    hasNext,
    hasPrev,
    paginate,
    nextPage,
    prevPage,
    goToPage,
    reset,
  }
}
