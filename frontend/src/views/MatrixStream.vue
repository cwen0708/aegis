<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { useAegisStore } from '../stores/aegis'
import { config } from '../config'
import { Pause, Play, Trash2, Wifi, WifiOff, X } from 'lucide-vue-next'

const store = useAegisStore()

// --- State ---
const canvasRef = ref<HTMLCanvasElement | null>(null)
const paused = ref(false)
const messages = ref<WsMessage[]>([])
const selectedMsg = ref<WsMessage | null>(null)
const msgCount = ref(0)

const MAX_MESSAGES = 120
const COLUMN_COUNT = 5

interface WsMessage {
  id: number
  type: string
  data: any
  raw: string
  ts: number
  column: number
  opacity: number
}

// --- Matrix Rain (Canvas) ---
let ctx: CanvasRenderingContext2D | null = null
let animFrame = 0
let drops: number[] = []
const FONT_SIZE = 16
const KATAKANA = 'アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン'
const CHARS = KATAKANA + '0123456789ABCDEF{}[]:<>'

function initCanvas() {
  const canvas = canvasRef.value
  if (!canvas) return
  ctx = canvas.getContext('2d')
  resizeCanvas()
}

function resizeCanvas() {
  const canvas = canvasRef.value
  if (!canvas || !ctx) return
  canvas.width = window.innerWidth
  canvas.height = window.innerHeight
  const cols = Math.floor(canvas.width / FONT_SIZE)
  drops = Array.from({ length: cols }, () => Math.random() * -100)
}

function drawMatrix() {
  if (paused.value || !ctx || !canvasRef.value) {
    animFrame = requestAnimationFrame(drawMatrix)
    return
  }

  const canvas = canvasRef.value
  // Semi-transparent black overlay for trail effect
  ctx.fillStyle = 'rgba(0, 0, 0, 0.05)'
  ctx.fillRect(0, 0, canvas.width, canvas.height)

  ctx.font = `${FONT_SIZE}px monospace`

  for (let i = 0; i < drops.length; i++) {
    const char = CHARS.charAt(Math.floor(Math.random() * CHARS.length))
    const x = i * FONT_SIZE
    const drop = drops[i] ?? 0
    const y = drop * FONT_SIZE

    // Head character: bright green/white
    if (Math.random() > 0.8) {
      ctx.fillStyle = '#ffffff'
    } else {
      // Varying green brightness
      const brightness = 180 + Math.floor(Math.random() * 75)
      ctx.fillStyle = `rgb(0, ${brightness}, ${Math.floor(brightness * 0.25)})`
    }

    ctx.fillText(char, x, y)

    // Reset drop to top when it goes below screen
    if (y > canvas.height && Math.random() > 0.975) {
      drops[i] = 0
    }
    drops[i] = (drops[i] ?? 0) + 0.5 + Math.random() * 0.5
  }

  animFrame = requestAnimationFrame(drawMatrix)
}

// --- WebSocket Raw Message ---
function handleRawMessage(raw: string) {
  try {
    const parsed = JSON.parse(raw)
    const msg: WsMessage = {
      id: ++msgCount.value,
      type: parsed.type || 'unknown',
      data: parsed.data || parsed,
      raw,
      ts: Date.now(),
      column: Math.floor(Math.random() * COLUMN_COUNT),
      opacity: 1,
    }
    messages.value.unshift(msg)
    if (messages.value.length > MAX_MESSAGES) {
      messages.value = messages.value.slice(0, MAX_MESSAGES)
    }
  } catch {
    // Non-JSON message
    const msg: WsMessage = {
      id: ++msgCount.value,
      type: 'raw',
      data: raw,
      raw,
      ts: Date.now(),
      column: Math.floor(Math.random() * COLUMN_COUNT),
      opacity: 1,
    }
    messages.value.unshift(msg)
  }
}

let rawWsInstance: WebSocket | null = null
let mounted = true

function setupRawWs() {
  const token = localStorage.getItem('aegis-token') || ''
  const wsUrl = `${config.wsUrl}/ws?token=${token}`
  rawWsInstance = new WebSocket(wsUrl)
  rawWsInstance.onmessage = (event) => {
    handleRawMessage(event.data)
  }
  rawWsInstance.onclose = () => {
    if (mounted) {
      setTimeout(() => {
        if (mounted) setupRawWs()
      }, 3000)
    }
  }
}

