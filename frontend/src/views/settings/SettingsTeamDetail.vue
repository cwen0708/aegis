<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft, Save, Loader2, Trash2, Upload, Sparkles,
  Plus, Edit3, BookOpen, ChevronDown, ChevronUp, Plug, AlertTriangle, Copy,
} from 'lucide-vue-next'
import { useAegisStore } from '../../stores/aegis'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { config } from '../../config'
import * as membersApi from '../../services/api/members'
import type { MemberAccount, AccountInfo, SkillInfo } from '../../services/api/members'
import { authHeaders } from '../../utils/authFetch'

const route = useRoute()
const router = useRouter()
const store = useAegisStore()
const API = config.apiUrl

const memberId = Number(route.params.id)
const loading = ref(true)
const saving = ref(false)

// ── Form ──
const form = ref({
  name: '',
  avatar: '',
  role: '',
  description: '',
  sprite_index: 0,
  portrait: '',
})

const avatarOptions = [
  '\u{1F916}', '\u{1F468}\u{200D}\u{1F4BC}', '\u{1F469}\u{200D}\u{1F4BB}', '\u{1F9EA}',
  '\u{1F4CA}', '\u{1F527}', '\u{1F3AF}', '\u{1F9E0}',
  '\u{1F98A}', '\u{1F431}', '\u{1F436}', '\u{1F989}',
  '\u{1F680}', '\u26A1', '\u{1F525}', '\u{1F48E}',
]

const modelOptions: Record<string, { value: string; label: string }[]> = {
  claude: [
    { value: 'opus', label: 'Opus (最強)' },
    { value: 'sonnet', label: 'Sonnet (平衡)' },
    { value: 'haiku', label: 'Haiku (快速)' },
  ],
  gemini: [
    { value: 'gemini-2.5-flash', label: '2.5 Flash (快速)' },
    { value: 'gemini-2.5-pro', label: '2.5 Pro' },
    { value: 'gemini-3-flash', label: '3 Flash (新)' },
    { value: 'gemini-3-pro', label: '3 Pro (新)' },
  ],
}

// ── Accounts ──
const memberAccounts = ref<MemberAccount[]>([])
const allAccounts = ref<AccountInfo[]>([])
const showBindDialog = ref(false)
const bindForm = ref({ account_id: 0, priority: 0, model: '' })
const showEditBindDialog = ref(false)
const editingBinding = ref<MemberAccount | null>(null)
const editBindForm = ref({ model: '', priority: 0 })

const bindAccountProvider = computed(() => {
  const acc = allAccounts.value.find(a => a.id === bindForm.value.account_id)
  return acc?.provider || ''
})
const bindModelOptions = computed(() => modelOptions[bindAccountProvider.value] || [])

const availableAccountsForBind = computed(() => {
  const boundIds = memberAccounts.value.map(a => a.account_id)
  return allAccounts.value.filter(a => !boundIds.includes(a.id))
})

watch(() => bindForm.value.account_id, (accId) => {
  const acc = allAccounts.value.find(a => a.id === accId)
  if (acc) {
    const opts = modelOptions[acc.provider]
    if (opts && opts.length > 0) {
      bindForm.value.model = opts[0]!.value
    }
  }
})

// ── Portrait ──
const uploadingPortrait = ref(false)
const generatingPortrait = ref(false)
const portraitInput = ref<HTMLInputElement | null>(null)
const generateInput = ref<HTMLInputElement | null>(null)

// ── Skills ──
const skills = ref<SkillInfo[]>([])
const loadingSkills = ref(false)
const expandedSkill = ref<string | null>(null)
const skillContent = ref('')
const loadingSkillContent = ref(false)
const editingSkill = ref(false)
const skillEditContent = ref('')
const savingSkill = ref(false)
const showNewSkillDialog = ref(false)
const newSkillForm = ref({ name: '', content: '' })

// ── Skill Copy ──
interface OtherMember {
  id: number
  name: string
  avatar: string
}
const allMembers = ref<OtherMember[]>([])
const showCopySkillMenu = ref<string | null>(null)
const copyingSkill = ref(false)

async function fetchAllMembers() {
  try {
    const res = await fetch(`${API}/api/v1/members?all=true`, { headers: authHeaders() })
    if (res.ok) allMembers.value = await res.json()
  } catch {}
}

