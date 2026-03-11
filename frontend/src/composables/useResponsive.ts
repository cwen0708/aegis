import { ref, computed } from 'vue'

// Shared state across components
const windowWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1024)
const windowHeight = ref(typeof window !== 'undefined' ? window.innerHeight : 768)

let listenersAttached = false

function attachListeners() {
  if (listenersAttached || typeof window === 'undefined') return

  const handleResize = () => {
    windowWidth.value = window.innerWidth
    windowHeight.value = window.innerHeight
  }

  window.addEventListener('resize', handleResize)
  listenersAttached = true
}

// Initialize listeners immediately if in browser
if (typeof window !== 'undefined') {
  attachListeners()
}

/**
 * Responsive utilities composable
 * Provides reactive screen size detection and touch device detection
 */
export function useResponsive() {
  // Breakpoints following Tailwind defaults
  const isMobile = computed(() => windowWidth.value < 768)  // < md
  const isTablet = computed(() => windowWidth.value >= 768 && windowWidth.value < 1024)  // md to lg
  const isDesktop = computed(() => windowWidth.value >= 1024)  // >= lg

  // Touch device detection
  const isTouchDevice = computed(() => {
    if (typeof window === 'undefined') return false
    return 'ontouchstart' in window || navigator.maxTouchPoints > 0
  })

  // Combined checks
  const isMobileOrTouch = computed(() => isMobile.value || isTouchDevice.value)

  // Screen dimensions
  const screenWidth = computed(() => windowWidth.value)
  const screenHeight = computed(() => windowHeight.value)

  return {
    // Breakpoints
    isMobile,
    isTablet,
    isDesktop,

    // Touch detection
    isTouchDevice,
    isMobileOrTouch,

    // Dimensions
    screenWidth,
    screenHeight,
  }
}

/**
 * Touch-friendly class helper
 * Returns classes that make hover-only features visible on touch devices
 */
export function useTouchFriendly() {
  const { isTouchDevice } = useResponsive()

  /**
   * Returns opacity class that's always visible on touch devices
   * Usage: :class="touchVisible('opacity-0 group-hover:opacity-100')"
   */
  const touchVisible = (hoverClasses: string) => {
    if (isTouchDevice.value) {
      return 'opacity-100'
    }
    return hoverClasses
  }

  return {
    isTouchDevice,
    touchVisible,
  }
}
