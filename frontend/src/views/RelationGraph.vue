<template>
  <div class="h-full flex flex-col">
    <PageHeader :icon="Share2">
      <div class="flex items-center gap-2">
        <!-- 類型選擇 -->
        <select v-model="centerType" class="bg-slate-700 text-slate-200 text-xs rounded-lg px-2 py-1 border border-slate-600 outline-none">
          <option value="project">專案</option>
          <option value="member">成員</option>
          <option value="domain">網域</option>
          <option value="room">空間</option>
          <option value="user">用戶</option>
        </select>
        <!-- 對象選擇 -->
        <select v-model="centerId" class="bg-slate-700 text-slate-200 text-xs rounded-lg px-2 py-1 border border-slate-600 outline-none max-w-[200px]">
          <option v-for="e in currentEntities" :key="e.id" :value="e.id">{{ e.label }}</option>
        </select>
      </div>
    </PageHeader>

    <div class="flex-1 relative overflow-hidden bg-slate-900/50">
      <svg ref="svgEl" class="w-full h-full" @click.self="deselectNode">
        <!-- Edges -->
        <line
          v-for="(e, i) in edges"
          :key="'e' + i"
          :x1="getNodePos(e.source)?.x || 0" :y1="getNodePos(e.source)?.y || 0"
          :x2="getNodePos(e.target)?.x || 0" :y2="getNodePos(e.target)?.y || 0"
          :stroke="edgeColor(e)" stroke-width="1.5" opacity="0.3"
        />
        <!-- Edge labels -->
        <text
          v-for="(e, i) in edges"
          :key="'el' + i"
          :x="((getNodePos(e.source)?.x || 0) + (getNodePos(e.target)?.x || 0)) / 2"
          :y="((getNodePos(e.source)?.y || 0) + (getNodePos(e.target)?.y || 0)) / 2 - 6"
          text-anchor="middle" fill="#64748b" font-size="9"
        >{{ e.relation }}</text>

        <!-- Nodes -->
        <g
          v-for="n in positionedNodes"
          :key="n.key"
          class="cursor-pointer"
          @click.stop="onNodeClick(n)"
        >
          <!-- Circle -->
          <circle
            :cx="n.x" :cy="n.y"
            :r="n.key === centerKey ? 28 : 20"
            :fill="nodeColor(n.type)" :opacity="n.key === centerKey ? 0.2 : 0.1"
            :stroke="nodeColor(n.type)" stroke-width="2"
          />
          <!-- Icon text -->
          <text
            :x="n.x" :y="n.y + 1"
            text-anchor="middle" dominant-baseline="central"
            :fill="nodeColor(n.type)" font-size="14"
          >{{ nodeIcon(n.type) }}</text>
          <!-- Label -->
          <text
            :x="n.x" :y="n.y + (n.key === centerKey ? 38 : 30)"
            text-anchor="middle" :fill="nodeColor(n.type)" font-size="11" font-weight="bold"
          >{{ n.label.length > 12 ? n.label.slice(0, 12) + '…' : n.label }}</text>
          <!-- Sub label -->
          <text
            v-if="n.sub"
            :x="n.x" :y="n.y + (n.key === centerKey ? 50 : 42)"
            text-anchor="middle" fill="#64748b" font-size="9"
          >{{ n.sub }}</text>
          <!-- Hover tooltip -->
          <title>{{ n.label }}{{ n.sub ? ' · ' + n.sub : '' }}</title>
        </g>
      </svg>

      <!-- Legend -->
      <div class="absolute bottom-3 left-3 flex gap-3 text-[10px]">
        <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-purple-400"></span> 專案</span>
        <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-emerald-400"></span> 成員</span>
        <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-blue-400"></span> 網域</span>
        <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-amber-400"></span> 用戶</span>
        <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-orange-400"></span> 空間</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { Share2 } from 'lucide-vue-next'
import PageHeader from '../components/PageHeader.vue'
import { config } from '../config'

const API = config.apiUrl

// ── 狀態 ──
const centerType = ref('project')
const centerId = ref<number>(0)
const entities = ref<Record<string, { id: number; label: string }[]>>({})
const nodes = ref<any[]>([])
const edges = ref<any[]>([])
const svgEl = ref<SVGElement | null>(null)

// 節點位置（force simulation 結果）
const nodePositions = ref<Record<string, { x: number; y: number }>>({})

const centerKey = computed(() => `${centerType.value}:${centerId.value}`)
const currentEntities = computed(() => entities.value[centerType.value] || [])