// --- Type Colors ---
function typeColor(type: string): string {
  switch (type) {
    case 'task_completed': return 'text-green-300 bg-green-500/20 border-green-500/30'
    case 'task_started': return 'text-cyan-300 bg-cyan-500/20 border-cyan-500/30'
    case 'task_failed': return 'text-red-300 bg-red-500/20 border-red-500/30'
    case 'task_log': return 'text-green-500/70 bg-green-500/5 border-green-500/10'
    case 'running_tasks_update': return 'text-amber-300 bg-amber-500/20 border-amber-500/30'
    case 'system_info_update': return 'text-emerald-400/60 bg-emerald-500/10 border-emerald-500/20'
    case 'member_dialogue': return 'text-purple-300 bg-purple-500/20 border-purple-500/30'
    case 'clone_progress': return 'text-blue-300 bg-blue-500/20 border-blue-500/30'
    default: return 'text-green-400 bg-green-500/10 border-green-500/20'
  }
}

function typeOpacity(type: string): string {
  // Less important types are dimmer
  switch (type) {
    case 'system_info_update': return 'opacity-40'
    case 'running_tasks_update': return 'opacity-50'
    case 'task_log': return 'opacity-60'
    default: return 'opacity-90'
  }
}

function msgSummary(msg: WsMessage): string {
  const d = msg.data
  if (!d) return msg.type
  switch (msg.type) {
    case 'task_started': return `▶ ${d.card_title || `Card #${d.card_id}`}`
    case 'task_completed': return `✓ Card #${d.card_id}`
    case 'task_failed': return `✗ Card #${d.card_id}`
    case 'task_log': return d.line?.slice(0, 80) || '...'
    case 'system_info_update': return `CPU ${d.cpu_percent}% MEM ${d.mem_percent}%`
    case 'running_tasks_update': return `${Array.isArray(d) ? d.length : 0} tasks running`
    case 'member_dialogue': return d.text?.slice(0, 60) || d.member_name || '...'
    case 'clone_progress': return d.message?.slice(0, 60) || '...'
    default: return JSON.stringify(d).slice(0, 60)
  }
}

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString('zh-TW', { hour12: false })
}

function clearMessages() {
  messages.value = []
  msgCount.value = 0
}

function selectMessage(msg: WsMessage) {
  selectedMsg.value = selectedMsg.value?.id === msg.id ? null : msg
}

function closeDetail() {
  selectedMsg.value = null
}

// --- Lifecycle ---
onMounted(async () => {
  mounted = true
  await nextTick()
  initCanvas()
  window.addEventListener('resize', resizeCanvas)
  animFrame = requestAnimationFrame(drawMatrix)
  setupRawWs()
})

onUnmounted(() => {
  mounted = false
  cancelAnimationFrame(animFrame)
  window.removeEventListener('resize', resizeCanvas)
  if (rawWsInstance) {
    rawWsInstance.close()
    rawWsInstance = null
  }
})
</script>

