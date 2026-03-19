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
    <div v-if="activeTab === 'overview'" class="flex-1 overflow-auto p-4 space-y-3">
      <div v-if="!overview" class="text-slate-600 text-sm">載入中...</div>
      <template v-else>
        <!-- 三環境比較表 -->
        <div class="space-y-2">
          <div
            v-for="env in envList"
            :key="env.key"
            class="flex items-center gap-3 px-3 py-2.5 rounded-lg border"
            :class="env.key === 'dev' ? 'bg-purple-500/5 border-purple-500/20' :
                    env.key === 'runtime' ? 'bg-emerald-500/5 border-emerald-500/20' :
                    'bg-blue-500/5 border-blue-500/20'"
          >
            <!-- 標籤 -->
            <div class="w-14 shrink-0">
              <span class="text-[10px] font-bold uppercase tracking-wider"
                :class="env.key === 'dev' ? 'text-purple-400' :
                        env.key === 'runtime' ? 'text-emerald-400' : 'text-blue-400'"
              >{{ env.data.label }}</span>
            </div>

            <!-- Commit info -->
            <template v-if="env.data.exists">
              <span class="text-xs font-mono text-slate-400">{{ env.data.sha }}</span>
              <span class="text-xs text-slate-300 truncate flex-1">{{ env.data.message }}</span>
              <span class="text-[10px] text-slate-600 shrink-0">{{ env.data.date ? formatDate(env.data.date) : '' }}</span>
              <button
                v-if="env.key === 'origin'"
                class="text-[10px] px-1.5 py-0.5 rounded border transition-colors shrink-0"
                :class="fetching
                  ? 'text-slate-600 border-slate-700 cursor-wait'
                  : 'text-blue-400 border-blue-500/30 hover:text-blue-300 hover:border-blue-400/50'"
                :disabled="fetching"
                @click="doFetch"
              >
                {{ fetching ? '...' : '⟳' }}
              </button>
            </template>
            <span v-else class="text-xs text-slate-600">不可用</span>
          </div>
        </div>

        <!-- 同步狀態 -->
        <div class="px-3 py-2 rounded-lg" :class="overview.all_synced ? 'bg-emerald-500/5 border border-emerald-500/20' : 'bg-amber-500/5 border border-amber-500/20'">
          <div v-if="overview.all_synced" class="text-xs text-emerald-400 flex items-center gap-2">
            <span>✓</span> 三個環境版本一致
          </div>
          <div v-else class="space-y-1">
            <div v-if="overview.dev_ahead_of_runtime > 0" class="text-xs text-amber-400">
              開發版 領先 運行版 {{ overview.dev_ahead_of_runtime }} 個 commit
            </div>
            <div v-if="overview.dev_ahead_of_origin > 0" class="text-xs text-purple-400">
              開發版 領先 遠端 {{ overview.dev_ahead_of_origin }} 個 commit（未 push）
            </div>
            <div v-if="overview.runtime_ahead_of_origin > 0" class="text-xs text-emerald-400">
              運行版 領先 遠端 {{ overview.runtime_ahead_of_origin }} 個 commit
            </div>
            <div v-if="overview.dev_ahead_of_runtime === 0 && overview.dev_ahead_of_origin === 0 && overview.runtime_ahead_of_origin === 0 && !overview.all_synced" class="text-xs text-amber-400">
              版本不一致（可能需要 fetch 更新）
            </div>
          </div>
        </div>

        <!-- 遠端 URL -->
        <div v-if="overview.origin?.url" class="text-[10px] text-slate-600 truncate">
          {{ overview.origin.url }}
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
        <!-- Branch -->
        <div class="flex items-center gap-2 text-sm">
          <GitBranch class="w-4 h-4 text-purple-400" />
          <span class="text-slate-300 font-mono">{{ status.branch }}</span>
          <span v-if="status.ahead > 0" class="text-xs text-emerald-400">↑{{ status.ahead }}</span>
          <span v-if="status.behind > 0" class="text-xs text-amber-400">↓{{ status.behind }}</span>
          <span v-if="status.is_clean && !status.behind" class="ml-auto text-xs text-emerald-500">Clean</span>
          <button
            class="ml-auto text-xs px-2 py-0.5 rounded border transition-colors"
            :class="fetching
              ? 'text-slate-600 border-slate-700 cursor-wait'
              : 'text-slate-400 border-slate-600 hover:text-slate-200 hover:border-slate-500'"
            :disabled="fetching"
            @click="doFetch"
          >
            {{ fetching ? '檢查中...' : '⟳ Fetch' }}
          </button>
        </div>

        <!-- Pull 按鈕 -->
        <div v-if="status.behind > 0" class="flex items-center gap-2 px-3 py-2 rounded bg-amber-500/10 border border-amber-500/20">
          <span class="text-xs text-amber-400 flex-1">
            遠端有 {{ status.behind }} 筆新 commit 可拉取
          </span>
          <button
            class="text-xs px-3 py-1 rounded font-medium transition-colors"
            :class="pulling
              ? 'bg-slate-700 text-slate-500 cursor-wait'
              : 'bg-amber-500 text-slate-900 hover:bg-amber-400'"
            :disabled="pulling"
            @click="doPullTask"
          >
            {{ pulling ? '建立中...' : '↓ AI Pull' }}
          </button>
        </div>

        <!-- Modified -->
        <div v-if="status.modified.length > 0">
          <p class="text-[10px] text-slate-600 uppercase tracking-wider mb-1">Modified</p>
          <div v-for="f in status.modified" :key="f" class="flex items-center gap-2 py-0.5 text-xs">
            <span class="w-1.5 h-1.5 rounded-full bg-amber-400" />
            <button class="text-slate-400 hover:text-slate-200 font-mono truncate" @click="viewDiff(f)">{{ f }}</button>
          </div>
        </div>

        <!-- Staged -->
        <div v-if="status.staged.length > 0">
          <p class="text-[10px] text-slate-600 uppercase tracking-wider mb-1">Staged</p>
          <div v-for="f in status.staged" :key="f" class="flex items-center gap-2 py-0.5 text-xs">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            <span class="text-slate-400 font-mono truncate">{{ f }}</span>
          </div>
        </div>

        <!-- Untracked -->
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

const props = defineProps<{
  projectId: number
}>()

const emit = defineEmits<{
  (e: 'pull-triggered', cardId: number): void
}>()

const API = config.apiUrl

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

const envList = computed(() => {
  if (!overview.value) return []
  const list = [
    { key: 'dev', data: overview.value.dev },
  ]
  if (overview.value.runtime?.exists) {
    list.push({ key: 'runtime', data: overview.value.runtime })
  }
  list.push({ key: 'origin', data: overview.value.origin })
  return list
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
    // 也更新 overview
    await loadOverview()
  } finally {
    fetching.value = false
  }
}

async function doPullTask() {
  pulling.value = true
  try {
    const res = await fetch(`${API}/api/v1/projects/${props.projectId}/git/pull-task`, { method: 'POST', headers: authHeaders() })
    if (res.ok) {
      const data = await res.json()
      if (data.ok) {
        emit('pull-triggered', data.card_id)
        alert(`已建立拉取任務 #${data.card_id}\nAI 將自動執行 git pull`)
      }
    }
  } finally {
    pulling.value = false
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
