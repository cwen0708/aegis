<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { Plus, UserPlus, Save, Edit3, Upload, Sparkles, Image } from 'lucide-vue-next'
import { useAegisStore } from '../stores/aegis'
import ConfirmDialog from '../components/ConfirmDialog.vue'

const store = useAegisStore()
const API = ''

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

const avatarOptions = ['🤖', '👨‍💼', '👩‍💻', '🧪', '📊', '🔧', '🎯', '🧠', '🦊', '🐱', '🐶', '🦉', '🚀', '⚡', '🔥', '💎']

interface AccountInfo {
  id: number
  provider: string
  name: string
  credential_file: string
  subscription: string
  email: string
  is_healthy: boolean
}

interface MemberAccount {
  account_id: number
  priority: number
  model: string
  name: string
  provider: string
  subscription: string
  is_healthy: boolean
}

interface MemberInfo {
  id: number
  name: string
  avatar: string
  role: string
  description: string
  sprite_index: number
  portrait: string
  provider: string  // 從主帳號推導
  accounts: MemberAccount[]
}

const loading = ref(true)
const accounts = ref<AccountInfo[]>([])
const members = ref<MemberInfo[]>([])

// Dialogs
const showMemberDialog = ref(false)
const showBindDialog = ref(false)
const showEditBindDialog = ref(false)
const editingMember = ref<MemberInfo | null>(null)
const bindingMemberId = ref<number | null>(null)
const editingBinding = ref<{ memberId: number; acc: MemberAccount } | null>(null)
const editBindForm = ref({ model: '', priority: 0 })

const memberForm = ref({ name: '', avatar: '🤖', role: '', description: '', sprite_index: 0, portrait: '' })
const bindForm = ref({ account_id: 0, priority: 0, model: '' })

// 綁定時根據選的帳號 provider 提供 model 選項
const bindAccountProvider = computed(() => {
  const acc = accounts.value.find(a => a.id === bindForm.value.account_id)
  return acc?.provider || ''
})
const bindModelOptions = computed(() => modelOptions[bindAccountProvider.value] || [])

// Phase routing
const phaseRouting = ref<Record<string, string>>({})
const phases = ['PLANNING', 'DEVELOPING', 'VERIFYING', 'REVIEWING']

async function fetchAll() {
  loading.value = true
  try {
    const [accRes, memRes] = await Promise.all([
      fetch(`${API}/api/v1/accounts`),
      fetch(`${API}/api/v1/members`),
    ])
    if (!accRes.ok) throw new Error(`帳號載入失敗: HTTP ${accRes.status}`)
    if (!memRes.ok) throw new Error(`成員載入失敗: HTTP ${memRes.status}`)
    accounts.value = await accRes.json()
    members.value = await memRes.json()

    // Load phase routing from settings
    await store.fetchSettings()
    for (const phase of phases) {
      phaseRouting.value[phase] = store.settings[`phase_routing.${phase}`] || ''
    }
  } catch (e) {
    store.addToast('載入失敗', 'error')
  }
  loading.value = false
}

onMounted(fetchAll)

// Member CRUD
function openMemberDialog(member?: MemberInfo) {
  if (member) {
    editingMember.value = member
    memberForm.value = {
      name: member.name,
      avatar: member.avatar,
      role: member.role,
      description: member.description,
      sprite_index: member.sprite_index ?? 0,
      portrait: member.portrait ?? '',
    }
  } else {
    editingMember.value = null
    memberForm.value = { name: '', avatar: '🤖', role: '', description: '', sprite_index: 0, portrait: '' }
  }
  showMemberDialog.value = true
}

// 上傳立繪
const uploadingPortrait = ref(false)
const portraitInput = ref<HTMLInputElement | null>(null)

