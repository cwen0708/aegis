<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Settings, Globe, Terminal, MessageSquare, Users, Bot, Activity, Lock, Loader2, FolderKanban, Mail, ChevronDown, Download, Layers, LogOut, Rocket } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import { useResponsive } from '../../composables/useResponsive'
import { useAuthStore } from '../../stores/auth'

const route = useRoute()
const router = useRouter()
const { isMobile } = useResponsive()
const auth = useAuthStore()
const showMobileMenu = ref(false)

const menuItems = [
  { path: '/settings/general', label: '一般設定', icon: Globe },
  { path: '/settings/onestack', label: 'OneStack', icon: Layers },
  { path: '/settings/channels', label: '頻道設定', icon: MessageSquare },
  { path: '/settings/projects', label: '專案管理', icon: FolderKanban },
  { path: '/settings/invitations', label: '邀請管理', icon: Mail },
  { path: '/settings/team', label: '團隊管理', icon: Users },
  { path: '/settings/agents', label: '代理設定', icon: Bot },
  { path: '/settings/tools', label: '終端管理', icon: Terminal },
  { path: '/settings/status', label: '服務狀態', icon: Activity },
  { path: '/settings/update', label: '系統更新', icon: Download },
  { path: '/onboarding', label: '設定引導', icon: Rocket },
]

// 驗證狀態
const authenticated = ref(false)
const password = ref('')
const error = ref('')
const loading = ref(false)

onMounted(() => {
  if (auth.isAuthenticated) {
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
    const ok = await auth.verifyPassword(password.value)
    if (ok) {
      authenticated.value = true
    } else {
      error.value = '密碼錯誤'
    }
  } catch {
    error.value = '驗證失敗，請稍後再試'
  } finally {
    loading.value = false
  }
}

function handleLogout() {
  auth.logout()
  authenticated.value = false
  password.value = ''
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="sticky top-0 z-10 h-14 sm:h-16 shrink-0 bg-slate-900/50 backdrop-blur-md border-b border-slate-800 px-2 sm:px-8 flex items-center justify-between">
      <div class="flex items-center gap-2">
        <Settings class="w-5 h-5 text-slate-400" />
        <h1 class="text-base sm:text-lg font-bold text-slate-100">系統設定</h1>
      </div>
      <button
        v-if="authenticated"
        @click="handleLogout"
        class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"
      >
        <LogOut class="w-3.5 h-3.5" />
        登出
      </button>
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
    <div v-else class="flex-1 flex flex-col sm:flex-row overflow-hidden">
      <!-- Mobile: Dropdown Menu -->
      <div v-if="isMobile" class="shrink-0 border-b border-slate-800 bg-slate-900/30 px-2 py-2">
        <button
          @click="showMobileMenu = !showMobileMenu"
          class="w-full flex items-center justify-between gap-2 px-3 py-2 bg-slate-800 rounded-lg text-sm text-slate-200"
        >
          <div class="flex items-center gap-2">
            <component :is="menuItems.find(m => m.path === route.path)?.icon || Globe" class="w-4 h-4 text-emerald-400" />
            {{ menuItems.find(m => m.path === route.path)?.label || '選擇' }}
          </div>
          <ChevronDown class="w-4 h-4 text-slate-400" :class="{ 'rotate-180': showMobileMenu }" />
        </button>
        <div v-if="showMobileMenu" class="mt-2 bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
          <button
            v-for="item in menuItems"
            :key="item.path"
            @click="router.push(item.path); showMobileMenu = false"
            class="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm transition-colors"
            :class="route.path === item.path
              ? 'bg-emerald-500/20 text-emerald-400'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700'"
          >
            <component :is="item.icon" class="w-4 h-4" />
            {{ item.label }}
          </button>
        </div>
      </div>

      <!-- Desktop: Left Menu -->
      <div v-else class="w-48 shrink-0 border-r border-slate-800 bg-slate-900/30 p-4">
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
      <div class="flex-1 overflow-auto p-2 sm:p-8">
        <router-view />
      </div>
    </div>
  </div>
</template>
