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

      <!-- Legend（可切換顯示/隱藏） -->
      <div class="absolute bottom-3 left-3 flex gap-1 text-[10px] bg-slate-800/80 px-2 py-1.5 rounded-lg">
        <button
          v-for="t in legendTypes" :key="t.type"
          @click="toggleType(t.type)"
          class="flex items-center gap-1 px-1.5 py-0.5 rounded transition-colors"
          :class="hiddenTypes.has(t.type) ? 'opacity-30 line-through' : 'hover:bg-slate-700'"
        >
          <span class="w-2.5 h-2.5 rounded-full shrink-0" :style="{ backgroundColor: t.color }"></span>
          <span :class="hiddenTypes.has(t.type) ? 'text-slate-600' : 'text-slate-400'">{{ t.label }}</span>
        </button>
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

// ── 圖例類型 ──
const legendTypes = [
  { type: 'domain', label: '網域', color: '#3b82f6' },
  { type: 'room', label: '空間', color: '#ea580c' },
  { type: 'project', label: '專案', color: '#7c3aed' },
  { type: 'member', label: '成員', color: '#059669' },
  { type: 'user', label: '用戶', color: '#d97706' },
  { type: 'account', label: '帳號', color: '#db2777' },
]
const hiddenTypes = ref(new Set<string>())

function toggleType(type: string) {
  if (hiddenTypes.value.has(type)) {
    hiddenTypes.value.delete(type)
  } else {
    hiddenTypes.value.add(type)
  }
  // 切換 Cytoscape 節點的顯示/隱藏
  if (cy) {
    cy.nodes().forEach((n) => {
      if (hiddenTypes.value.has(n.data('nodeType'))) {
        n.style('display', 'none')
      } else {
        n.style('display', 'element')
      }
    })
    // 邊：兩端有一端隱藏就隱藏
    cy.edges().forEach((e) => {
      const st = e.source().data('nodeType')
      const tt = e.target().data('nodeType')
      if (hiddenTypes.value.has(st) || hiddenTypes.value.has(tt)) {
        e.style('display', 'none')
      } else {
        e.style('display', 'element')
      }
    })
  }
}

// ── 層級定義（breadthfirst 排列用）──
const tierMap: Record<string, number> = {
  domain: 1, room: 2, project: 3, member: 4, user: 5, account: 5,
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

  // 拖拽時子節點跟著走
  let dragDescendants: cytoscape.NodeCollection | null = null
  let dragStartPositions: Map<string, { x: number; y: number }> = new Map()

  cy.on('grab', 'node', (evt) => {
    const node = evt.target
    // BFS 找所有下游節點（outgoing edges 的 target）
    const descendants = cy!.collection()
    const queue = [node]
    const visited = new Set([node.id()])
    while (queue.length) {
      const current = queue.shift()!
      current.outgoers('node').forEach((child: cytoscape.NodeSingular) => {
        if (!visited.has(child.id())) {
          visited.add(child.id())
          descendants.merge(child)
          queue.push(child)
        }
      })
    }
    dragDescendants = descendants
    // 記錄所有下游節點的起始位置
    dragStartPositions.clear()
    dragStartPositions.set(node.id(), { ...node.position() })
    descendants.forEach((n: cytoscape.NodeSingular) => {
      dragStartPositions.set(n.id(), { ...n.position() })
    })
  })

  cy.on('drag', 'node', (evt) => {
    if (!dragDescendants || !dragDescendants.length) return
    const node = evt.target
    const startPos = dragStartPositions.get(node.id())
    if (!startPos) return
    const dx = node.position('x') - startPos.x
    const dy = node.position('y') - startPos.y
    dragDescendants.forEach((n: cytoscape.NodeSingular) => {
      const sp = dragStartPositions.get(n.id())
      if (sp) {
        n.position({ x: sp.x + dx, y: sp.y + dy })
      }
    })
  })

  cy.on('free', 'node', () => {
    dragDescendants = null
    dragStartPositions.clear()
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
          tier: tierMap[n.type] || 5,
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
