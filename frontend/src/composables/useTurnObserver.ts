import { onBeforeUnmount, ref, watch, type Ref } from 'vue'

export interface UseTurnObserverOptions {
  /** Selector used to locate turn elements inside the scroll container. */
  selector?: string
  /** IntersectionObserver root margin. Use to bias the "active" band. */
  rootMargin?: string
  /** Thresholds to trigger callbacks. */
  threshold?: number | number[]
}

export interface UseTurnObserverResult {
  /** Reactive index (0-based) of the turn currently most visible. -1 when none. */
  activeTurnIndex: Ref<number>
  /** Manually force a re-scan (e.g. after turns list changes). */
  refresh: () => void
  /** Stop observing and detach. */
  disconnect: () => void
}

/**
 * Observes `[data-turn-index]` elements inside a scroll container and
 * exposes the index of the turn currently most visible in the viewport.
 *
 * Immutable contract: never mutates caller's refs; returns fresh reactive state.
 */
export function useTurnObserver(
  container: Ref<HTMLElement | null>,
  options: UseTurnObserverOptions = {},
): UseTurnObserverResult {
  const selector = options.selector ?? '[data-turn-index]'
  const rootMargin = options.rootMargin ?? '-30% 0px -60% 0px'
  const threshold = options.threshold ?? [0, 0.25, 0.5, 0.75, 1]

  const activeTurnIndex = ref<number>(-1)
  const visibilityMap = new Map<number, number>()

  let observer: IntersectionObserver | null = null
  let mutationObserver: MutationObserver | null = null

  function parseIndex(el: Element): number {
    const raw = (el as HTMLElement).dataset?.turnIndex
    if (raw == null) return -1
    const n = Number.parseInt(raw, 10)
    return Number.isFinite(n) ? n : -1
  }

  function recomputeActive(): void {
    let bestIndex = -1
    let bestRatio = -1
    for (const [idx, ratio] of visibilityMap) {
      if (ratio > bestRatio) {
        bestRatio = ratio
        bestIndex = idx
      }
    }
    if (bestRatio <= 0) {
      // Nothing meaningfully visible — keep previous value to avoid flicker.
      return
    }
    if (bestIndex !== activeTurnIndex.value) {
      activeTurnIndex.value = bestIndex
    }
  }

  function handleEntries(entries: IntersectionObserverEntry[]): void {
    for (const entry of entries) {
      const idx = parseIndex(entry.target)
      if (idx < 0) continue
      if (entry.isIntersecting) {
        visibilityMap.set(idx, entry.intersectionRatio)
      } else {
        visibilityMap.delete(idx)
      }
    }
    recomputeActive()
  }

  function attach(root: HTMLElement): void {
    detach()
    visibilityMap.clear()

    observer = new IntersectionObserver(handleEntries, {
      root,
      rootMargin,
      threshold,
    })

    const targets = root.querySelectorAll(selector)
    targets.forEach((el) => observer?.observe(el))

    mutationObserver = new MutationObserver(() => {
      if (!observer) return
      const next = root.querySelectorAll(selector)
      observer.disconnect()
      visibilityMap.clear()
      next.forEach((el) => observer?.observe(el))
    })
    mutationObserver.observe(root, { childList: true, subtree: true })
  }

  function detach(): void {
    observer?.disconnect()
    observer = null
    mutationObserver?.disconnect()
    mutationObserver = null
  }

  function refresh(): void {
    const root = container.value
    if (!root) return
    attach(root)
  }

  watch(
    container,
    (root) => {
      if (root) {
        attach(root)
      } else {
        detach()
        activeTurnIndex.value = -1
      }
    },
    { immediate: true, flush: 'post' },
  )

  onBeforeUnmount(() => {
    detach()
  })

  return {
    activeTurnIndex,
    refresh,
    disconnect: detach,
  }
}
