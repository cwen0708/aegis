<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Settings, Globe, Sparkles, MessageSquare, Users, Bot, Activity, Lock, Loader2, FolderKanban, Mail } from 'lucide-vue-next'
import { useRoute } from 'vue-router'

const route = useRoute()

const menuItems = [
  { path: '/settings/general', label: '一般設定', icon: Globe },
  { path: '/settings/ai', label: 'AI 模型', icon: Sparkles },
  { path: '/settings/channels', label: '頻道', icon: MessageSquare },
  { path: '/settings/projects', label: '專案管理', icon: FolderKanban },
  { path: '/settings/invitations', label: '邀請管理', icon: Mail },
  { path: '/settings/team', label: '團隊管理', icon: Users },
  { path: '/settings/agents', label: 'AI 代理', icon: Bot },
  { path: '/settings/status', label: '服務狀態', icon: Activity },
]

// 驗證狀態
const authenticated = ref(false)
const password = ref('')
const error = ref('')
const loading = ref(false)

const API = ''

onMounted(() => {
  // 檢查 sessionStorage 是否已驗證
  if (sessionStorage.getItem('aegis-admin-auth') === 'true') {
    authenticated.value = true
  }
})

async function verifyPassword() {
  if (!password.value.trim()) {
    error.value = '請輸入密碼'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const res = await fetch(`${API}/api/v1/auth/verify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: password.value }),
    })
    if (res.ok) {
      sessionStorage.setItem('aegis-admin-auth', 'true')
      authenticated.value = true
    } else {
      const data = await res.json()
      error.value = data.detail || '密碼錯誤'
    }
  } catch {
    error.value = '驗證失敗，請稍後再試'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="sticky top-0 z-10 h-16 shrink-0 bg-slate-900/50 backdrop-blur-md border-b border-slate-800 px-8 flex items-center">
      <div class="flex items-center gap-2">
        <Settings class="w-5 h-5 text-slate-400" />
        <h1 class="text-lg font-bold text-slate-100">系統設定</h1>
      </div>
    </div>

    <!-- 未驗證：顯示密碼輸入 -->
    <div v-if="!authenticated" class="flex-1 flex items-center justify-center">
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-8 w-full max-w-sm">
        <div class="flex items-center gap-3 mb-6">
          <div class="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
            <Lock class="w-6 h-6 text-emerald-400" />
          </div>
          <div>
            <h2 class="text-sm font-bold text-slate-200">管理員驗證</h2>
            <p class="text-xs text-slate-500">請輸入管理員密碼以存取設定</p>
          </div>
        </div>

        <div class="space-y-4">
          <div>
            <input
              v-model="password"
              type="password"
              placeholder="輸入管理員密碼"
              class="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none text-sm"
              @keyup.enter="verifyPassword"
              autofocus
            />
          </div>

          <div v-if="error" class="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
            {{ error }}
          </div>

          <button
            @click="verifyPassword"
            :disabled="loading"
            class="w-full flex items-center justify-center gap-2 px-4 py-3 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-lg font-bold text-sm transition-all"
          >
            <Loader2 v-if="loading" class="w-4 h-4 animate-spin" />
            {{ loading ? '驗證中...' : '進入設定' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 已驗證：顯示設定內容 -->
    <div v-else class="flex-1 flex overflow-hidden">
      <!-- Left Menu -->
      <div class="w-48 shrink-0 border-r border-slate-800 bg-slate-900/30 p-4">
        <nav class="space-y-1">
          <router-link
            v-for="item in menuItems"
            :key="item.path"
            :to="item.path"
            class="flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors"
            :class="route.path === item.path
              ? 'bg-emerald-500/20 text-emerald-400'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'"
          >
            <component :is="item.icon" class="w-4 h-4" />
            {{ item.label }}
          </router-link>
        </nav>
      </div>

      <!-- Right Content -->
      <div class="flex-1 overflow-auto p-8">
        <router-view />
      </div>
    </div>
  </div>
</template>
