<template>
  <div class="h-full flex flex-col">
    <PageHeader :icon="Share2">
      <div class="flex items-center gap-2">
        <!-- 起點選擇 -->
        <select v-model="centerType" class="bg-slate-700 text-slate-200 text-xs rounded-lg px-2 py-1 border border-slate-600 outline-none">
          <option value="">全部</option>
          <option value="project">專案</option>
          <option value="member">成員</option>
          <option value="domain">網域</option>
          <option value="room">空間</option>
          <option value="user">用戶</option>
        </select>
        <select v-if="centerType" v-model="centerId" class="bg-slate-700 text-slate-200 text-xs rounded-lg px-2 py-1 border border-slate-600 outline-none max-w-[200px]">
          <option v-for="e in currentEntities" :key="e.id" :value="e.id">{{ e.label }}</option>
        </select>
        <!-- Layout 切換 -->
        <button
          @click="toggleLayout"
          class="text-[10px] px-2 py-1 rounded-md border text-slate-400 border-slate-600 hover:text-slate-200 hover:border-slate-500 transition-colors"
        >{{ layoutName === 'breadthfirst' ? '樹狀' : layoutName === 'cose' ? '力導向' : '圓形' }}</button>
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
import type { Core, ElementDefinition } from 'cytoscape'

const API = config.apiUrl

// ── 狀態 ──
const centerType = ref('')
const centerId = ref<number>(0)
const cyContainer = ref<HTMLElement | null>(null)
let cy: Core | null = null
let allElements: ElementDefinition[] = []
const layoutName = ref<'breadthfirst' | 'cose' | 'circle'>('cose')

// ── 從 API 資料中提取各類型列表（給下拉選單用）──
const entityLists = ref<Record<string, { id: number; label: string }[]>>({})
const currentEntities = computed(() => entityLists.value[centerType.value] || [])

// ── 顏色 ──
const nodeColors: Record<string, { bg: string; border: string }> = {
  project: { bg: '#7c3aed', border: '#a78bfa' },
  member: { bg: '#059669', border: '#34d399' },
  domain: { bg: '#2563eb', border: '#60a5fa' },
  user: { bg: '#d97706', border: '#fbbf24' },
  room: { bg: '#ea580c', border: '#fb923c' },
  account: { bg: '#db2777', border: '#f472b6' },
}

