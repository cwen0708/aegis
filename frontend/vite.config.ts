import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/**
 * Read backend/VERSION as the single source of truth for the app version.
 * Falls back to "0.0.0" if the file is missing (e.g. frontend-only builds).
 */
function readBackendVersion(): string {
  try {
    const versionPath = resolve(__dirname, '../backend/VERSION')
    return readFileSync(versionPath, 'utf-8').trim() || '0.0.0'
  } catch {
    return '0.0.0'
  }
}

const APP_VERSION = readBackendVersion()

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    tailwindcss(),
  ],
  define: {
    // 供前端透過 import.meta.env.__APP_VERSION__ / globalThis.__APP_VERSION__ 取得
    __APP_VERSION__: JSON.stringify(APP_VERSION),
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-vue': ['vue', 'vue-router', 'pinia'],
          'vendor-phaser': ['phaser'],
          'vendor-three': ['three'],
          'vendor-cytoscape': ['cytoscape'],
          'vendor-xterm': ['@xterm/xterm', '@xterm/addon-fit', '@xterm/addon-web-links'],
          'vendor-markdown': ['marked', 'dompurify', 'highlight.js'],
        },
      },
    },
  },
  server: {
    port: 8888,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8899',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8899',
        ws: true,
      },
    },
  },
})