<template>
  <div class="relative w-full h-full overflow-hidden bg-black select-none">
    <!-- Matrix Rain Canvas Background -->
    <canvas ref="canvasRef" class="absolute inset-0 w-full h-full" />

    <!-- Top Control Bar -->
    <div class="absolute top-0 left-0 right-0 z-30 flex items-center justify-between px-4 py-2 bg-gradient-to-b from-black/80 to-transparent">
      <div class="flex items-center gap-3">
        <h1 class="text-green-400 font-mono text-lg font-bold tracking-widest" style="text-shadow: 0 0 10px #00ff41, 0 0 20px #00ff41;">
          AEGIS STREAM
        </h1>
        <span class="text-green-600 font-mono text-xs">{{ msgCount }} messages</span>
      </div>
      <div class="flex items-center gap-2">
        <div class="flex items-center gap-1.5 text-xs font-mono">
          <Wifi v-if="store.connected" class="w-3.5 h-3.5 text-green-400" />
          <WifiOff v-else class="w-3.5 h-3.5 text-red-500" />
          <span :class="store.connected ? 'text-green-500' : 'text-red-500'">
            {{ store.connected ? 'CONNECTED' : 'OFFLINE' }}
          </span>
        </div>
        <button
          @click="paused = !paused"
          class="p-1.5 rounded border border-green-500/30 text-green-400 hover:bg-green-500/20 transition-colors"
          :title="paused ? '繼續' : '暫停'"
        >
          <Play v-if="paused" class="w-4 h-4" />
          <Pause v-else class="w-4 h-4" />
        </button>
        <button
          @click="clearMessages"
          class="p-1.5 rounded border border-green-500/30 text-green-400 hover:bg-green-500/20 transition-colors"
          title="清除"
        >
          <Trash2 class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- Message Waterfall Overlay -->
    <div class="absolute inset-0 z-10 flex gap-1 px-2 pt-12 pb-2 overflow-hidden pointer-events-none">
      <div
        v-for="col in COLUMN_COUNT"
        :key="col"
        class="flex-1 flex flex-col gap-1 overflow-hidden"
      >
        <TransitionGroup name="msg-slide">
          <div
            v-for="msg in messages.filter(m => m.column === col - 1).slice(0, 20)"
            :key="msg.id"
            class="pointer-events-auto cursor-pointer px-2 py-1 rounded border font-mono text-xs backdrop-blur-sm transition-all duration-300 hover:scale-[1.02] hover:brightness-150"
            :class="[typeColor(msg.type), typeOpacity(msg.type)]"
            @click="selectMessage(msg)"
          >
            <div class="flex items-center gap-1.5 mb-0.5">
              <span class="text-[10px] opacity-50">{{ formatTime(msg.ts) }}</span>
              <span class="px-1 py-0.5 rounded text-[9px] uppercase tracking-wider bg-black/30">
                {{ msg.type }}
              </span>
            </div>
            <div class="truncate leading-tight" style="text-shadow: 0 0 8px currentColor;">
              {{ msgSummary(msg) }}
            </div>
          </div>
        </TransitionGroup>
      </div>
    </div>

    <!-- Selected Message Detail -->
    <Transition name="detail-fade">
      <div
        v-if="selectedMsg"
        class="absolute inset-0 z-40 flex items-center justify-center bg-black/70 backdrop-blur-sm"
        @click.self="closeDetail"
      >
        <div class="max-w-2xl w-full mx-4 max-h-[80vh] flex flex-col rounded-lg border border-green-500/30 bg-black/90 shadow-[0_0_30px_rgba(0,255,65,0.15)]">
          <!-- Detail Header -->
          <div class="flex items-center justify-between px-4 py-3 border-b border-green-500/20">
            <div class="flex items-center gap-2">
              <span class="px-2 py-1 rounded text-xs uppercase tracking-wider font-mono border" :class="typeColor(selectedMsg.type)">
                {{ selectedMsg.type }}
              </span>
              <span class="text-green-600 font-mono text-xs">
                #{{ selectedMsg.id }} · {{ formatTime(selectedMsg.ts) }}
              </span>
            </div>
            <button @click="closeDetail" class="p-1 text-green-500 hover:text-green-300 transition-colors">
              <X class="w-5 h-5" />
            </button>
          </div>
          <!-- Detail Body -->
          <div class="flex-1 overflow-auto p-4">
            <pre class="text-green-400 font-mono text-xs whitespace-pre-wrap break-all leading-relaxed" style="text-shadow: 0 0 5px #00ff41;">{{ JSON.stringify(JSON.parse(selectedMsg.raw), null, 2) }}</pre>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Scanline Effect Overlay -->
    <div class="absolute inset-0 z-20 pointer-events-none opacity-[0.03]"
      style="background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,255,65,0.1) 2px, rgba(0,255,65,0.1) 4px);"
    />
  </div>
</template>

<style scoped>
/* Message slide-in animation */
.msg-slide-enter-active {
  transition: all 0.5s ease-out;
}
.msg-slide-leave-active {
  transition: all 0.3s ease-in;
}
.msg-slide-enter-from {
  opacity: 0;
  transform: translateY(-20px);
}
.msg-slide-leave-to {
  opacity: 0;
  transform: translateX(20px) scale(0.95);
}
.msg-slide-move {
  transition: transform 0.3s ease;
}

/* Detail panel animation */
.detail-fade-enter-active,
.detail-fade-leave-active {
  transition: opacity 0.2s ease;
}
.detail-fade-enter-from,
.detail-fade-leave-to {
  opacity: 0;
}
</style>
