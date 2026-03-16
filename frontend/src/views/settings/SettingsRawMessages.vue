<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { Inbox, Users, Building2, RefreshCw, MessageCircle, Mail, ChevronRight } from 'lucide-vue-next'
import { config } from '../../config'
import { authHeaders } from '../../utils/authFetch'
import { useAegisStore } from '../../stores/aegis'

const store = useAegisStore()
const API = config.apiUrl

// Tabs
type Tab = 'messages' | 'emails' | 'groups' | 'users'
const activeTab = ref<Tab>('messages')

// ==========================================
// 訊息列表 (RawMessage)
// ==========================================
interface RawMsg {
  id: number
  platform: string
  source_type: string
  source_id: string
  user_id: string
  user_name: string
  event_type: string
  content_type: string
  content: string
  is_processed: boolean
  created_at: string
}

const messages = ref<RawMsg[]>([])
const messagesLoading = ref(false)
const filterSourceId = ref('')
const messagesOffset = ref(0)
const messagesLimit = 50

// ==========================================
// Email 列表 (EmailMessage)
// ==========================================
interface EmailMsg {
  id: number
  from_address: string
  from_name: string
  subject: string
  date: string | null
  body_text: string
  category: string
  urgency: string
  summary: string
  suggested_action: string
  is_processed: boolean
  project_id: number | null
  created_at: string
}

const emails = ref<EmailMsg[]>([])
const emailsLoading = ref(false)
const emailFilter = ref<string>('')  // category filter
const emailsOffset = ref(0)
const emailsLimit = 50

// ==========================================
// 群組列表
// ==========================================
interface RawGroup {
  id: number
  platform: string
  group_id: string
  group_name: string
  picture_url: string
  member_count: number
  project_id: number | null
  updated_at: string
}

const groups = ref<RawGroup[]>([])
const groupsLoading = ref(false)

interface GroupStat {
  source_id: string
  group_name: string
  project_id: number | null
  member_count: number
  message_count: number
  last_message_at: string | null
}

const groupStats = ref<GroupStat[]>([])

// ==========================================
// 用戶列表
// ==========================================
interface RawUser {
  id: number
  platform: string
  user_id: string
  display_name: string
  picture_url: string
  status_message: string
  updated_at: string
}

const users = ref<RawUser[]>([])
const usersLoading = ref(false)

// 專案列表（for 下拉）
interface ProjectOption { id: number; name: string }
const projects = ref<ProjectOption[]>([])

// ==========================================
// Fetch functions
// ==========================================

async function fetchMessages() {
  messagesLoading.value = true
  try {
    const params = new URLSearchParams({ limit: String(messagesLimit), offset: String(messagesOffset.value) })
    if (filterSourceId.value) params.set('source_id', filterSourceId.value)
    const res = await fetch(`${API}/api/v1/raw-messages/?${params}`)
    messages.value = await res.json()
  } catch { messages.value = [] }
  finally { messagesLoading.value = false }
}

async function fetchEmails() {
  emailsLoading.value = true
  try {
    const params = new URLSearchParams({ limit: String(emailsLimit), offset: String(emailsOffset.value) })
    if (emailFilter.value) params.set('category', emailFilter.value)
    const res = await fetch(`${API}/api/v1/emails/?${params}`)
    emails.value = await res.json()
  } catch { emails.value = [] }
  finally { emailsLoading.value = false }
}

async function fetchGroups() {
  groupsLoading.value = true
  try {
    const [gRes, sRes] = await Promise.all([
      fetch(`${API}/api/v1/raw-messages/groups/`),
      fetch(`${API}/api/v1/raw-messages/stats`),
    ])
    groups.value = await gRes.json()
    groupStats.value = await sRes.json()
  } catch { groups.value = []; groupStats.value = [] }
  finally { groupsLoading.value = false }
}

async function fetchUsers() {
  usersLoading.value = true
  try {
    const res = await fetch(`${API}/api/v1/raw-messages/users/`)
    users.value = await res.json()
  } catch { users.value = [] }
  finally { usersLoading.value = false }
}

async function fetchProjects() {
  try {
    const res = await fetch(`${API}/api/v1/projects/`)
    const data = await res.json()
    projects.value = data.map((p: any) => ({ id: p.id, name: p.name }))
  } catch { projects.value = [] }
}

