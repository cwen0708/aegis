<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Settings, Globe, TerminalSquare, MessageSquare, Users, UserCheck, Bot, Activity, Lock, Loader2, FolderKanban, ChevronDown, Download, Rocket, Building2, Inbox } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import { useResponsive } from '../../composables/useResponsive'
import { useAuthStore } from '../../stores/auth'

const route = useRoute()
const router = useRouter()
const { isMobile } = useResponsive()
const auth = useAuthStore()
const showMobileMenu = ref(false)

const menuGroups = [
  {
    label: '系統',
    items: [
      { path: '/settings/update', label: '系統更新', icon: Download },
      { path: '/settings/general', label: '一般設定', icon: Settings },
      { path: '/settings/status', label: '服務狀態', icon: Activity },
      { path: '/onboarding', label: '設定引導', icon: Rocket },
    ],
  },
  {
    label: '連線',
    items: [
      { path: '/settings/channels', label: '頻道設定', icon: MessageSquare },
      { path: '/settings/users', label: '用戶管理', icon: UserCheck },
      { path: '/settings/domains', label: '網域綁定', icon: Globe },
    ],
  },
  {
    label: '工作空間',
    items: [
      { path: '/settings/rooms', label: '空間管理', icon: Building2 },
      { path: '/settings/raw-messages', label: '訊息收整', icon: Inbox },
      { path: '/settings/projects', label: '專案管理', icon: FolderKanban },
      { path: '/settings/team', label: '成員管理', icon: Users },
      { path: '/settings/agents', label: '代理設定', icon: Bot },
      { path: '/settings/terminal', label: '網頁終端', icon: TerminalSquare },
    ],
  },
]

// 扁平化（用於 mobile dropdown 和路由匹配）
const menuItems = menuGroups.flatMap(g => g.items)

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

// 登出功能已移至 SettingsGeneral.vue

const currentMenuItem = computed(() => menuItems.find(m => route.path === m.path || route.path.startsWith(m.path + '/')))
const triggerEl = ref<HTMLElement | null>(null)
const mobileDropdownStyle = computed(() => {
  if (!triggerEl.value) return {}
  const rect = triggerEl.value.getBoundingClientRect()
  return {
    top: `${rect.bottom + 8}px`,
    left: `${rect.left}px`,
  }
})
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div ref="headerEl" class="sticky top-0 z-10 h-14 sm:h-16 shrink-0 bg-slate-900/50 backdrop-blur-md border-b border-slate-800 px-2 sm:px-8 flex items-center justify-between">
      <div class="flex items-center gap-2">
        <!-- Mobile: 下拉選單觸發器（跟 PageHeader 同樣式） -->
        <button
          v-if="isMobile && authenticated"
          ref="triggerEl"
          @click="showMobileMenu = !showMobileMenu"
          class="flex items-center gap-1.5 min-w-0 group"
        >
          <component :is="currentMenuItem?.icon || Settings" class="w-4 h-4 text-emerald-400 shrink-0" />
          <span class="text-sm font-bold text-slate-100 truncate group-hover:text-emerald-400 transition-colors max-w-[160px]">
            {{ currentMenuItem?.label || '系統設定' }}
          </span>
          <ChevronDown
            class="w-3 h-3 text-slate-500 shrink-0 transition-transform"
            :class="{ 'rotate-180': showMobileMenu }"
          />
        </button>
        <!-- Desktop: 固定標題 -->
        <template v-else>
          <Settings class="w-5 h-5 text-slate-400" />
          <h1 class="text-base sm:text-lg font-bold text-slate-100">系統設定</h1>
        </template>
      </div>
      <!-- 各頁面的 action 按鈕 Teleport 到這裡 -->
      <div id="settings-header-actions" class="flex items-center gap-2"></div>
    </div>

    <!-- Mobile: Dropdown (Teleport to body，跟 PageHeader 同樣式) -->
    <Teleport to="body">
      <template v-if="showMobileMenu && isMobile && authenticated">
        <div class="fixed inset-0 z-40" @click="showMobileMenu = false" />
        <div
          class="fixed z-50 w-64 bg-slate-800 rounded-lg border border-slate-700 shadow-xl max-h-72 overflow-y-auto"
          :style="mobileDropdownStyle"
        >
          <div class="py-1">
            <button
              v-for="item in menuItems"
              :key="item.path"
              @click="router.push(item.path); showMobileMenu = false"
              class="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm transition-colors"
              :class="route.path === item.path
                ? 'bg-emerald-500/20 text-emerald-400'
                : 'text-slate-300 hover:bg-slate-700'"
            >
              <component :is="item.icon" class="w-4 h-4 shrink-0" :class="route.path === item.path ? 'text-emerald-400' : 'text-slate-500'" />
              {{ item.label }}
            </button>
          </div>
        </div>
      </template>
    </Teleport>

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
      <!-- Desktop: Left Menu -->
      <div v-if="!isMobile" class="w-48 shrink-0 border-r border-slate-800 bg-slate-900/30 p-4 overflow-y-auto">
        <nav>
          <div v-for="group in menuGroups" :key="group.label" class="mb-3">
            <p class="px-3 mb-1 text-[10px] font-semibold text-slate-600 tracking-widest uppercase">{{ group.label }}</p>
            <div class="space-y-0.5">
              <router-link
                v-for="item in group.items"
                :key="item.path"
                :to="item.path"
                class="flex items-center gap-2.5 px-3 py-1.5 rounded-lg text-sm transition-colors"
                :class="route.path === item.path
                  ? 'bg-emerald-500/20 text-emerald-400'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'"
              >
                <component :is="item.icon" class="w-4 h-4" />
                {{ item.label }}
              </router-link>
            </div>
          </div>
        </nav>
      </div>

      <!-- Right Content -->
      <div class="flex-1 overflow-auto p-2 sm:p-8">
        <router-view />
      </div>
    </div>
  </div>
</template>
