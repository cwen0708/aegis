import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    tailwindcss(),
  ],
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
