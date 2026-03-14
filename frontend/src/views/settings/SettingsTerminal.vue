<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { Terminal as XTerm } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import '@xterm/xterm/css/xterm.css'
import { Circle, Loader2 } from 'lucide-vue-next'
import { config } from '../../config'

const route = useRoute()
// 從 query param 取得初始工作目錄
const initialCwd = (route.query.cwd as string) || ''

const termRef = ref<HTMLDivElement>()
const status = ref<'connecting' | 'connected' | 'disconnected'>('disconnected')

let term: XTerm | null = null
let fitAddon: FitAddon | null = null
let ws: WebSocket | null = null
let resizeObserver: ResizeObserver | null = null

function getWsUrl() {
  const base = config.apiUrl.replace(/^http/, 'ws')
  return `${base}/ws/terminal`
}

function connect() {
  if (ws && ws.readyState === WebSocket.OPEN) return

  status.value = 'connecting'
  ws = new WebSocket(getWsUrl())

  ws.onopen = () => {
    status.value = 'connected'
    term?.focus()
    // 自動 cd 到指定目錄
    if (initialCwd) {
      setTimeout(() => sendInput(`cd ${initialCwd}\n`), 300)
    }
  }

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)
      if (msg.type === 'output' && msg.data) {
        term?.write(msg.data)
      }
    } catch {
      // raw text fallback
      term?.write(event.data)
    }
  }

  ws.onclose = () => {
    status.value = 'disconnected'
    term?.write('\r\n\x1b[31m[連線已關閉]\x1b[0m\r\n')
  }

  ws.onerror = () => {
    status.value = 'disconnected'
  }
}

function disconnect() {
  if (ws) {
    ws.close()
    ws = null
  }
  status.value = 'disconnected'
}

function sendInput(data: string) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'input', data }))
  }
}

function sendResize(cols: number, rows: number) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'resize', cols, rows }))
  }
}

onMounted(async () => {
  await nextTick()
  if (!termRef.value) return

  term = new XTerm({
    cursorBlink: true,
    fontSize: 14,
    fontFamily: "'JetBrains Mono', 'Cascadia Code', 'Fira Code', Menlo, monospace",
    theme: {
      background: '#0f172a',
      foreground: '#e2e8f0',
      cursor: '#10b981',
      selectionBackground: '#334155',
      black: '#1e293b',
      red: '#ef4444',
      green: '#22c55e',
      yellow: '#eab308',
      blue: '#3b82f6',
      magenta: '#a855f7',
      cyan: '#06b6d4',
      white: '#f1f5f9',
    },
    scrollback: 5000,
    allowProposedApi: true,
  })

  fitAddon = new FitAddon()
  term.loadAddon(fitAddon)
  term.loadAddon(new WebLinksAddon())
  term.open(termRef.value)

  // Fit to container
  setTimeout(() => {
    fitAddon?.fit()
    sendResize(term!.cols, term!.rows)
  }, 100)

  // Handle resize
  resizeObserver = new ResizeObserver(() => {
    fitAddon?.fit()
    if (term) sendResize(term.cols, term.rows)
  })
  resizeObserver.observe(termRef.value)

  // Forward input to WebSocket
  term.onData((data) => sendInput(data))

  // Auto-connect
  connect()
})

onUnmounted(() => {
  disconnect()
  resizeObserver?.disconnect()
  term?.dispose()
})
</script>

<template>
  <div class="flex flex-col h-[calc(100vh-5rem)]">
    <!-- Header actions -->
    <Teleport to="#settings-header-actions">
      <div class="flex items-center gap-2">
        <!-- Status -->
        <div class="flex items-center gap-1.5 text-xs">
          <Loader2 v-if="status === 'connecting'" class="w-3.5 h-3.5 animate-spin text-amber-400" />
          <Circle v-else-if="status === 'connected'" class="w-2.5 h-2.5 fill-green-400 text-green-400" />
          <Circle v-else class="w-2.5 h-2.5 fill-slate-500 text-slate-500" />
          <span class="hidden sm:inline" :class="status === 'connected' ? 'text-green-400' : status === 'connecting' ? 'text-amber-400' : 'text-slate-500'">
            {{ status === 'connected' ? '已連線' : status === 'connecting' ? '連線中...' : '未連線' }}
          </span>
        </div>
        <!-- Connect/Disconnect -->
        <button
          v-if="status === 'disconnected'"
          @click="connect"
          class="px-3 py-1.5 text-xs bg-emerald-600 hover:bg-emerald-500 rounded-lg transition"
        >
          連線
        </button>
        <button
          v-else-if="status === 'connected'"
          @click="disconnect"
          class="px-3 py-1.5 text-xs bg-slate-700 hover:bg-red-600/80 text-slate-300 hover:text-white rounded-lg transition"
        >
          斷線
        </button>
      </div>
    </Teleport>

    <!-- Terminal (full area) -->
    <div
      ref="termRef"
      class="flex-1 rounded-xl border border-slate-700 overflow-hidden bg-[#0f172a]"
    ></div>
  </div>
</template>
