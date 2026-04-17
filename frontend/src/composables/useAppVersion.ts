import { ref, onMounted } from 'vue'
import { config } from '../config'

/**
 * Version info returned by GET /api/v1/version (backend SSOT).
 */
export interface AppVersionInfo {
  current: string
  tag: string
  channel: 'development' | 'stable'
  latest: string
}

/**
 * Reactive app version, prioritising /api/v1/version with a build-time fallback.
 *
 * The fallback value __APP_VERSION__ is injected by vite.config.ts at build time
 * from backend/VERSION, so even offline the UI still shows a sensible version.
 */
export function useAppVersion() {
  // __APP_VERSION__ is injected by vite's `define` (see vite.config.ts)
  const buildTimeVersion: string =
    typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : '0.0.0'

  const version = ref<string>(buildTimeVersion)
  const info = ref<AppVersionInfo | null>(null)
  const loading = ref(false)
  const error = ref<string>('')

  async function fetchVersion(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      const res = await fetch(`${config.apiUrl}/api/v1/version`)
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`)
      }
      const data = (await res.json()) as AppVersionInfo
      info.value = data
      if (data.current) {
        version.value = data.current
      }
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'unknown error'
      // Keep the build-time fallback, don't reset version
    } finally {
      loading.value = false
    }
  }

  onMounted(() => {
    void fetchVersion()
  })

  return { version, info, loading, error, fetchVersion }
}