// ==========================================
// Actions
// ==========================================

async function updateGroupProject(groupId: number, projectId: number | null) {
  try {
    const res = await fetch(`${API}/api/v1/raw-messages/groups/${groupId}`, {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ project_id: projectId }),
    })
    if (res.ok) {
      store.addToast('群組專案已更新', 'success')
      await fetchGroups()
    }
  } catch {
    store.addToast('更新失敗', 'error')
  }
}

function viewGroupMessages(sourceId: string) {
  filterSourceId.value = sourceId
  messagesOffset.value = 0
  activeTab.value = 'messages'
  fetchMessages()
}

// 分頁 — messages
function msgNextPage() { messagesOffset.value += messagesLimit; fetchMessages() }
function msgPrevPage() { messagesOffset.value = Math.max(0, messagesOffset.value - messagesLimit); fetchMessages() }

// 分頁 — emails
function emailNextPage() { emailsOffset.value += emailsLimit; fetchEmails() }
function emailPrevPage() { emailsOffset.value = Math.max(0, emailsOffset.value - emailsLimit); fetchEmails() }

// ==========================================
// Helpers
// ==========================================

function formatTime(iso: string | null) {
  if (!iso) return ''
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
  return d.toLocaleString('zh-TW', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

const statsMap = computed(() => {
  const m: Record<string, GroupStat> = {}
  for (const s of groupStats.value) m[s.source_id] = s
  return m
})

const projectMap = computed(() => {
  const m: Record<number, string> = {}
  for (const p of projects.value) m[p.id] = p.name
  return m
})

// 分類 badge 顏色
const categoryStyles: Record<string, string> = {
  actionable: 'text-red-400 bg-red-500/10',
  informational: 'text-blue-400 bg-blue-500/10',
  spam: 'text-slate-500 bg-slate-500/10',
  newsletter: 'text-purple-400 bg-purple-500/10',
  unclassified: 'text-amber-400 bg-amber-500/10',
}

const urgencyStyles: Record<string, string> = {
  high: 'text-red-400',
  medium: 'text-amber-400',
  low: 'text-slate-500',
}

// Email 展開
const expandedEmailId = ref<number | null>(null)
function toggleEmail(id: number) {
  expandedEmailId.value = expandedEmailId.value === id ? null : id
}

// Tab 切換時載入
watch(activeTab, (tab) => {
  if (tab === 'messages') fetchMessages()
  else if (tab === 'emails') fetchEmails()
  else if (tab === 'groups') fetchGroups()
  else if (tab === 'users') fetchUsers()
})

onMounted(() => {
  fetchMessages()
  fetchProjects()
})
</script>

<template>
  <div class="max-w-3xl space-y-4">
    <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
      <!-- Header -->
      <div class="px-6 py-4 border-b border-slate-700/50">
        <div class="flex items-center gap-2">
          <Inbox class="w-4 h-4 text-green-400" />
          <h2 class="text-sm font-semibold text-slate-200">收件匣</h2>
        </div>
        <p class="text-[11px] text-slate-500 mt-1">多通道訊息收集 — LINE 群組、Email 等</p>
      </div>

      <!-- Tabs -->
      <div class="flex border-b border-slate-700/50 overflow-x-auto">
        <button
          v-for="tab in ([
            { key: 'messages' as Tab, label: '訊息', icon: MessageCircle },
            { key: 'emails' as Tab, label: 'Email', icon: Mail },
            { key: 'groups' as Tab, label: '群組', icon: Building2 },
            { key: 'users' as Tab, label: '用戶', icon: Users },
          ])"
          :key="tab.key"
          @click="activeTab = tab.key"
          class="flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium transition-colors border-b-2 whitespace-nowrap"
          :class="activeTab === tab.key
            ? 'border-green-400 text-green-400'
            : 'border-transparent text-slate-500 hover:text-slate-300'"
        >
          <component :is="tab.icon" class="w-3.5 h-3.5" />
          {{ tab.label }}
        </button>
      </div>

      <!-- ==========================================
           Messages Tab
           ========================================== -->
      <div v-if="activeTab === 'messages'" class="p-4">
        <div class="flex items-center gap-2 mb-3">
          <div v-if="filterSourceId" class="flex items-center gap-1.5 bg-green-500/10 border border-green-500/20 rounded-lg px-2.5 py-1">
            <span class="text-[11px] text-green-400">群組: {{ filterSourceId.slice(0, 12) }}...</span>
            <button @click="filterSourceId = ''; fetchMessages()" class="text-green-400 hover:text-green-300 text-xs">✕</button>
          </div>
          <div class="flex-1"></div>
          <button @click="fetchMessages" class="p-1.5 hover:bg-slate-700 rounded-lg transition-colors">
            <RefreshCw class="w-3.5 h-3.5 text-slate-400" :class="{ 'animate-spin': messagesLoading }" />
          </button>
        </div>

        <div v-if="messagesLoading" class="text-sm text-slate-500 text-center py-8">載入中...</div>
        <div v-else-if="messages.length === 0" class="text-sm text-slate-500 text-center py-8">尚無訊息</div>
        <div v-else class="space-y-1">
          <div
            v-for="msg in messages"
            :key="msg.id"
            class="flex items-start gap-3 px-3 py-2 rounded-lg hover:bg-slate-800/50 transition-colors"
          >
            <div class="w-8 h-8 rounded-full bg-slate-700 flex items-center justify-center text-xs text-slate-400 shrink-0 mt-0.5">
              {{ (msg.user_name || msg.user_id || '?').charAt(0) }}
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-baseline gap-2">
                <span class="text-xs font-medium text-slate-300">{{ msg.user_name || msg.user_id.slice(0, 10) }}</span>
                <span class="text-[10px] text-slate-600">{{ formatTime(msg.created_at) }}</span>
                <span v-if="msg.content_type !== 'text'" class="text-[10px] text-amber-500/70 bg-amber-500/10 px-1 rounded">{{ msg.content_type }}</span>
              </div>
              <p class="text-sm text-slate-400 break-words">{{ msg.content || `[${msg.content_type}]` }}</p>
            </div>
          </div>
        </div>

        <div v-if="messages.length > 0" class="flex items-center justify-between pt-3 border-t border-slate-700/50 mt-3">
          <button @click="msgPrevPage" :disabled="messagesOffset === 0" class="text-xs text-slate-400 hover:text-slate-200 disabled:opacity-30 disabled:cursor-not-allowed">← 上一頁</button>
          <span class="text-[10px] text-slate-600">{{ messagesOffset + 1 }} - {{ messagesOffset + messages.length }}</span>
          <button @click="msgNextPage" :disabled="messages.length < messagesLimit" class="text-xs text-slate-400 hover:text-slate-200 disabled:opacity-30 disabled:cursor-not-allowed">下一頁 →</button>
        </div>
      </div>

      <!-- ==========================================
           Email Tab
           ========================================== -->
      <div v-if="activeTab === 'emails'" class="p-4">
        <!-- Filter bar -->
        <div class="flex items-center gap-2 mb-3">
          <select
            v-model="emailFilter"
            @change="emailsOffset = 0; fetchEmails()"
            class="bg-slate-800 border border-slate-600 rounded-lg px-2 py-1.5 text-xs text-slate-200 focus:ring-2 focus:ring-green-500 outline-none"
          >
            <option value="">全部分類</option>
            <option value="actionable">需處理</option>
            <option value="informational">資訊</option>
            <option value="newsletter">電子報</option>
            <option value="spam">垃圾</option>
            <option value="unclassified">未分類</option>
          </select>
          <div class="flex-1"></div>
          <button @click="fetchEmails" class="p-1.5 hover:bg-slate-700 rounded-lg transition-colors">
            <RefreshCw class="w-3.5 h-3.5 text-slate-400" :class="{ 'animate-spin': emailsLoading }" />
          </button>
        </div>

        <div v-if="emailsLoading" class="text-sm text-slate-500 text-center py-8">載入中...</div>
        <div v-else-if="emails.length === 0" class="text-sm text-slate-500 text-center py-8">尚無 Email</div>
        <div v-else class="space-y-1">
          <div
            v-for="em in emails"
            :key="em.id"
            class="rounded-lg hover:bg-slate-800/50 transition-colors cursor-pointer"
            @click="toggleEmail(em.id)"
          >
            <!-- Email 標題列 -->
            <div class="flex items-center gap-3 px-3 py-2.5">
              <!-- 緊急度指示 -->
              <div class="w-1.5 h-1.5 rounded-full shrink-0" :class="em.urgency === 'high' ? 'bg-red-400' : em.urgency === 'medium' ? 'bg-amber-400' : 'bg-slate-600'"></div>
              <!-- 寄件人 -->
              <div class="w-28 shrink-0">
                <div class="text-xs font-medium text-slate-300 truncate">{{ em.from_name || em.from_address }}</div>
              </div>
              <!-- 主旨 -->
              <div class="flex-1 min-w-0">
                <div class="text-xs text-slate-400 truncate">{{ em.subject }}</div>
              </div>
              <!-- 分類 badge -->
              <span :class="['text-[10px] px-1.5 py-0.5 rounded', categoryStyles[em.category] || categoryStyles.unclassified]">
                {{ em.category === 'actionable' ? '需處理' : em.category === 'informational' ? '資訊' : em.category === 'newsletter' ? '電子報' : em.category === 'spam' ? '垃圾' : '未分類' }}
              </span>
              <!-- 專案 -->
              <span v-if="em.project_id && projectMap[em.project_id]" class="text-[10px] text-slate-500">{{ projectMap[em.project_id] }}</span>
              <!-- 時間 -->
              <span class="text-[10px] text-slate-600 shrink-0 w-16 text-right">{{ formatTime(em.date || em.created_at) }}</span>
              <ChevronRight class="w-3 h-3 text-slate-600 shrink-0 transition-transform" :class="{ 'rotate-90': expandedEmailId === em.id }" />
            </div>

            <!-- Email 展開詳情 -->
            <div v-if="expandedEmailId === em.id" class="px-3 pb-3 border-t border-slate-700/30 mt-1 pt-2 space-y-2">
              <!-- AI 摘要 -->
              <div v-if="em.summary" class="bg-slate-900/50 rounded-lg px-3 py-2">
                <div class="text-[10px] text-slate-500 mb-1">AI 摘要</div>
                <p class="text-xs text-slate-300">{{ em.summary }}</p>
              </div>
              <!-- 建議動作 -->
              <div v-if="em.suggested_action" class="bg-slate-900/50 rounded-lg px-3 py-2">
                <div class="text-[10px] text-slate-500 mb-1">建議動作</div>
                <p class="text-xs text-slate-300">{{ em.suggested_action }}</p>
              </div>
              <!-- 原文預覽 -->
              <div class="bg-slate-900/50 rounded-lg px-3 py-2">
                <div class="text-[10px] text-slate-500 mb-1">內文預覽</div>
                <p class="text-xs text-slate-400 whitespace-pre-wrap line-clamp-6">{{ em.body_text.slice(0, 500) }}</p>
              </div>
              <!-- Meta -->
              <div class="flex items-center gap-4 text-[10px] text-slate-600">
                <span>From: {{ em.from_address }}</span>
                <span :class="urgencyStyles[em.urgency]">緊急度: {{ em.urgency }}</span>
                <span v-if="!em.is_processed" class="text-amber-400">未分類</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Pagination -->
        <div v-if="emails.length > 0" class="flex items-center justify-between pt-3 border-t border-slate-700/50 mt-3">
          <button @click="emailPrevPage" :disabled="emailsOffset === 0" class="text-xs text-slate-400 hover:text-slate-200 disabled:opacity-30 disabled:cursor-not-allowed">← 上一頁</button>
          <span class="text-[10px] text-slate-600">{{ emailsOffset + 1 }} - {{ emailsOffset + emails.length }}</span>
          <button @click="emailNextPage" :disabled="emails.length < emailsLimit" class="text-xs text-slate-400 hover:text-slate-200 disabled:opacity-30 disabled:cursor-not-allowed">下一頁 →</button>
        </div>
      </div>

      <!-- ==========================================
           Groups Tab
           ========================================== -->
      <div v-if="activeTab === 'groups'" class="p-4">
        <div class="flex items-center justify-between mb-3">
          <span class="text-xs text-slate-500">{{ groups.length }} 個群組</span>
          <button @click="fetchGroups" class="p-1.5 hover:bg-slate-700 rounded-lg transition-colors">
            <RefreshCw class="w-3.5 h-3.5 text-slate-400" :class="{ 'animate-spin': groupsLoading }" />
          </button>
        </div>

        <div v-if="groupsLoading" class="text-sm text-slate-500 text-center py-8">載入中...</div>
        <div v-else-if="groups.length === 0" class="text-sm text-slate-500 text-center py-8">尚無群組（等待 LINE 訊息進來）</div>
        <div v-else class="space-y-2">
          <div v-for="g in groups" :key="g.id" class="bg-slate-900 rounded-xl border border-slate-700/50 p-4">
            <div class="flex items-center gap-3">
              <div class="w-10 h-10 rounded-lg bg-slate-700 flex items-center justify-center shrink-0 overflow-hidden">
                <img v-if="g.picture_url" :src="g.picture_url" class="w-full h-full object-cover" />
                <Building2 v-else class="w-5 h-5 text-slate-500" />
              </div>
              <div class="flex-1 min-w-0">
                <div class="text-sm font-medium text-slate-200">{{ g.group_name || g.group_id.slice(0, 16) + '...' }}</div>
                <div class="flex items-center gap-3 text-[10px] text-slate-500 mt-0.5">
                  <span>{{ g.member_count }} 人</span>
                  <span v-if="statsMap[g.group_id]">{{ statsMap[g.group_id]?.message_count }} 則訊息</span>
                  <span v-if="statsMap[g.group_id]?.last_message_at">最後: {{ formatTime(statsMap[g.group_id]?.last_message_at ?? '') }}</span>
                </div>
              </div>
              <button @click="viewGroupMessages(g.group_id)" class="text-[11px] text-green-400 hover:text-green-300 px-2 py-1 rounded-lg hover:bg-green-500/10 transition-colors">查看訊息</button>
            </div>
            <div class="mt-3 flex items-center gap-2">
              <span class="text-[11px] text-slate-500 shrink-0">所屬專案:</span>
              <select
                :value="g.project_id ?? ''"
                @change="updateGroupProject(g.id, ($event.target as HTMLSelectElement).value ? Number(($event.target as HTMLSelectElement).value) : null)"
                class="flex-1 bg-slate-800 border border-slate-600 rounded-lg px-2 py-1.5 text-xs text-slate-200 focus:ring-2 focus:ring-green-500 outline-none"
              >
                <option value="">未指派</option>
                <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
              </select>
            </div>
          </div>
        </div>
      </div>

      <!-- ==========================================
           Users Tab
           ========================================== -->
      <div v-if="activeTab === 'users'" class="p-4">
        <div class="flex items-center justify-between mb-3">
          <span class="text-xs text-slate-500">{{ users.length }} 個用戶</span>
          <button @click="fetchUsers" class="p-1.5 hover:bg-slate-700 rounded-lg transition-colors">
            <RefreshCw class="w-3.5 h-3.5 text-slate-400" :class="{ 'animate-spin': usersLoading }" />
          </button>
        </div>

        <div v-if="usersLoading" class="text-sm text-slate-500 text-center py-8">載入中...</div>
        <div v-else-if="users.length === 0" class="text-sm text-slate-500 text-center py-8">尚無用戶</div>
        <div v-else class="space-y-1">
          <div v-for="u in users" :key="u.id" class="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-slate-800/50 transition-colors">
            <div class="w-8 h-8 rounded-full bg-slate-700 shrink-0 overflow-hidden">
              <img v-if="u.picture_url" :src="u.picture_url" class="w-full h-full object-cover" />
              <div v-else class="w-full h-full flex items-center justify-center text-xs text-slate-400">{{ (u.display_name || '?').charAt(0) }}</div>
            </div>
            <div class="flex-1 min-w-0">
              <div class="text-sm text-slate-200">{{ u.display_name || '(未知)' }}</div>
              <div class="text-[10px] text-slate-500">{{ u.platform }} · {{ u.user_id.slice(0, 16) }}...</div>
            </div>
            <div class="text-[10px] text-slate-600">{{ formatTime(u.updated_at) }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
