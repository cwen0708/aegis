<template>
  <div class="h-full flex flex-col">
    <PageHeader :icon="Share2">
      <div class="flex items-center gap-2">
        <select v-model="centerType" class="bg-slate-700 text-slate-200 text-xs rounded-lg px-2 py-1 border border-slate-600 outline-none">
          <option value="project">專案</option>
          <option value="member">成員</option>
          <option value="domain">網域</option>
          <option value="room">空間</option>
          <option value="user">用戶</option>
        </select>
        <select v-model="centerId" class="bg-slate-700 text-slate-200 text-xs rounded-lg px-2 py-1 border border-slate-600 outline-none max-w-[200px]">
          <option v-for="e in currentEntities" :key="e.id" :value="e.id">{{ e.label }}</option>
        </select>
      </div>
    </PageHeader>

    <div class="flex-1 relative overflow-hidden bg-slate-900/50">
      <div ref="cyContainer" class="w-full h-full" />

      <!-- Legend -->
      <div class="absolute bottom-3 left-3 flex gap-3 text-[10px] text-slate-400 bg-slate-800/80 px-3 py-1.5 rounded-lg">
        <span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-full bg-purple-500"></span> 專案</span>
        <span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-full bg-emerald-500"></span> 成員</span>
        <span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-full bg-blue-500"></span> 網域</span>
        <span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-full bg-amber-500"></span> 用戶</span>
        <span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-full bg-orange-500"></span> 空間</span>
        <span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-full bg-pink-500"></span> 帳號</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { Share2 } from 'lucide-vue-next'
import PageHeader from '../components/PageHeader.vue'
import { config } from '../config'
import cytoscape from 'cytoscape'
import type { Core } from 'cytoscape'

const API = config.apiUrl

// ── 狀態 ──
const centerType = ref('project')
const centerId = ref<number>(0)
const entities = ref<Record<string, { id: number; label: string }[]>>({})
const cyContainer = ref<HTMLElement | null>(null)
let cy: Core | null = null

const currentEntities = computed(() => entities.value[centerType.value] || [])

// ── 顏色 ──
const nodeColors: Record<string, { bg: string; border: string; text: string }> = {
  project: { bg: '#7c3aed', border: '#a78bfa', text: '#e9d5ff' },
  member: { bg: '#059669', border: '#34d399', text: '#d1fae5' },
  domain: { bg: '#2563eb', border: '#60a5fa', text: '#dbeafe' },
  user: { bg: '#d97706', border: '#fbbf24', text: '#fef3c7' },
  room: { bg: '#ea580c', border: '#fb923c', text: '#ffedd5' },
  account: { bg: '#db2777', border: '#f472b6', text: '#fce7f3' },
  info: { bg: '#475569', border: '#94a3b8', text: '#e2e8f0' },
}

function getColor(type: string) {
  return nodeColors[type] || nodeColors.info!
}

// ── Cytoscape 初始化 ──
function initCytoscape() {
  if (!cyContainer.value) return

  cy = cytoscape({
    container: cyContainer.value,
    style: [
      {
        selector: 'node',
        style: {
          'label': 'data(label)',
          'text-valign': 'bottom',
          'text-halign': 'center',
          'font-size': '11px',
          'color': '#e2e8f0',
          'text-margin-y': 6,
          'width': 40,
          'height': 40,
          'background-color': 'data(bgColor)',
          'border-color': 'data(borderColor)',
          'border-width': 2,
          'text-wrap': 'ellipsis',
          'text-max-width': '80px',
        },
      },
      {
        selector: 'node[?isCenter]',
        style: {
          'width': 56,
          'height': 56,
          'border-width': 3,
          'font-size': '13px',
          'font-weight': 'bold',
        },
      },
      {
        selector: 'node[sub]',
        style: {
          'label': 'data(fullLabel)',
          'text-wrap': 'wrap',
          'text-max-width': '100px',
          'font-size': '10px',
          'line-height': 1.3,
        },
      },
      {
        selector: 'edge',
        style: {
          'width': 1.5,
          'line-color': '#334155',
          'target-arrow-color': '#334155',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          'arrow-scale': 0.8,
          'label': 'data(relation)',
          'font-size': '9px',
          'color': '#64748b',
          'text-rotation': 'autorotate',
          'text-margin-y': -8,
        },
      },
      {
        selector: 'edge:selected',
        style: {
          'width': 2.5,
          'line-color': '#60a5fa',
        },
      },
    ],
    layout: { name: 'preset' },
    minZoom: 0.3,
    maxZoom: 3,
    wheelSensitivity: 0.3,
  })

  // 點擊節點 → 重新展開
  cy.on('tap', 'node', (evt) => {
    const node = evt.target
    const type = node.data('nodeType')
    const id = node.data('nodeId')
    if (type && id && type !== 'info') {
      centerType.value = type
      centerId.value = id
    }
  })
}

// ── 渲染圖形 ──
function renderGraph(data: { center: string; nodes: any[]; edges: any[] }) {
  if (!cy) return

  const elements: cytoscape.ElementDefinition[] = []
  const centerKey = data.center

  // 節點
  for (const n of data.nodes) {
    const key = `${n.type}:${n.id}`
    const color = getColor(n.type)
    const isCenter = key === centerKey
    const sub = subLabel(n)

    elements.push({
      data: {
        id: key,
        label: n.label,
        fullLabel: sub ? `${n.label}\n${sub}` : n.label,
        sub: sub || undefined,
        nodeType: n.type,
        nodeId: n.id,
        isCenter,
        bgColor: color.bg,
        borderColor: color.border,
      },
    })
  }

  // 邊
  for (const e of data.edges) {
    elements.push({
      data: {
        id: `${e.source}-${e.target}`,
        source: e.source,
        target: e.target,
        relation: e.relation,
      },
    })
  }

  cy.elements().remove()
  cy.add(elements)

  // 階梯式佈局（從左到右）
  cy.layout({
    name: 'breadthfirst',
    directed: true,
    roots: centerKey ? [centerKey] : undefined,
    spacingFactor: 1.5,
    avoidOverlap: true,
    // @ts-ignore - cytoscape 的 breadthfirst 支援但類型沒宣告
    orientation: 'horizontal',
  } as any).run()

  // 動畫 fit
  cy.animate({ fit: { eles: cy.elements(), padding: 40 } } as any, { duration: 300 })
}

function subLabel(n: any): string {
  if (n.type === 'user') {
    const parts: string[] = []
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

// ── 資料載入 ──
async function loadEntities() {
  try {
    const res = await fetch(`${API}/api/v1/graph/entities`)
    if (res.ok) {
      entities.value = await res.json()
      if (!centerId.value && currentEntities.value.length) {
        centerId.value = currentEntities.value[0]!.id
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
      renderGraph(data)
    }
  } catch { /* silent */ }
}

// ── Watch ──
watch(centerType, () => {
  if (currentEntities.value.length) {
    centerId.value = currentEntities.value[0]!.id
  }
})

watch(centerId, () => {
  if (centerId.value) loadGraph()
})

onMounted(async () => {
  await loadEntities()
  await nextTick()
  initCytoscape()
  if (centerId.value) loadGraph()
})

onUnmounted(() => {
  if (cy) {
    cy.destroy()
    cy = null
  }
})
</script>