async function uploadPortrait(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files?.length || !editingMember.value) return

  uploadingPortrait.value = true
  try {
    const formData = new FormData()
    formData.append('file', input.files[0]!)

    const res = await fetch(`${API}/api/v1/members/${editingMember.value.id}/portrait`, {
      method: 'POST',
      body: formData,
    })
    if (!res.ok) throw new Error('上傳失敗')

    const data = await res.json()
    memberForm.value.portrait = data.portrait
    store.addToast('立繪已上傳', 'success')
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
  uploadingPortrait.value = false
}

// AI 產生立繪
const generatingPortrait = ref(false)
const generateInput = ref<HTMLInputElement | null>(null)

async function generatePortrait(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files?.length || !editingMember.value) return

  generatingPortrait.value = true
  try {
    const formData = new FormData()
    formData.append('file', input.files[0]!)

    const res = await fetch(`${API}/api/v1/members/${editingMember.value.id}/generate-portrait`, {
      method: 'POST',
      body: formData,
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '生成失敗' }))
      throw new Error(err.detail || '生成失敗')
    }

    const data = await res.json()
    memberForm.value.portrait = data.portrait
    store.addToast('立繪已生成', 'success')
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
  generatingPortrait.value = false
  // 清空 input 以便重新選擇
  input.value = ''
}

async function saveMember() {
  try {
    const url = editingMember.value
      ? `${API}/api/v1/members/${editingMember.value.id}`
      : `${API}/api/v1/members`
    const method = editingMember.value ? 'PUT' : 'POST'
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(memberForm.value),
    })
    if (!res.ok) throw new Error('儲存失敗')
    store.addToast(editingMember.value ? '成員已更新' : '成員已新增', 'success')
    showMemberDialog.value = false
    await fetchAll()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}

// 刪除成員確認
const confirmDeleteMember = ref(false)
const deleteTargetMemberId = ref<number | null>(null)

function requestDeleteMember(id: number) {
  deleteTargetMemberId.value = id
  confirmDeleteMember.value = true
}

async function doDeleteMember() {
  if (!deleteTargetMemberId.value) return
  try {
    const res = await fetch(`${API}/api/v1/members/${deleteTargetMemberId.value}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    store.addToast('成員已刪除', 'success')
    confirmDeleteMember.value = false
    deleteTargetMemberId.value = null
    showMemberDialog.value = false
    await fetchAll()
  } catch {
    store.addToast('刪除失敗', 'error')
  }
}

// Binding
function openBindDialog(memberId: number) {
  bindingMemberId.value = memberId
  bindForm.value = { account_id: 0, priority: 0, model: '' }
  showBindDialog.value = true
}

// 選擇帳號時自動設定預設 model
watch(() => bindForm.value.account_id, (accId) => {
  const acc = accounts.value.find(a => a.id === accId)
  if (acc) {
    const opts = modelOptions[acc.provider]
    if (opts && opts.length > 0) {
      bindForm.value.model = opts[0]!.value
    }
  }
})

const availableAccountsForBind = computed(() => {
  if (!bindingMemberId.value) return accounts.value
  const member = members.value.find(m => m.id === bindingMemberId.value)
  const boundIds = member?.accounts.map(a => a.account_id) || []
  return accounts.value.filter(a => !boundIds.includes(a.id))
})

async function bindAccount() {
  if (!bindingMemberId.value || !bindForm.value.account_id) return
  try {
    const res = await fetch(`${API}/api/v1/members/${bindingMemberId.value}/accounts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(bindForm.value),
    })
    if (!res.ok) throw new Error('綁定失敗')
    store.addToast('帳號已綁定', 'success')
    showBindDialog.value = false
    await fetchAll()
  } catch {
    store.addToast('綁定失敗', 'error')
  }
}

function openEditBindDialog(memberId: number, acc: MemberAccount) {
  editingBinding.value = { memberId, acc }
  editBindForm.value = { model: acc.model, priority: acc.priority }
  showEditBindDialog.value = true
}

