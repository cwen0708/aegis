/// <reference types="vite/client" />

/**
 * Build-time injected app version, sourced from backend/VERSION via vite.config.ts.
 * Used as a fallback when /api/v1/version is unreachable.
 */
declare const __APP_VERSION__: string