function toggleCopyMenu(skillName: string) {
  showCopySkillMenu.value = showCopySkillMenu.value === skillName ? null : skillName
}

async function copySkillToMember(skillName: string, targetMemberId: number) {
  copyingSkill.value = true
  showCopySkillMenu.value = null
  try {
    // First fetch the skill content
    const contentRes = await fetch(`${API}/api/v1/members/${memberId}/skills/${skillName}`)
    if (!contentRes.ok) throw new Error('讀取技能失敗')
    const data = await contentRes.json()

    // Then create on target member
    const res = await fetch(`${API}/api/v1/members/${targetMemberId}/skills`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ name: skillName, content: data.content }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '複製失敗' }))
      throw new Error(err.detail)
    }
    const target = allMembers.value.find(m => m.id === targetMemberId)
    store.addToast(`技能已複製到 ${target?.name || '目標成員'}`, 'success')
  } catch (e: any) {
    store.addToast(e.message || '複製失敗', 'error')
  }
  copyingSkill.value = false
}

// ── MCP ──
const mcpContent = ref('')
const mcpEditing = ref(false)
const loadingMcp = ref(false)
const savingMcp = ref(false)
const mcpJsonError = ref('')

// ── Delete ──
const confirmDelete = ref(false)

// ═══════════════════════════════════════
// Fetch
// ═══════════════════════════════════════

async function fetchMember() {
  try {
    const members = await membersApi.listMembers(true)
    const m = members.find((m) => m.id === memberId)
    if (!m) {
      store.addToast('成員不存在', 'error')
      router.push('/settings/team')
      return
    }
    form.value = {
      name: m.name,
      avatar: m.avatar,
      role: m.role,
      description: m.description,
      sprite_index: m.sprite_index ?? 0,
      portrait: m.portrait ?? '',
    }
    memberAccounts.value = m.accounts || []
  } catch (e: any) {
    store.addToast(e.message || '載入失敗', 'error')
  }
}

async function fetchAccounts() {
  try {
    allAccounts.value = await membersApi.listAccounts()
  } catch {}
}

async function fetchSkills() {
  loadingSkills.value = true
  try {
    skills.value = await membersApi.listSkills(memberId)
  } catch {
    store.addToast('技能載入失敗', 'error')
  }
  loadingSkills.value = false
}

async function fetchMcp() {
  loadingMcp.value = true
  try {
    const data = await membersApi.getMcpConfig(memberId)
    mcpContent.value = JSON.stringify(data, null, 2)
  } catch {
    store.addToast('MCP 設定載入失敗', 'error')
  }
  loadingMcp.value = false
}

// ═══════════════════════════════════════
// Save member
// ═══════════════════════════════════════