// ── 顏色 ──
function nodeColor(type: string): string {
  const colors: Record<string, string> = {
    project: '#c084fc', member: '#34d399', domain: '#60a5fa',
    user: '#fbbf24', room: '#fb923c', account: '#f472b6', info: '#94a3b8',
  }
  return colors[type] || '#64748b'
}

function edgeColor(e: any): string {
  const sourceType = e.source.split(':')[0]
  return nodeColor(sourceType)
}

function nodeIcon(type: string): string {
  const icons: Record<string, string> = {
    project: '📁', member: '🤖', domain: '🌐',
    user: '👤', room: '🏠', account: '🔑', info: 'ℹ️',
  }
  return icons[type] || '●'
}

// ── 節點位置計算（簡單圓形佈局） ──
interface PositionedNode {
  key: string; type: string; id: number; label: string; sub?: string;
  x: number; y: number;
}

const positionedNodes = computed<PositionedNode[]>(() => {
  if (!svgEl.value || nodes.value.length === 0) return []
  const rect = svgEl.value.getBoundingClientRect()
  const cx = rect.width / 2
  const cy = rect.height / 2
  const radius = Math.min(cx, cy) * 0.6

  const result: PositionedNode[] = []
  const others = nodes.value.filter(n => `${n.type}:${n.id}` !== centerKey.value)
  const center = nodes.value.find(n => `${n.type}:${n.id}` === centerKey.value)

  // 中心節點
  if (center) {
    const key = `${center.type}:${center.id}`
    result.push({
      key, type: center.type, id: center.id,
      label: center.label, sub: subLabel(center),
      x: cx, y: cy,
    })
    nodePositions.value[key] = { x: cx, y: cy }
  }

  // 周圍節點（按類型分群）
  const grouped: Record<string, any[]> = {}
  for (const n of others) {
    (grouped[n.type] ||= []).push(n)
  }

  const types = Object.keys(grouped)
  let idx = 0
  const total = others.length

  for (let ti = 0; ti < types.length; ti++) {
    const group = grouped[types[ti]]
    for (let gi = 0; gi < group.length; gi++) {
      const n = group[gi]
      const angle = (idx / total) * Math.PI * 2 - Math.PI / 2
      const r = radius + (group.length > 5 ? (gi % 2) * 40 : 0)
      const x = cx + Math.cos(angle) * r
      const y = cy + Math.sin(angle) * r
      const key = `${n.type}:${n.id}`
      result.push({
        key, type: n.type, id: n.id,
        label: n.label, sub: subLabel(n),
        x, y,
      })
      nodePositions.value[key] = { x, y }
      idx++
    }
  }

  return result
})

function subLabel(n: any): string {
  if (n.type === 'user') {
    const parts = []
    if (n.platform) parts.push(n.platform)
    if (n.level !== undefined) parts.push(`Lv${n.level}`)
    if (n.has_ad) parts.push('AD✓')
    return parts.join(' · ')
  }
  if (n.type === 'member' && n.slug) return n.slug
  if (n.type === 'account' && n.provider) return n.provider
  if (n.type === 'project' && n.is_system) return '系統'
  return ''
}

function getNodePos(key: string) {
  return nodePositions.value[key]
}

// ── 載入 ──
async function loadEntities() {
  try {
    const res = await fetch(`${API}/api/v1/graph/entities`)
    if (res.ok) {
      entities.value = await res.json()
      // 預設選第一個
      if (!centerId.value && currentEntities.value.length) {
        centerId.value = currentEntities.value[0].id
      }
    }
  } catch { /* silent */ }
}

async function loadGraph() {
  if (!centerId.value) return
  try {
    const res = await fetch(`${API}/api/v1/graph/relations?center_type=${centerType.value}&center_id=${centerId.value}`)
    if (res.ok) {
      const data = await res.json()
      nodes.value = data.nodes || []
      edges.value = data.edges || []
    }
  } catch { /* silent */ }
}

function onNodeClick(n: PositionedNode) {
  if (n.type === 'info') return // info 節點不可點擊
  centerType.value = n.type
  centerId.value = n.id
}

function deselectNode() {
  // 點空白處不做事
}

// ── Watch ──
watch(centerType, () => {
  if (currentEntities.value.length) {
    centerId.value = currentEntities.value[0].id
  }
})

watch(centerId, () => {
  if (centerId.value) loadGraph()
})

onMounted(async () => {
  await loadEntities()
  await nextTick()
  if (centerId.value) loadGraph()
})
</script>
