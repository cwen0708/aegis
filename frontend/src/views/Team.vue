<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Plus, ChevronRight } from 'lucide-vue-next'
import { useAegisStore } from '../stores/aegis'
import { useEscapeKey } from '../composables/useEscapeKey'
import { authHeaders } from '../utils/authFetch'

import { config } from '../config'

const store = useAegisStore()
const API = config.apiUrl

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
  provider: string
  accounts: MemberAccount[]
}

const loading = ref(true)
const accounts = ref<AccountInfo[]>([])
const members = ref<MemberInfo[]>([])

// Dialog
const showMemberDialog = ref(false)

// ESC key handling
useEscapeKey(showMemberDialog, () => { showMemberDialog.value = false })

const memberForm = ref({ name: '', avatar: '🤖', role: '', description: '', sprite_index: 0 })

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

  } catch (e) {
    store.addToast('載入失敗', 'error')
  }
  loading.value = false
}

onMounted(fetchAll)

// New member dialog
function openMemberDialog() {
  memberForm.value = { name: '', avatar: '🤖', role: '', description: '', sprite_index: 0 }
  showMemberDialog.value = true
}

async function saveMember() {
  try {
    const res = await fetch(`${API}/api/v1/members`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(memberForm.value),
    })
    if (!res.ok) throw new Error('儲存失敗')
    store.addToast('成員已新增', 'success')
    showMemberDialog.value = false
    await fetchAll()
  } catch (e: any) {
    store.addToast(e.message, 'error')
  }
}

function providerBadgeClass(provider: string) {
  return provider === 'claude'
    ? 'bg-orange-500/10 text-orange-400 border-orange-500/20'
    : 'bg-blue-500/10 text-blue-400 border-blue-500/20'
}
</script>

<template>
  <div class="max-w-4xl">
    <!-- Header action: 新增成員按鈕 -->
    <Teleport to="#settings-header-actions">
      <button @click="openMemberDialog()" class="flex items-center gap-1 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 rounded-lg text-xs font-medium transition-colors">
        <Plus class="w-3.5 h-3.5" />
        新增成員
      </button>
    </Teleport>

    <div v-if="loading" class="text-sm text-slate-500 text-center py-20">載入中...</div>

    <div v-else class="space-y-3">
            <div v-if="members.length === 0" class="text-center text-sm text-slate-500 py-8">
              尚未建立成員，點擊右上角按鈕新增
            </div>

            <div
              v-for="member in members"
              :key="member.id"
              @click="$router.push(`/settings/team/${member.id}`)"
              class="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4 cursor-pointer hover:bg-slate-700/30 hover:border-slate-600/50 transition-all"
            >
              <div class="flex items-center gap-4">
                <!-- 立繪 -->
                <div class="w-[100px] h-[100px] sm:w-[120px] sm:h-[120px] shrink-0 rounded-xl overflow-hidden bg-slate-900/50">
                  <img
                    v-if="member.portrait"
                    :src="`${API}${member.portrait}`"
                    :alt="member.name"
                    class="w-full h-full object-cover"
                  />
                  <div v-else class="w-full h-full flex items-center justify-center text-4xl">
                    {{ member.avatar || '🤖' }}
                  </div>
                </div>

                <!-- 資訊 -->
                <div class="flex-1 min-w-0">
                  <div class="text-sm font-semibold text-slate-200">{{ member.name }}</div>
                  <div class="text-xs text-slate-500 mt-0.5">{{ member.role }}</div>

                  <!-- 帳號摘要 -->
                  <div class="flex flex-wrap gap-1.5 mt-2">
                    <span
                      v-for="acc in member.accounts"
                      :key="acc.account_id"
                      class="text-[10px] px-1.5 py-0.5 rounded border"
                      :class="providerBadgeClass(acc.provider)"
                    >
                      {{ acc.model || acc.name }}
                    </span>
                  </div>
                </div>

                <!-- 箭頭 -->
                <ChevronRight class="w-4 h-4 text-slate-600 shrink-0" />
              </div>
            </div>
          </div>

    <!-- Member Create Dialog -->
    <Teleport to="body">
      <div v-if="showMemberDialog" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" @click.self="showMemberDialog = false">
        <div class="bg-slate-800 rounded-2xl border border-slate-700 w-full max-w-sm p-6 space-y-4">
          <h3 class="text-sm font-bold text-slate-200">新增成員</h3>

          <div class="space-y-3">
            <div>
              <label class="block text-xs text-slate-400 mb-1">頭像</label>
              <div class="flex flex-wrap gap-1.5">
                <button
                  v-for="e in avatarOptions"
                  :key="e"
                  @click="memberForm.avatar = e"
                  type="button"
                  :class="[
                    'w-8 h-8 rounded-lg text-base flex items-center justify-center transition-all',
                    memberForm.avatar === e
                      ? 'bg-emerald-500/20 border-2 border-emerald-500 scale-110'
                      : 'bg-slate-800 border border-slate-700 hover:border-slate-500'
                  ]"
                >
                  {{ e }}
                </button>
              </div>
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

          <p class="text-[11px] text-slate-500">
            儲存成員後可上傳立繪
          </p>

          <div class="flex justify-end gap-2 pt-2">
            <button @click="showMemberDialog = false" class="px-4 py-2 text-xs text-slate-400 hover:text-slate-200 transition-colors">取消</button>
            <button @click="saveMember" :disabled="!memberForm.name" class="px-4 py-2 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-lg text-xs font-bold transition-all">
              新增
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