async function saveMember() {
  if (!form.value.name.trim()) return
  saving.value = true
  try {
    await membersApi.updateMember(memberId, form.value)
    store.addToast('成員已更新', 'success')
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
  saving.value = false
}

// ═══════════════════════════════════════
// Portrait
// ═══════════════════════════════════════

async function handleUploadPortrait(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files?.length) return

  const file = input.files[0]!
  if (file.size > 10 * 1024 * 1024) {
    store.addToast(`檔案過大（${(file.size / 1024 / 1024).toFixed(1)}MB），上限 10MB`, 'error')
    return
  }

  uploadingPortrait.value = true
  try {
    const data = await membersApi.uploadPortrait(memberId, file)
    form.value.portrait = data.portrait
    store.addToast('立繪已上傳', 'success')
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
  uploadingPortrait.value = false
  input.value = ''
}

async function handleGeneratePortrait(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files?.length) return

  const file = input.files[0]!
  if (file.size > 10 * 1024 * 1024) {
    store.addToast(`檔案過大（${(file.size / 1024 / 1024).toFixed(1)}MB），上限 10MB`, 'error')
    return
  }

  generatingPortrait.value = true
  try {
    const data = await membersApi.generatePortrait(memberId, file)
    form.value.portrait = data.portrait
    store.addToast('立繪已生成', 'success')
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
  generatingPortrait.value = false
  input.value = ''
}

// ═══════════════════════════════════════
// Account bindings
// ═══════════════════════════════════════

function openBindDialog() {
  bindForm.value = { account_id: 0, priority: 0, model: '' }
  showBindDialog.value = true
}

async function bindAccount() {
  if (!bindForm.value.account_id) return
  try {
    await membersApi.createAccount(memberId, bindForm.value)
    store.addToast('帳號已綁定', 'success')
    showBindDialog.value = false
    await fetchMember()
  } catch {
    store.addToast('綁定失敗', 'error')
  }
}

function openEditBindDialog(acc: MemberAccount) {
  editingBinding.value = acc
  editBindForm.value = { model: acc.model, priority: acc.priority }
  showEditBindDialog.value = true
}

async function saveEditBinding() {
  if (!editingBinding.value) return
  try {
    await membersApi.createAccount(memberId, {
      account_id: editingBinding.value.account_id,
      priority: editBindForm.value.priority,
      model: editBindForm.value.model,
    })
    store.addToast('綁定已更新', 'success')
    showEditBindDialog.value = false
    await fetchMember()
  } catch (e: any) {
    store.addToast(e.message || '更新失敗', 'error')
  }
}

async function unbindAccount(accountId: number) {
  try {
    await membersApi.deleteAccount(memberId, accountId)
    store.addToast('帳號已解綁', 'success')
    showEditBindDialog.value = false
    await fetchMember()
  } catch {
    store.addToast('解綁失敗', 'error')
  }
}

function providerBadgeClass(provider: string) {
  return provider === 'claude'
    ? 'bg-orange-500/10 text-orange-400 border-orange-500/20'
    : 'bg-blue-500/10 text-blue-400 border-blue-500/20'
}

// ═══════════════════════════════════════
// Skills
// ═══════════════════════════════════════

async function toggleSkill(skill: SkillInfo) {
  if (expandedSkill.value === skill.name) {
    expandedSkill.value = null
    editingSkill.value = false
    return
  }
  expandedSkill.value = skill.name
  editingSkill.value = false
  loadingSkillContent.value = true
  try {
    const data = await membersApi.getSkill(memberId, skill.name)
    skillContent.value = data.content
  } catch {
    store.addToast('技能載入失敗', 'error')
    expandedSkill.value = null
  }
  loadingSkillContent.value = false
}

function startEditSkill() {
  skillEditContent.value = skillContent.value
  editingSkill.value = true
}

async function saveSkill() {
  if (!expandedSkill.value) return
  savingSkill.value = true
  try {
    await membersApi.updateSkill(memberId, expandedSkill.value, { content: skillEditContent.value })
    skillContent.value = skillEditContent.value
    editingSkill.value = false
    store.addToast('技能已更新', 'success')
    await fetchSkills()
  } catch {
    store.addToast('儲存失敗', 'error')
  }
  savingSkill.value = false
}

async function handleDeleteSkill(skillName: string) {
  if (!confirm(`確定刪除技能「${skillName}」？`)) return
  try {
    await membersApi.deleteSkill(memberId, skillName)
    store.addToast('技能已刪除', 'success')
    if (expandedSkill.value === skillName) expandedSkill.value = null
    await fetchSkills()
  } catch {
    store.addToast('刪除失敗', 'error')
  }
}

function openNewSkillDialog() {
  newSkillForm.value = { name: '', content: '# 新技能\n\n' }
  showNewSkillDialog.value = true
}

async function handleCreateSkill() {
  if (!newSkillForm.value.name) return
  try {
    await membersApi.createSkill(memberId, newSkillForm.value)
    store.addToast('技能已建立', 'success')
    showNewSkillDialog.value = false
    await fetchSkills()
  } catch (e: any) {
    store.addToast(e.message || '建立失敗', 'error')
  }
}

// ═══════════════════════════════════════
// MCP
// ═══════════════════════════════════════

function validateMcpJson(): boolean {
  try {
    const parsed = JSON.parse(mcpContent.value)
    if (!parsed || typeof parsed !== 'object' || !('mcpServers' in parsed)) {
      mcpJsonError.value = '必須包含 mcpServers 鍵'
      return false
    }
    mcpJsonError.value = ''
    return true
  } catch (e: any) {
    mcpJsonError.value = `JSON 格式錯誤: ${e.message}`
    return false
  }
}

async function saveMcp() {
  if (!validateMcpJson()) return
  savingMcp.value = true
  try {
    await membersApi.updateMcpConfig(memberId, mcpContent.value)
    store.addToast('MCP 設定已儲存', 'success')
    mcpEditing.value = false
  } catch {
    store.addToast('MCP 設定儲存失敗', 'error')
  }
  savingMcp.value = false
}

// ═══════════════════════════════════════
// Delete
// ═══════════════════════════════════════

async function doDelete() {
  try {
    await membersApi.deleteMember(memberId)
    store.addToast('成員已刪除', 'success')
    router.push('/settings/team')
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}

// ═══════════════════════════════════════
// Init
// ═══════════════════════════════════════

function closeCopyMenu() { showCopySkillMenu.value = null }

onMounted(async () => {
  await Promise.all([fetchMember(), fetchAccounts(), fetchSkills(), fetchMcp(), fetchAllMembers()])
  loading.value = false
  document.addEventListener('click', closeCopyMenu)
})

onUnmounted(() => {
  document.removeEventListener('click', closeCopyMenu)
})
</script>

<template>
  <div class="space-y-6">
    <!-- Header actions via Teleport -->
    <Teleport to="#settings-header-actions">
      <button
        @click="saveMember"
        :disabled="saving || !form.name.trim()"
        class="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded-lg text-xs font-medium transition-colors"
      >
        <Loader2 v-if="saving" class="w-3.5 h-3.5 animate-spin" />
        <Save v-else class="w-3.5 h-3.5" />
        儲存
      </button>
    </Teleport>

    <!-- Header -->
    <div class="flex items-center gap-3">
      <button
        @click="router.push('/settings/team')"
        class="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 rounded-lg transition-colors"
      >
        <ArrowLeft class="w-5 h-5" />
      </button>
      <h2 class="text-xl font-semibold text-slate-200">{{ form.name || '成員設定' }}</h2>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex justify-center py-12">
      <Loader2 class="w-8 h-8 animate-spin text-slate-400" />
    </div>

    <template v-else>
      <!-- ═══ Section 1: 基本資訊 ═══ -->
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-6 space-y-4">
        <h3 class="text-sm font-bold text-slate-300 uppercase tracking-wider">基本資訊</h3>

        <div class="flex flex-col sm:flex-row gap-6">
          <!-- Left: Portrait -->
          <div class="flex flex-col items-center gap-3 shrink-0">
            <div class="w-[200px] h-[200px] rounded-xl overflow-hidden bg-slate-900/50 border border-slate-700/50">
              <img
                v-if="form.portrait"
                :src="`${API}${form.portrait}`"
                :alt="form.name"
                class="w-full h-full object-cover"
              />
              <div v-else class="w-full h-full flex items-center justify-center text-6xl">
                {{ form.avatar || '' }}
              </div>
            </div>
            <!-- Upload / Generate buttons -->
            <div class="flex gap-2">
              <input ref="portraitInput" type="file" accept="image/*" class="hidden" @change="handleUploadPortrait" />
              <input ref="generateInput" type="file" accept="image/*" class="hidden" @change="handleGeneratePortrait" />
              <button
                @click="portraitInput?.click()"
                :disabled="uploadingPortrait || generatingPortrait"
                class="flex items-center gap-1.5 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-200 rounded-lg text-xs transition-colors"
              >
                <Upload class="w-3.5 h-3.5" />
                {{ uploadingPortrait ? '上傳中...' : '上傳' }}
              </button>
              <button
                @click="generateInput?.click()"
                :disabled="uploadingPortrait || generatingPortrait"
                class="flex items-center gap-1.5 px-3 py-1.5 bg-purple-500/20 hover:bg-purple-500/30 disabled:opacity-50 text-purple-300 rounded-lg text-xs transition-colors"
              >
                <Sparkles class="w-3.5 h-3.5" :class="{ 'animate-pulse': generatingPortrait }" />
                {{ generatingPortrait ? '生成中...' : 'AI 生成' }}
              </button>
            </div>
          </div>

          <!-- Right: Form fields -->
          <div class="flex-1 space-y-4 min-w-0">
            <!-- Name -->
            <div>
              <label class="block text-sm text-slate-400 mb-1">名稱 <span class="text-red-400">*</span></label>
              <input
                v-model="form.name"
                type="text"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500"
                placeholder="例：小陳"
              />
            </div>

            <!-- Role -->
            <div>
              <label class="block text-sm text-slate-400 mb-1">角色</label>
              <input
                v-model="form.role"
                type="text"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500"
                placeholder="例：資深開發者"
              />
            </div>

            <!-- Description -->
            <div>
              <label class="block text-sm text-slate-400 mb-1">描述</label>
              <textarea
                v-model="form.description"
                rows="3"
                class="w-full px-3 py-2 bg-slate-900 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 resize-none"
                placeholder="擅長什麼..."
              ></textarea>
            </div>

            <!-- Avatar -->
            <div>
              <label class="block text-sm text-slate-400 mb-1">頭像</label>
              <div class="flex flex-wrap gap-1.5">
                <button
                  v-for="e in avatarOptions"
                  :key="e"
                  @click="form.avatar = e"
                  :class="[
                    'w-9 h-9 rounded-lg text-lg flex items-center justify-center transition-all',
                    form.avatar === e
                      ? 'bg-emerald-500/20 border-2 border-emerald-500 scale-110'
                      : 'bg-slate-800 border border-slate-700 hover:border-slate-500'
                  ]"
                >
                  {{ e }}
                </button>
              </div>
            </div>

            <!-- Sprite Index -->
            <div>
              <label class="block text-sm text-slate-400 mb-2">小人物（空間用）</label>
              <div class="flex items-center gap-2">
                <button
                  v-for="i in 6"
                  :key="i - 1"
                  @click="form.sprite_index = i - 1"
                  class="w-10 h-14 rounded-lg border-2 transition-all overflow-hidden bg-slate-900"
                  :class="form.sprite_index === i - 1
                    ? 'border-emerald-500 ring-2 ring-emerald-500/30'
                    : 'border-slate-700 hover:border-slate-600'"
                >
                  <div class="w-full h-full overflow-hidden flex items-center justify-center">
                    <img
                      :src="`/assets/office/characters_4dir/char_${i - 1}.png`"
                      class="object-none object-left-top"
                      style="image-rendering: pixelated; width: 16px; height: 32px; transform: scale(1.5); transform-origin: center;"
                    />
                  </div>
                </button>
                <router-link
                  v-if="memberId"
                  :to="`/settings/team/${memberId}/sprite`"
                  class="ml-2 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs rounded-lg transition flex items-center gap-1"
                >
                  AI 生成
                </router-link>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ═══ Section 2: 帳號綁定 ═══ -->
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-6 space-y-4">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <Plug class="w-4 h-4 text-violet-400" />
            <h3 class="text-sm font-bold text-slate-300 uppercase tracking-wider">帳號綁定</h3>
          </div>
          <button
            @click="openBindDialog"
            class="flex items-center gap-1 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 rounded-lg text-xs font-medium transition-colors"
          >
            <Plus class="w-3.5 h-3.5" />
            綁定帳號
          </button>
        </div>

        <div v-if="memberAccounts.length === 0" class="text-center py-6 text-slate-500 text-sm">
          尚未綁定帳號
        </div>

        <div v-else class="space-y-2">
          <button
            v-for="acc in memberAccounts"
            :key="acc.account_id"
            @click="openEditBindDialog(acc)"
            class="w-full flex items-center gap-3 px-4 py-3 bg-slate-900/50 hover:bg-slate-900 rounded-xl border border-slate-700/50 hover:border-violet-500/30 transition-all text-left"
          >
            <span :class="acc.is_healthy ? 'text-emerald-500' : 'text-red-400'">&#9679;</span>
            <span class="text-sm text-slate-200 flex-1 truncate">{{ acc.name }}</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded border" :class="providerBadgeClass(acc.provider)">
              {{ acc.provider }}
            </span>
            <span v-if="acc.model" class="text-xs text-slate-400">{{ acc.model }}</span>
            <span class="text-[10px] text-slate-500 font-mono">P{{ acc.priority }}</span>
          </button>
        </div>
      </div>

      <!-- ═══ Section 3: 技能 ═══ -->
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-6 space-y-4">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <BookOpen class="w-4 h-4 text-purple-400" />
            <h3 class="text-sm font-bold text-slate-300 uppercase tracking-wider">技能</h3>
          </div>
          <button
            @click="openNewSkillDialog"
            class="flex items-center gap-1 px-3 py-1.5 bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 rounded-lg text-xs font-medium transition-colors"
          >
            <Plus class="w-3.5 h-3.5" />
            新增技能
          </button>
        </div>

        <div v-if="loadingSkills" class="flex justify-center py-6">
          <Loader2 class="w-6 h-6 animate-spin text-slate-400" />
        </div>

        <div v-else-if="skills.length === 0" class="text-center py-6 text-slate-500 text-sm">
          尚未設定技能
        </div>

        <div v-else class="space-y-2">
          <div
            v-for="skill in skills"
            :key="skill.name"
            class="bg-slate-900/50 rounded-xl border border-slate-700/50 overflow-hidden"
          >
            <!-- Skill header -->
            <button
              @click="toggleSkill(skill)"
              class="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-900 transition-colors text-left"
            >
              <BookOpen class="w-4 h-4 text-purple-400 shrink-0" />
              <div class="flex-1 min-w-0">
                <div class="text-sm text-slate-200 truncate">{{ skill.title }}</div>
                <div class="text-[10px] text-slate-500 font-mono">{{ skill.name }}.md</div>
              </div>
              <component :is="expandedSkill === skill.name ? ChevronUp : ChevronDown" class="w-4 h-4 text-slate-500 shrink-0" />
            </button>

            <!-- Expanded content -->
            <div v-if="expandedSkill === skill.name" class="border-t border-slate-700/50 p-4 space-y-3">
              <div v-if="loadingSkillContent" class="text-center text-sm text-slate-500 py-4">載入中...</div>
              <template v-else>
                <!-- View mode -->
                <pre v-if="!editingSkill" class="whitespace-pre-wrap text-sm text-slate-300 font-mono bg-slate-950/50 rounded-lg p-4 max-h-[50vh] overflow-y-auto">{{ skillContent }}</pre>
                <!-- Edit mode -->
                <textarea
                  v-else
                  v-model="skillEditContent"
                  class="w-full h-[40vh] bg-slate-950/50 rounded-lg p-4 border border-purple-500/50 text-sm text-slate-300 font-mono resize-none outline-none focus:ring-2 focus:ring-purple-500"
                ></textarea>

                <div class="flex items-center justify-between">
                  <button
                    @click="handleDeleteSkill(skill.name)"
                    class="flex items-center gap-1 px-3 py-1.5 text-xs text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg transition-colors"
                  >
                    <Trash2 class="w-3.5 h-3.5" />
                    刪除
                  </button>
                  <div class="flex gap-2">
                    <template v-if="!editingSkill">
                      <!-- Copy skill button -->
                      <div class="relative">
                        <button
                          @click.stop="toggleCopyMenu(skill.name)"
                          :disabled="copyingSkill"
                          class="flex items-center gap-1 px-3 py-1.5 bg-sky-500/20 hover:bg-sky-500/30 text-sky-300 rounded-lg text-xs font-medium transition-colors"
                          title="複製到其他成員"
                        >
                          <Copy class="w-3.5 h-3.5" />
                          複製
                        </button>
                        <!-- Dropdown -->
                        <div
                          v-if="showCopySkillMenu === skill.name"
                          class="absolute right-0 bottom-full mb-1 w-48 bg-slate-800 rounded-lg border border-slate-700 shadow-xl z-10 max-h-48 overflow-y-auto py-1"
                        >
                          <div class="px-3 py-1.5 text-[10px] text-slate-500 uppercase tracking-wider">複製到</div>
                          <button
                            v-for="m in allMembers.filter(m => m.id !== memberId)"
                            :key="m.id"
                            @click="copySkillToMember(skill.name, m.id)"
                            class="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-300 hover:bg-slate-700 transition-colors text-left"
                          >
                            <span>{{ m.avatar }}</span>
                            <span class="truncate">{{ m.name }}</span>
                          </button>
                          <div v-if="allMembers.filter(m => m.id !== memberId).length === 0" class="px-3 py-2 text-xs text-slate-500">
                            沒有其他成員
                          </div>
                        </div>
                      </div>
                      <button
                        @click="startEditSkill"
                        class="flex items-center gap-1 px-3 py-1.5 bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 rounded-lg text-xs font-medium transition-colors"
                      >
                        <Edit3 class="w-3.5 h-3.5" />
                        編輯
                      </button>
                    </template>
                    <template v-else>
                      <button @click="editingSkill = false" class="px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors">取消</button>
                      <button
                        @click="saveSkill"
                        :disabled="savingSkill"
                        class="flex items-center gap-1 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg text-xs font-medium transition-colors"
                      >
                        <Save class="w-3.5 h-3.5" />
                        {{ savingSkill ? '儲存中...' : '儲存' }}
                      </button>
                    </template>
                  </div>
                </div>
              </template>
            </div>
          </div>
        </div>
      </div>

      <!-- ═══ Section 4: MCP 設定 ═══ -->
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-6 space-y-4">
        <div class="flex items-center gap-2">
          <Plug class="w-4 h-4 text-cyan-400" />
          <h3 class="text-sm font-bold text-slate-300 uppercase tracking-wider">MCP 設定</h3>
        </div>
        <p class="text-xs text-slate-500">Model Context Protocol servers 設定，JSON 格式，必須包含 <code class="text-cyan-400">mcpServers</code> 鍵。</p>

        <div v-if="loadingMcp" class="flex justify-center py-6">
          <Loader2 class="w-6 h-6 animate-spin text-slate-400" />
        </div>

        <div v-else class="space-y-3">
          <textarea
            v-model="mcpContent"
            :readonly="!mcpEditing"
            @input="mcpJsonError = ''"
            class="w-full h-64 bg-slate-900/50 rounded-xl p-4 text-sm text-slate-300 font-mono resize-none outline-none border"
            :class="mcpEditing ? 'border-cyan-500/50 focus:ring-2 focus:ring-cyan-500' : 'border-slate-700/50'"
            placeholder='{"mcpServers": {}}'
          ></textarea>
          <p v-if="mcpJsonError" class="text-xs text-red-400">{{ mcpJsonError }}</p>

          <div class="flex justify-end gap-2">
            <template v-if="!mcpEditing">
              <button
                @click="mcpEditing = true"
                class="flex items-center gap-1 px-4 py-2 bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 rounded-lg text-xs font-medium transition-colors"
              >
                <Edit3 class="w-3.5 h-3.5" />
                編輯
              </button>
            </template>
            <template v-else>
              <button @click="mcpEditing = false; mcpJsonError = ''" class="px-4 py-2 text-xs text-slate-400 hover:text-slate-200 transition-colors">取消</button>
              <button
                @click="saveMcp"
                :disabled="savingMcp"
                class="flex items-center gap-1 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg text-xs font-medium transition-colors"
              >
                <Save class="w-3.5 h-3.5" />
                {{ savingMcp ? '儲存中...' : '儲存' }}
              </button>
            </template>
          </div>
        </div>
      </div>

      <!-- ═══ Section 5: 危險區域 ═══ -->
      <div class="bg-slate-800/50 rounded-2xl border border-red-500/20 p-6 space-y-4">
        <div class="flex items-center gap-2">
          <AlertTriangle class="w-4 h-4 text-red-400" />
          <h3 class="text-sm font-bold text-red-400 uppercase tracking-wider">危險區域</h3>
        </div>
        <div class="flex items-center justify-between">
          <div>
            <span class="text-sm text-slate-300">刪除成員</span>
            <p class="text-xs text-slate-500">此操作會刪除成員及所有相關的帳號綁定，無法復原。</p>
          </div>
          <button
            @click="confirmDelete = true"
            class="flex items-center gap-2 px-4 py-2 text-red-400 hover:text-red-300 hover:bg-red-500/10 border border-red-500/30 rounded-lg transition text-sm"
          >
            <Trash2 class="w-4 h-4" />
            刪除成員
          </button>
        </div>
      </div>
    </template>

    <!-- ═══ Dialogs ═══ -->

    <!-- Bind Account Dialog -->
    <Teleport to="body">
      <div v-if="showBindDialog" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" @click.self="showBindDialog = false">
        <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-sm p-6 space-y-4">
          <h3 class="text-sm font-bold text-slate-200">綁定帳號</h3>

          <div>
            <label class="block text-xs text-slate-400 mb-1">選擇帳號</label>
            <select v-model="bindForm.account_id" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-slate-200 outline-none">
              <option :value="0" disabled>-- 請選擇 --</option>
              <option v-for="acc in availableAccountsForBind" :key="acc.id" :value="acc.id">
                {{ acc.name }} ({{ acc.provider }} / {{ acc.subscription }})
              </option>
            </select>
          </div>
          <div v-if="bindModelOptions.length > 0">
            <label class="block text-xs text-slate-400 mb-1">模型</label>
            <select v-model="bindForm.model" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-slate-200 outline-none">
              <option v-for="opt in bindModelOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>
          <div>
            <label class="block text-xs text-slate-400 mb-1">優先順序</label>
            <input v-model.number="bindForm.priority" type="number" min="0" class="w-20 bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-slate-200 outline-none font-mono" />
            <span class="text-[10px] text-slate-500 ml-2">0 = 主要</span>
          </div>

          <div class="flex justify-end gap-2 pt-2">
            <button @click="showBindDialog = false" class="px-4 py-2 text-xs text-slate-400 hover:text-slate-200 transition-colors">取消</button>
            <button @click="bindAccount" :disabled="!bindForm.account_id" class="px-4 py-2 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-lg text-xs font-bold transition-all">確認綁定</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Edit Binding Dialog -->
    <Teleport to="body">
      <div v-if="showEditBindDialog && editingBinding" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" @click.self="showEditBindDialog = false">
        <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-sm p-6 space-y-4">
          <h3 class="text-sm font-bold text-slate-200">編輯綁定</h3>

          <div class="flex items-center gap-2 bg-slate-900/50 rounded-lg px-3 py-2.5">
            <span :class="editingBinding.is_healthy ? 'text-emerald-500' : 'text-red-400'">&#9679;</span>
            <span class="text-sm text-slate-200">{{ editingBinding.name }}</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded border" :class="providerBadgeClass(editingBinding.provider)">
              {{ editingBinding.provider }}
            </span>
            <span class="text-xs text-slate-500">{{ editingBinding.subscription }}</span>
          </div>

          <div>
            <label class="block text-xs text-slate-400 mb-1">模型</label>
            <select v-model="editBindForm.model" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-slate-200 outline-none">
              <option value="">-- 未指定 --</option>
              <option
                v-for="opt in (modelOptions[editingBinding.provider] || [])"
                :key="opt.value"
                :value="opt.value"
              >{{ opt.label }}</option>
            </select>
          </div>

          <div>
            <label class="block text-xs text-slate-400 mb-1">優先順序</label>
            <input v-model.number="editBindForm.priority" type="number" min="0" class="w-20 bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-slate-200 outline-none font-mono" />
            <span class="text-[10px] text-slate-500 ml-2">0 = 主要</span>
          </div>

          <div class="flex items-center justify-between pt-2">
            <button @click="unbindAccount(editingBinding.account_id)" class="px-3 py-2 text-xs text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg transition-colors">
              解除綁定
            </button>
            <div class="flex gap-2">
              <button @click="showEditBindDialog = false" class="px-4 py-2 text-xs text-slate-400 hover:text-slate-200 transition-colors">取消</button>
              <button @click="saveEditBinding" class="px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-white rounded-lg text-xs font-bold transition-all">儲存</button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- New Skill Dialog -->
    <Teleport to="body">
      <div v-if="showNewSkillDialog" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" @click.self="showNewSkillDialog = false">
        <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-md p-6 space-y-4">
          <h3 class="text-sm font-bold text-slate-200">新增技能</h3>

          <div>
            <label class="block text-xs text-slate-400 mb-1">技能名稱（英文、小寫、連字號）</label>
            <input
              v-model="newSkillForm.name"
              class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-slate-200 font-mono outline-none focus:ring-2 focus:ring-purple-500"
              placeholder="例：code-review"
            />
          </div>

          <div>
            <label class="block text-xs text-slate-400 mb-1">內容（Markdown）</label>
            <textarea
              v-model="newSkillForm.content"
              rows="8"
              class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-slate-200 font-mono outline-none resize-none focus:ring-2 focus:ring-purple-500"
              placeholder="# 技能標題&#10;&#10;技能說明..."
            ></textarea>
          </div>

          <div class="flex justify-end gap-2 pt-2">
            <button @click="showNewSkillDialog = false" class="px-4 py-2 text-xs text-slate-400 hover:text-slate-200 transition-colors">取消</button>
            <button @click="handleCreateSkill" :disabled="!newSkillForm.name" class="px-4 py-2 bg-purple-500 hover:bg-purple-600 disabled:opacity-50 text-white rounded-lg text-xs font-bold transition-all">建立</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Confirm Delete -->
    <ConfirmDialog
      :show="confirmDelete"
      title="刪除成員"
      :message="`確定要刪除「${form.name}」？相關的帳號綁定也會移除，此操作無法復原。`"
      confirm-text="刪除"
      @confirm="doDelete"
      @cancel="confirmDelete = false"
    />
  </div>
</template>
