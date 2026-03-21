<template>
  <div class="h-full flex flex-col overflow-hidden">
    <!-- Tabs -->
    <div class="flex border-b border-slate-700/50 bg-slate-800/50 shrink-0">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="px-4 py-2 text-xs font-medium transition-colors border-b-2"
        :class="activeTab === tab.id
          ? 'text-emerald-400 border-emerald-400'
          : 'text-slate-500 border-transparent hover:text-slate-300'"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
        <span v-if="tab.badge" class="ml-1 px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-400 text-[10px]">
          {{ tab.badge }}
        </span>
      </button>
    </div>

    <!-- Overview -->
    <div v-if="activeTab === 'overview'" class="flex-1 overflow-auto p-4 space-y-4">
      <div v-if="!overview" class="text-slate-600 text-sm">載入中...</div>
      <template v-else>

        <!-- 版本圖形 (三條線) — 最上方 -->
        <div v-if="graph" class="rounded-xl border border-slate-700/30 bg-slate-800/30 p-4 overflow-x-auto">
          <div class="flex items-center gap-2 mb-3">
            <span class="text-[10px] text-slate-600 uppercase tracking-wider font-bold">Commit Graph</span>
            <span v-if="overview.all_synced" class="text-[10px] text-emerald-400 ml-auto">✓ 同步</span>
          </div>
          <div class="relative" :style="{ minWidth: svgWidth + 'px' }">
            <svg :width="svgWidth" height="110" class="block">
              <!-- 左側標籤 -->
              <text x="24" y="24" fill="#c084fc" font-size="10" font-weight="bold" text-anchor="end">開發</text>
              <text v-if="hasRuntime" x="24" y="54" fill="#34d399" font-size="10" font-weight="bold" text-anchor="end">運行</text>
              <text x="24" :y="hasRuntime ? 84 : 54" fill="#60a5fa" font-size="10" font-weight="bold" text-anchor="end">遠端</text>

              <!-- 三條平行線 -->
              <line :x1="lineStart" y1="20" :x2="lineEnd" y2="20" stroke="#7c3aed" stroke-width="1.5" opacity="0.3" />
              <line v-if="hasRuntime" :x1="lineStart" y1="50" :x2="lineEnd" y2="50" stroke="#10b981" stroke-width="1.5" opacity="0.3" />
              <line :x1="lineStart" :y1="hasRuntime ? 80 : 50" :x2="lineEnd" :y2="hasRuntime ? 80 : 50" stroke="#3b82f6" stroke-width="1.5" opacity="0.3" />

              <!-- Commit 節點和連線 -->
              <g v-for="(c, i) in graph.commits" :key="c.sha_full">
                <!-- dev 線(y=20) -->
                <circle
                  :cx="nodeX(i)" cy="20" r="4"
                  :fill="Number(i) === graph.dev_idx ? '#c084fc' : '#334155'"
                  class="cursor-pointer"
                >
                  <title>{{ c.sha }} · {{ c.message }}{{ c.date ? ' · ' + formatDate(c.date) : '' }}</title>
                </circle>

                <!-- runtime 線(y=50) -->
                <template v-if="hasRuntime && Number(i) === graph.runtime_idx">
                  <line :x1="nodeX(i)" y1="20" :x2="nodeX(i)" y2="50" stroke="#34d399" stroke-width="1.5" opacity="0.5" />
                  <circle :cx="nodeX(i)" cy="50" r="5" fill="#10b981" stroke="#10b981" stroke-width="2" class="cursor-pointer">
                    <title>運行版 · {{ c.sha }} · {{ c.message }}</title>
                  </circle>
                </template>
                <circle v-else-if="hasRuntime && graph.runtime_idx >= 0 && Number(i) <= graph.runtime_idx"
                  :cx="nodeX(i)" cy="50" r="3" fill="#334155" class="cursor-pointer"
                >
                  <title>{{ c.sha }} · {{ c.message }}</title>
                </circle>

                <!-- origin 線 -->
                <template v-if="Number(i) === graph.origin_idx">
                  <line :x1="nodeX(i)" :y1="hasRuntime && Number(i) === graph.runtime_idx ? 50 : 20"
                    :x2="nodeX(i)" :y2="hasRuntime ? 80 : 50"
                    stroke="#3b82f6" stroke-width="1.5" opacity="0.5"
                  />
                  <circle :cx="nodeX(i)" :cy="hasRuntime ? 80 : 50" r="5" fill="#3b82f6" stroke="#3b82f6" stroke-width="2" class="cursor-pointer">
                    <title>遠端 · {{ c.sha }} · {{ c.message }}</title>
                  </circle>
                </template>
                <circle v-else-if="graph.origin_idx >= 0 && Number(i) <= graph.origin_idx"
                  :cx="nodeX(i)" :cy="hasRuntime ? 80 : 50" r="3" fill="#334155" class="cursor-pointer"
                >
                  <title>{{ c.sha }} · {{ c.message }}</title>
                </circle>
              </g>

              <!-- dev HEAD 大圓 -->
              <circle v-if="graph.dev_idx >= 0"
                :cx="nodeX(graph.dev_idx)" cy="20" r="6"
                fill="#c084fc" stroke="#e9d5ff" stroke-width="2" class="cursor-pointer"
              >
                <title>開發版 HEAD · {{ graph.commits[graph.dev_idx]?.sha }} · {{ graph.commits[graph.dev_idx]?.message }}</title>
              </circle>

              <!-- SHA 標籤 -->
              <text v-if="graph.dev_idx >= 0"
                :x="nodeX(graph.dev_idx)" y="106"
                text-anchor="middle" fill="#c084fc" font-size="8" font-family="monospace" opacity="0.7"
              >{{ graph.commits[graph.dev_idx]?.sha }}</text>
              <text v-if="graph.origin_idx >= 0 && graph.origin_idx !== graph.dev_idx"
                :x="nodeX(graph.origin_idx)" y="106"
                text-anchor="middle" fill="#60a5fa" font-size="8" font-family="monospace" opacity="0.7"
              >{{ graph.commits[graph.origin_idx]?.sha }}</text>
              <text v-if="hasRuntime && graph.runtime_idx >= 0 && graph.runtime_idx !== graph.origin_idx && graph.runtime_idx !== graph.dev_idx"
                :x="nodeX(graph.runtime_idx)" y="106"
                text-anchor="middle" fill="#34d399" font-size="8" font-family="monospace" opacity="0.7"
              >{{ graph.commits[graph.runtime_idx]?.sha }}</text>
            </svg>
          </div>
        </div>

        <!-- 開發版卡片 -->
        <div class="rounded-xl border border-purple-500/20 bg-purple-500/5 overflow-hidden">
          <div class="px-4 py-3 flex items-center gap-3">
            <div class="w-2 h-2 rounded-full bg-purple-400 shrink-0" />
            <span class="text-xs font-bold text-purple-400 uppercase tracking-wider">開發版</span>
            <span v-if="overview.dev?.exists" class="text-xs font-mono text-slate-400 ml-auto">{{ overview.dev.sha }}</span>
          </div>
          <div v-if="overview.dev?.exists" class="px-4 pb-3">
            <p class="text-sm text-slate-300 truncate">{{ overview.dev.message }}</p>
            <p class="text-[10px] text-slate-600 mt-1">{{ overview.dev.date ? formatDate(overview.dev.date) : '' }}</p>
          </div>
          <div class="px-4 py-2.5 border-t border-purple-500/10 flex gap-2 flex-wrap">
            <button
              class="text-[10px] px-3 py-1 rounded-md border font-medium transition-colors"
              :class="canDeploy ? 'bg-purple-500/10 text-purple-400 border-purple-500/30 hover:bg-purple-500/20' : 'bg-slate-800/50 text-slate-600 border-slate-700 cursor-not-allowed'"
              :disabled="!canDeploy || deploying"
              @click="deployToRuntime('dev')"
            >{{ deploying ? '...' : '→ 部署到運行環境' }}</button>
            <button
              class="text-[10px] px-3 py-1 rounded-md border font-medium transition-colors"
              :class="canPush ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/20' : 'bg-slate-800/50 text-slate-600 border-slate-700 cursor-not-allowed'"
              :disabled="!canPush || pushing"
              @click="doPush"
            >{{ pushing ? '...' : '↑ Push' }}</button>
            <button
              class="text-[10px] px-3 py-1 rounded-md border font-medium transition-colors"
              :class="canPull ? 'bg-amber-500/10 text-amber-400 border-amber-500/30 hover:bg-amber-500/20' : 'bg-slate-800/50 text-slate-600 border-slate-700 cursor-not-allowed'"
              :disabled="!canPull || pulling"
              @click="doPull"
            >{{ pulling ? '...' : '↓ Pull' }}</button>
          </div>
        </div>

        <!-- 運行版卡片 -->
        <div v-if="overview.runtime?.exists" class="rounded-xl border border-emerald-500/20 bg-emerald-500/5 overflow-hidden">
          <div class="px-4 py-3 flex items-center gap-3">
            <div class="w-2 h-2 rounded-full bg-emerald-400 shrink-0" />
            <span class="text-xs font-bold text-emerald-400 uppercase tracking-wider">運行版</span>
            <span class="text-xs font-mono text-slate-400 ml-auto">{{ overview.runtime.sha }}</span>
          </div>
          <div class="px-4 pb-3">
            <p class="text-sm text-slate-300 truncate">{{ overview.runtime.message }}</p>
            <p class="text-[10px] text-slate-600 mt-1">{{ overview.runtime.date ? formatDate(overview.runtime.date) : '' }}</p>
          </div>
        </div>

        <!-- 遠端卡片 -->
        <div class="rounded-xl border border-blue-500/20 bg-blue-500/5 overflow-hidden">
          <div class="px-4 py-3 flex items-center gap-3">
            <div class="w-2 h-2 rounded-full shrink-0" :class="fetching ? 'bg-blue-400 animate-pulse' : 'bg-blue-400'" />
            <span class="text-xs font-bold text-blue-400 uppercase tracking-wider">遠端</span>
            <span v-if="overview.origin?.exists" class="text-xs font-mono text-slate-400 ml-auto">{{ overview.origin.sha }}</span>
          </div>
          <div v-if="overview.origin?.exists" class="px-4 pb-3">
            <p class="text-sm text-slate-300 truncate">{{ overview.origin.message }}</p>
            <p class="text-[10px] text-slate-600 mt-1">{{ overview.origin.date ? formatDate(overview.origin.date) : '' }}</p>
            <p v-if="overview.origin.url" class="text-[10px] text-slate-600 mt-1 truncate">{{ overview.origin.url }}</p>
          </div>
          <div class="px-4 py-2.5 border-t border-blue-500/10 flex gap-2 flex-wrap">
            <button
              class="text-[10px] px-3 py-1 rounded-md border font-medium transition-colors"
              :class="canDeployOrigin ? 'bg-blue-500/10 text-blue-400 border-blue-500/30 hover:bg-blue-500/20' : 'bg-slate-800/50 text-slate-600 border-slate-700 cursor-not-allowed'"
              :disabled="!canDeployOrigin || deploying"
              @click="deployToRuntime('origin')"
            >{{ deploying ? '...' : '→ 更新運行環境' }}</button>
            <a v-if="repoUrl" :href="`${repoUrl}/issues/new`" target="_blank"
              class="text-[10px] px-3 py-1 rounded-md border font-medium transition-colors bg-slate-800/50 text-slate-400 border-slate-600 hover:text-slate-200 hover:border-slate-500"
            >💡 提出建議</a>
            <a v-if="repoUrl" :href="`${repoUrl}/compare/main...main?expand=1`" target="_blank"
              class="text-[10px] px-3 py-1 rounded-md border font-medium transition-colors bg-slate-800/50 text-slate-400 border-slate-600 hover:text-slate-200 hover:border-slate-500"
            >🔀 貢獻代碼</a>
          </div>
        </div>

      </template>
    </div>

    <!-- Status -->
    <div v-if="activeTab === 'status'" class="flex-1 overflow-auto p-4 space-y-4">
      <div v-if="!status" class="text-slate-600 text-sm">載入中...</div>
      <div v-else-if="!status.is_git" class="text-slate-600 text-sm text-center py-8">
        此專案不是 Git 儲存庫
      </div>
      <template v-else>
        <div class="flex items-center gap-2 text-sm">
          <GitBranch class="w-4 h-4 text-purple-400" />
          <span class="text-slate-300 font-mono">{{ status.branch }}</span>
          <span v-if="status.ahead > 0" class="text-xs text-emerald-400">↑{{ status.ahead }}</span>
          <span v-if="status.behind > 0" class="text-xs text-amber-400">↓{{ status.behind }}</span>
          <span v-if="status.is_clean && !status.behind" class="ml-auto text-xs text-emerald-500">Clean</span>
        </div>

        <div v-if="status.modified.length > 0">
          <p class="text-[10px] text-slate-600 uppercase tracking-wider mb-1">Modified</p>
          <div v-for="f in status.modified" :key="f" class="flex items-center gap-2 py-0.5 text-xs">
            <span class="w-1.5 h-1.5 rounded-full bg-amber-400" />
            <button class="text-slate-400 hover:text-slate-200 font-mono truncate" @click="viewDiff(f)">{{ f }}</button>
          </div>
        </div>

        <div v-if="status.staged.length > 0">
          <p class="text-[10px] text-slate-600 uppercase tracking-wider mb-1">Staged</p>
          <div v-for="f in status.staged" :key="f" class="flex items-center gap-2 py-0.5 text-xs">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            <span class="text-slate-400 font-mono truncate">{{ f }}</span>
          </div>
        </div>

        <div v-if="status.untracked.length > 0">
          <p class="text-[10px] text-slate-600 uppercase tracking-wider mb-1">Untracked</p>
          <div v-for="f in status.untracked" :key="f" class="flex items-center gap-2 py-0.5 text-xs">
            <span class="w-1.5 h-1.5 rounded-full bg-slate-600" />
            <span class="text-slate-500 font-mono truncate">{{ f }}</span>
          </div>
        </div>
      </template>
    </div>

    <!-- Log -->
    <div v-if="activeTab === 'log'" class="flex-1 overflow-auto">
      <div v-if="commits.length === 0" class="text-slate-600 text-sm text-center py-8">無 commit 記錄</div>
      <div v-for="c in commits" :key="c.sha_full" class="px-4 py-2.5 border-b border-slate-800 hover:bg-slate-800/50">
        <div class="flex items-center gap-2 mb-0.5">
          <span class="text-xs font-mono text-purple-400">{{ c.sha }}</span>
          <span class="text-[10px] text-slate-600 ml-auto">{{ formatDate(c.date) }}</span>
        </div>
        <p class="text-sm text-slate-300 truncate">{{ c.message }}</p>
        <p class="text-[10px] text-slate-600">{{ c.author }}</p>
      </div>
    </div>

    <!-- Diff -->
    <div v-if="activeTab === 'diff'" class="flex-1 overflow-auto">
      <div v-if="!diffContent && !diffLoading" class="text-slate-600 text-sm text-center py-8">
        點擊 modified 檔案查看 diff
      </div>
      <div v-if="diffLoading" class="text-slate-600 text-sm text-center py-8">載入中...</div>
      <div v-if="diffContent" class="font-mono text-xs leading-5">
        <div
          v-for="(line, i) in diffLines"
          :key="i"
          class="px-4 py-0"
          :class="diffLineClass(line)"
        >
          <pre class="whitespace-pre">{{ line }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { GitBranch } from 'lucide-vue-next'
import { config } from '../../config'
import { authHeaders } from '../../utils/authFetch'
import { useAegisStore } from '../../stores/aegis'

const props = defineProps<{
  projectId: number
}>()

const emit = defineEmits<{
  (e: 'pull-triggered', cardId: number): void
}>()

const API = config.apiUrl
const aegis = useAegisStore()

const tabs = computed(() => [
  { id: 'overview', label: 'Overview' },
  { id: 'status', label: 'Status', badge: changedCount.value || undefined },
  { id: 'log', label: 'Log' },
  { id: 'diff', label: 'Diff' },
])

const activeTab = ref('overview')
const overview = ref<any>(null)
const status = ref<any>(null)
const commits = ref<any[]>([])
const diffContent = ref('')
const diffLoading = ref(false)
const fetching = ref(false)
const pulling = ref(false)
const deploying = ref(false)
const pushing = ref(false)

// 按鈕狀態（始終可見，disabled 時灰色）
// Graph data
const graph = computed(() => overview.value?.graph || null)
const hasRuntime = computed(() => overview.value?.runtime?.exists)

const lineStart = 36
const nodeSpacing = 48
const nodeX = (i: number | string) => lineStart + Number(i) * nodeSpacing
const lineEnd = computed(() => graph.value ? lineStart + (graph.value.commits.length - 1) * nodeSpacing : 100)
const svgWidth = computed(() => graph.value ? lineStart + graph.value.commits.length * nodeSpacing + 20 : 120)

const canDeploy = computed(() => overview.value?.runtime?.exists && overview.value?.dev_ahead_of_runtime > 0)
const canPush = computed(() => overview.value?.dev_ahead_of_origin > 0)
const canPull = computed(() => status.value?.behind > 0)
const canDeployOrigin = computed(() => overview.value?.runtime?.exists && overview.value?.runtime_ahead_of_origin < 0)

// 遠端 repo URL（去掉 .git 後綴）
const repoUrl = computed(() => {
  const url = overview.value?.origin?.url || ''
  return url.replace(/\.git$/, '')
})

const changedCount = computed(() => {
  if (!status.value?.is_git) return 0
  return (status.value.modified?.length || 0) + (status.value.staged?.length || 0)
})

const diffLines = computed(() => diffContent.value.split('\n'))

function diffLineClass(line: string): string {
  if (line.startsWith('+') && !line.startsWith('+++')) return 'bg-emerald-900/20 text-emerald-400'
  if (line.startsWith('-') && !line.startsWith('---')) return 'bg-red-900/20 text-red-400'
  if (line.startsWith('@@')) return 'text-blue-400 bg-blue-900/10'
  if (line.startsWith('diff ')) return 'text-slate-500 bg-slate-800'
  return 'text-slate-400'
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  const now = Date.now()
  const diff = Math.floor((now - d.getTime()) / 1000)
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return d.toLocaleDateString('zh-TW', { month: 'short', day: 'numeric' })
}

async function loadOverview() {
  try {
    const res = await fetch(`${API}/api/v1/projects/${props.projectId}/git/overview`)
    if (res.ok) overview.value = await res.json()
  } catch { /* silent */ }
}

async function loadStatus() {
  const res = await fetch(`${API}/api/v1/projects/${props.projectId}/git/status`)
  if (res.ok) status.value = await res.json()
}

async function doFetch() {
  fetching.value = true
  try {
    const res = await fetch(`${API}/api/v1/projects/${props.projectId}/git/fetch`, { method: 'POST', headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      if (data.ok && status.value) {
        status.value.ahead = data.ahead
        status.value.behind = data.behind
      }
    }
    await loadOverview()
  } finally {
    fetching.value = false
  }
}

async function doPull() {
  if (!confirm('確定要從遠端拉取？')) return
  pulling.value = true
  try {
    const res = await fetch(`${API}/api/v1/projects/${props.projectId}/git/pull`, { method: 'POST', headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      if (data.ok) {
        await loadStatus()
        await loadOverview()
        loadLog()
      } else {
        aegis.addToast(`拉取失敗: ${data.error}`, 'error')
      }
    }
  } finally {
    pulling.value = false
  }
}

async function doPush() {
  if (!confirm('確定要推送到遠端倉庫？')) return
  pushing.value = true
  try {
    const res = await fetch(`${API}/api/v1/projects/${props.projectId}/git/push`, { method: 'POST', headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      if (data.ok) {
        await loadOverview()
      } else {
        aegis.addToast(`推送失敗: ${data.error}`, 'error')
      }
    }
  } finally {
    pushing.value = false
  }
}

async function deployToRuntime(source: 'dev' | 'origin') {
  if (!confirm('確定要部署到運行環境？')) return
  deploying.value = true
  try {
    const res = await fetch(`${API}/api/v1/projects/${props.projectId}/git/deploy-to-runtime`, {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ source }),
    })
    if (res.ok) {
      const data = await res.json()
      if (data.ok) {
        aegis.addToast(`部署任務已建立 #${data.card_id}`, 'success')
        emit('pull-triggered', data.card_id)
      } else {
        aegis.addToast(`部署失敗: ${data.error || '未知錯誤'}`, 'error')
      }
    }
  } finally {
    deploying.value = false
  }
}

async function loadLog() {
  const res = await fetch(`${API}/api/v1/projects/${props.projectId}/git/log?limit=30`)
  if (res.ok) {
    const data = await res.json()
    commits.value = data.commits || []
  }
}

async function viewDiff(file: string) {
  activeTab.value = 'diff'
  diffLoading.value = true
  try {
    const res = await fetch(`${API}/api/v1/projects/${props.projectId}/git/diff?file=${encodeURIComponent(file)}`)
    if (res.ok) {
      const data = await res.json()
      diffContent.value = data.diff || ''
    }
  } finally {
    diffLoading.value = false
  }
}

watch(() => props.projectId, () => {
  overview.value = null
  status.value = null
  commits.value = []
  diffContent.value = ''
  loadOverview()
  loadStatus()
  loadLog()
})

onMounted(async () => {
  await loadOverview()
  await loadStatus()
  loadLog()
  doFetch()
})
</script>