async function saveEditBinding() {
  if (!editingBinding.value) return
  const { memberId, acc } = editingBinding.value
  try {
    const res = await fetch(`${API}/api/v1/members/${memberId}/accounts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        account_id: acc.account_id,
        priority: editBindForm.value.priority,
        model: editBindForm.value.model,
      }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || '儲存失敗')
    }
    store.addToast('綁定已更新', 'success')
    showEditBindDialog.value = false
    await fetchAll()
  } catch (e: any) {
    store.addToast(e.message || '更新失敗', 'error')
  }
}

async function removeBinding() {
  if (!editingBinding.value) return
  const { memberId, acc } = editingBinding.value
  await unbindAccount(memberId, acc.account_id)
  showEditBindDialog.value = false
}

async function unbindAccount(memberId: number, accountId: number) {
  try {
    const res = await fetch(`${API}/api/v1/members/${memberId}/accounts/${accountId}`, { method: 'DELETE' })
    if (!res.ok) throw new Error('解綁失敗')
    await fetchAll()
  } catch {
    store.addToast('解綁失敗', 'error')
  }
}

// Phase routing save
async function saveRouting() {
  const data: Record<string, string> = {}
  for (const phase of phases) {
    data[`phase_routing.${phase}`] = phaseRouting.value[phase] || ''
  }
  await store.updateSettings(data)
}

function providerBadgeClass(provider: string) {
  return provider === 'claude'
    ? 'bg-orange-500/10 text-orange-400 border-orange-500/20'
    : 'bg-blue-500/10 text-blue-400 border-blue-500/20'
}
</script>

<template>
  <div class="max-w-4xl">
    <div v-if="loading" class="text-sm text-slate-500 text-center py-20">載入中...</div>

    <div v-else class="space-y-8">

        <!-- 成員管理 -->
        <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
          <div class="px-6 py-4 border-b border-slate-700/50 flex items-center justify-between">
            <div class="flex items-center gap-2">
              <UserPlus class="w-4 h-4 text-emerald-400" />
              <h2 class="text-sm font-semibold text-slate-200">成員管理</h2>
            </div>
            <button @click="openMemberDialog()" class="flex items-center gap-1 px-3 py-1.5 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 rounded-lg text-xs font-medium transition-colors">
              <Plus class="w-3.5 h-3.5" />
              新增成員
            </button>
          </div>

          <div class="p-4 space-y-3">
            <div v-if="members.length === 0" class="text-center text-sm text-slate-500 py-8">
              尚未建立成員，點擊上方按鈕新增
            </div>

            <div v-for="member in members" :key="member.id" class="bg-slate-900/50 rounded-xl border border-slate-700/50 p-4">
              <div class="flex items-center justify-between mb-3">
                <div class="flex items-center gap-3">
                  <span class="text-xl">{{ member.avatar || '🤖' }}</span>
                  <div>
                    <div class="flex items-center gap-2">
                      <span class="text-sm font-semibold text-slate-200">{{ member.name }}</span>
                    </div>
                    <div class="text-xs text-slate-500">{{ member.role }}</div>
                  </div>
                </div>
                <div class="flex items-center gap-1">
                  <button @click="openMemberDialog(member)" class="p-1.5 rounded-lg hover:bg-slate-700/50 text-slate-400 hover:text-slate-200 transition-colors">
                    <Edit3 class="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              <!-- 綁定帳號 -->
              <div class="space-y-1.5">
                <div v-for="(acc, idx) in member.accounts" :key="acc.account_id"
                  @click="openEditBindDialog(member.id, acc)"
                  class="flex items-center justify-between px-3 py-2 bg-slate-800/50 rounded-lg text-xs cursor-pointer hover:bg-slate-800 transition-colors"
                >
                  <div class="flex items-center gap-2 min-w-0">
                    <span class="text-slate-500 font-mono text-[11px] w-5 shrink-0 text-center">{{ idx === 0 ? '主' : (member.accounts.length > 2 ? `備${idx}` : '備') }}</span>
                    <span :class="acc.is_healthy ? 'text-emerald-500' : 'text-red-400'" class="shrink-0">●</span>
                    <span class="text-slate-300 truncate">{{ acc.name }}</span>
                    <span class="text-slate-600 shrink-0">{{ acc.subscription }}</span>
                  </div>
                  <div class="flex items-center gap-1.5 shrink-0">
                    <span v-if="acc.model" class="text-[10px] px-1.5 py-0.5 rounded border" :class="providerBadgeClass(acc.provider)">
                      {{ acc.model }}
                    </span>
                    <span v-else class="text-[10px] text-slate-600">未設定模型</span>
                    <Edit3 class="w-3 h-3 text-slate-600" />
                  </div>
                </div>
                <button @click="openBindDialog(member.id)" class="flex items-center gap-1 px-3 py-1.5 text-[11px] text-slate-500 hover:text-emerald-400 transition-colors">
                  <Plus class="w-3 h-3" />
                  綁定帳號
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 路由設定 -->
        <div class="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
          <div class="px-6 py-4 border-b border-slate-700/50">
            <h2 class="text-sm font-semibold text-slate-200">預設路由</h2>
            <p class="text-[11px] text-slate-500 mt-0.5">各階段的預設成員，可在專案看板中針對個別列表覆寫</p>
          </div>
          <div class="p-6 space-y-3">
            <div v-for="phase in phases" :key="phase" class="flex items-center gap-4">
              <span class="text-xs font-mono text-slate-400 w-28">{{ phase }}</span>
              <select
                v-model="phaseRouting[phase]"
                class="flex-1 bg-slate-900 border border-slate-700 rounded-lg p-2 text-slate-200 text-sm outline-none focus:ring-2 focus:ring-emerald-500"
              >
                <option value="">-- 使用預設 --</option>
                <option v-for="m in members" :key="m.id" :value="String(m.id)">{{ m.avatar }} {{ m.name }}</option>
              </select>
            </div>
            <div class="flex justify-end pt-2">
              <button @click="saveRouting" class="flex items-center gap-2 px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-white rounded-lg font-bold text-xs transition-all">
                <Save class="w-3.5 h-3.5" />
                儲存路由
              </button>
            </div>
          </div>
        </div>
      </div>

    <!-- Member Dialog -->
    <Teleport to="body">
      <div v-if="showMemberDialog" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" @click.self="showMemberDialog = false">
        <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-sm p-6 space-y-4">
          <h3 class="text-sm font-bold text-slate-200">{{ editingMember ? '編輯成員' : '新增成員' }}</h3>

          <div class="grid grid-cols-[4rem_1fr] gap-3">
            <div>
              <label class="block text-xs text-slate-400 mb-1">頭像</label>
              <select v-model="memberForm.avatar" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-center text-lg outline-none">
                <option v-for="e in avatarOptions" :key="e" :value="e">{{ e }}</option>
              </select>
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">名稱</label>
              <input v-model="memberForm.name" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-slate-200 outline-none" placeholder="例：財務小陳" />
            </div>
          </div>

          <div>
            <label class="block text-xs text-slate-400 mb-1">角色</label>
            <input v-model="memberForm.role" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-slate-200 outline-none" placeholder="例：資深開發者" />
          </div>

          <div>
            <label class="block text-xs text-slate-400 mb-1">描述</label>
            <textarea v-model="memberForm.description" rows="2" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-slate-200 outline-none resize-none" placeholder="擅長什麼..."></textarea>
          </div>

          <!-- 小人物選擇 -->
          <div>
            <label class="block text-xs text-slate-400 mb-2">小人物（辦公室用）</label>
            <div class="flex gap-2">
              <button
                v-for="i in 6"
                :key="i - 1"
                @click="memberForm.sprite_index = i - 1"
                class="w-10 h-14 rounded-lg border-2 transition-all overflow-hidden bg-slate-900"
                :class="memberForm.sprite_index === i - 1
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
            </div>
          </div>

          <!-- 立繪上傳 -->
          <div v-if="editingMember">
            <label class="block text-xs text-slate-400 mb-2">立繪（對話框用）</label>
            <div class="flex gap-3">
              <!-- 預覽 -->
              <div class="w-20 h-24 rounded-lg border border-slate-700 bg-slate-900 overflow-hidden flex items-center justify-center">
                <img
                  v-if="memberForm.portrait"
                  :src="`${API}${memberForm.portrait}`"
                  class="w-full h-full object-cover"
                />
                <Image v-else class="w-8 h-8 text-slate-600" />
              </div>
              <!-- 按鈕 -->
              <div class="flex flex-col gap-2">
                <input
                  ref="portraitInput"
                  type="file"
                  accept="image/*"
                  class="hidden"
                  @change="uploadPortrait"
                />
                <input
                  ref="generateInput"
                  type="file"
                  accept="image/*"
                  class="hidden"
                  @change="generatePortrait"
                />
                <button
                  @click="portraitInput?.click()"
                  :disabled="uploadingPortrait || generatingPortrait"
                  class="flex items-center gap-1.5 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-200 rounded-lg text-xs transition-colors"
                >
                  <Upload class="w-3.5 h-3.5" />
                  {{ uploadingPortrait ? '上傳中...' : '上傳立繪' }}
                </button>
                <button
                  @click="generateInput?.click()"
                  :disabled="uploadingPortrait || generatingPortrait"
                  class="flex items-center gap-1.5 px-3 py-1.5 bg-purple-500/20 hover:bg-purple-500/30 disabled:opacity-50 text-purple-300 rounded-lg text-xs transition-colors"
                >
                  <Sparkles class="w-3.5 h-3.5" :class="{ 'animate-pulse': generatingPortrait }" />
                  {{ generatingPortrait ? '生成中...' : '產生立繪' }}
                </button>
              </div>
            </div>
          </div>
          <p v-else class="text-[11px] text-slate-500">
            儲存成員後可上傳立繪
          </p>

          <div class="flex items-center justify-between pt-2">
            <button
              v-if="editingMember"
              @click="requestDeleteMember(editingMember.id)"
              class="px-3 py-2 text-xs text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg transition-colors"
            >
              刪除成員
            </button>
            <span v-else></span>
            <div class="flex gap-2">
              <button @click="showMemberDialog = false" class="px-4 py-2 text-xs text-slate-400 hover:text-slate-200 transition-colors">取消</button>
              <button @click="saveMember" :disabled="!memberForm.name" class="px-4 py-2 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-lg text-xs font-bold transition-all">
                {{ editingMember ? '更新' : '新增' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

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
            <span :class="editingBinding.acc.is_healthy ? 'text-emerald-500' : 'text-red-400'">●</span>
            <span class="text-sm text-slate-200">{{ editingBinding.acc.name }}</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded border" :class="providerBadgeClass(editingBinding.acc.provider)">
              {{ editingBinding.acc.provider }}
            </span>
            <span class="text-xs text-slate-500">{{ editingBinding.acc.subscription }}</span>
          </div>

          <div>
            <label class="block text-xs text-slate-400 mb-1">模型</label>
            <select v-model="editBindForm.model" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-slate-200 outline-none">
              <option value="">-- 未指定 --</option>
              <option
                v-for="opt in (modelOptions[editingBinding.acc.provider] || [])"
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
            <button @click="removeBinding" class="px-3 py-2 text-xs text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg transition-colors">
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

    <!-- Delete Member Confirm -->
    <ConfirmDialog
      :show="confirmDeleteMember"
      title="刪除成員"
      message="確定刪除此成員？相關的帳號綁定也會移除。"
      confirm-text="刪除"
      @confirm="doDeleteMember"
      @cancel="confirmDeleteMember = false; deleteTargetMemberId = null"
    />
  </div>
</template>