function getColor(type: string) {
  return nodeColors[type] || { bg: '#475569', border: '#94a3b8' }
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

// ── Cytoscape 初始化 ──
function initCytoscape() {
  if (!cyContainer.value) return

  cy = cytoscape({
    container: cyContainer.value,
    style: [
      {
        selector: 'node',
        style: {
          'label': 'data(displayLabel)',
          'text-valign': 'bottom',
          'text-halign': 'center',
          'font-size': '10px',
          'color': '#cbd5e1',
          'text-margin-y': 6,
          'width': 36,
          'height': 36,
          'background-color': 'data(bgColor)',
          'border-color': 'data(borderColor)',
          'border-width': 2,
          'text-wrap': 'ellipsis',
          'text-max-width': '80px',
        },
      },
      {
        selector: 'node.center',
        style: {
          'width': 52,
          'height': 52,
          'border-width': 3,
          'font-size': '12px',
          'font-weight': 'bold',
          'color': '#f1f5f9',
        },
      },
      {
        selector: 'node.dimmed',
        style: {
          'opacity': 0.2,
        },
      },
      {
        selector: 'edge',
        style: {
          'width': 1.5,
          'line-color': '#1e293b',
          'target-arrow-color': '#334155',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          'arrow-scale': 0.7,
          'label': 'data(relation)',
          'font-size': '8px',
          'color': '#475569',
          'text-rotation': 'autorotate',
          'text-margin-y': -8,
        },
      },
      {
        selector: 'edge.dimmed',
        style: {
          'opacity': 0.1,
        },
      },
      {
        selector: 'edge.highlighted',
        style: {
          'width': 2.5,
          'line-color': '#60a5fa',
          'target-arrow-color': '#60a5fa',
          'opacity': 1,
        },
      },
    ],
    layout: { name: 'preset' },
    minZoom: 0.2,
    maxZoom: 3,
    wheelSensitivity: 0.3,
  })

  // 點擊節點 → 以它為中心重新佈局
  cy.on('tap', 'node', (evt) => {
    const node = evt.target
    const type = node.data('nodeType')
    const id = node.data('nodeId')
    if (type && id) {
      centerType.value = type
      centerId.value = id
    }
  })

  // 點空白 → 顯示全部
  cy.on('tap', (evt) => {
    if (evt.target === cy) {
      centerType.value = ''
      centerId.value = 0
    }
  })

  // Hover highlight
  cy.on('mouseover', 'node', (evt) => {
    const node = evt.target
    const neighborhood = node.closedNeighborhood()
    cy!.elements().addClass('dimmed')
    neighborhood.removeClass('dimmed')
    neighborhood.edges().addClass('highlighted')
  })

  cy.on('mouseout', 'node', () => {
    cy!.elements().removeClass('dimmed').removeClass('highlighted')
  })
}

// ── 載入全部資料 ──
async function loadAll() {
  try {
    const res = await fetch(`${API}/api/v1/graph/all`)
    if (!res.ok) return
    const data = await res.json()

    // 建立下拉選單
    const lists: Record<string, { id: number; label: string }[]> = {}
    for (const n of data.nodes) {
      if (!lists[n.type]) lists[n.type] = []
      lists[n.type]!.push({ id: n.id, label: n.label })
    }
    entityLists.value = lists

    // 轉成 Cytoscape elements
    allElements = []
    for (const n of data.nodes) {
      const key = `${n.type}:${n.id}`
      const color = getColor(n.type)
      const sub = subLabel(n)
      allElements.push({
        data: {
          id: key,
          label: n.label,
          displayLabel: sub ? `${n.label}\n${sub}` : n.label,
          nodeType: n.type,
          nodeId: n.id,
          bgColor: color.bg,
          borderColor: color.border,
        },
      })
    }
    for (const e of data.edges) {
      allElements.push({
        data: {
          id: `${e.source}-${e.target}`,
          source: e.source,
          target: e.target,
          relation: e.relation,
        },
      })
    }

    renderAll()
  } catch { /* silent */ }
}

// ── 渲染 ──
function renderAll() {
  if (!cy) return

  cy.elements().remove()
  cy.add(allElements)

  applyLayout()
}

function applyLayout() {
  if (!cy) return

  // 清除 center class
  cy.nodes().removeClass('center')

  const centerKey = centerType.value && centerId.value ? `${centerType.value}:${centerId.value}` : ''

  // 設定中心節點樣式
  if (centerKey) {
    const centerNode = cy.getElementById(centerKey)
    if (centerNode.length) {
      centerNode.addClass('center')
    }
  }

  const opts: any = {
    animate: true,
    animationDuration: 400,
    fit: true,
    padding: 40,
  }

  if (layoutName.value === 'breadthfirst') {
    cy.layout({
      name: 'breadthfirst',
      directed: true,
      roots: centerKey ? [centerKey] : undefined,
      spacingFactor: 1.2,
      avoidOverlap: true,
      ...opts,
    } as any).run()
  } else if (layoutName.value === 'cose') {
    cy.layout({
      name: 'cose',
      nodeRepulsion: () => 8000,
      idealEdgeLength: () => 120,
      gravity: 0.3,
      ...opts,
    } as any).run()
  } else {
    cy.layout({
      name: 'circle',
      ...opts,
    } as any).run()
  }
}

function toggleLayout() {
  if (layoutName.value === 'cose') layoutName.value = 'breadthfirst'
  else if (layoutName.value === 'breadthfirst') layoutName.value = 'circle'
  else layoutName.value = 'cose'
  applyLayout()
}

// ── Watch ──
watch(centerType, () => {
  if (centerType.value && currentEntities.value.length) {
    centerId.value = currentEntities.value[0]!.id
  } else {
    centerId.value = 0
    applyLayout()
  }
})

watch(centerId, () => {
  applyLayout()
})

onMounted(async () => {
  await nextTick()
  initCytoscape()
  await loadAll()
})

onUnmounted(() => {
  if (cy) {
    cy.destroy()
    cy = null
  }
})
</script>
