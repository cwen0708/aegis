<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Shield, ListTodo, Settings, Clock, FolderOpen, GitBranch, Wifi, WifiOff, Sun, Moon, Zap, Building2, Home, PanelLeftClose, PanelLeftOpen, Rocket } from 'lucide-vue-next'
import { useWebSocket } from './composables/useWebSocket'
import { useResponsive } from './composables/useResponsive'
import { useAegisStore } from './stores/aegis'
import { useDomainStore } from './stores/domain'
import ToastNotification from './components/ToastNotification.vue'

const router = useRouter()
const route = useRoute()
const store = useAegisStore()
const domainStore = useDomainStore()
// 初始化 WebSocket
useWebSocket()

// 響應式檢測（使用共用 composable）
const { isMobile } = useResponsive()


// 側邊欄收起
const sidebarCollapsed = ref(localStorage.getItem('aegis-sidebar') === 'collapsed')
function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem('aegis-sidebar', sidebarCollapsed.value ? 'collapsed' : 'expanded')
}

// 明暗主題
const isDark = ref(localStorage.getItem('aegis-theme') !== 'light')

function toggleTheme() {
  isDark.value = !isDark.value
  localStorage.setItem('aegis-theme', isDark.value ? 'dark' : 'light')
  document.documentElement.classList.toggle('light', !isDark.value)
}

onMounted(() => {
  if (!isDark.value) document.documentElement.classList.add('light')
})

const settingsReady = ref(false)

onMounted(async () => {
  await store.fetchSettings()

  // 解析當前網域 → 決定可見的專案和成員
  const { useDomainStore } = await import('./stores/domain')
  const domainStore = useDomainStore()
  await domainStore.resolve()

  settingsReady.value = true

  // 檢查 onboarding 狀態，未完成則導向
  if (store.settings.onboarding_completed !== 'true' && route.path !== '/onboarding') {
    router.replace('/onboarding')
  }
})

// 系統指標格式化
const cpuBar = computed(() => Math.min(store.systemInfo.cpu_percent, 100))
const memBar = computed(() => Math.min(store.systemInfo.mem_percent, 100))

function barColor(val: number) {
  if (val > 80) return 'bg-red-500'
  if (val > 60) return 'bg-amber-500'
  return 'bg-emerald-500'
}

function navClass(path: string) {
  const active = route.path === path || route.path.startsWith(path + '/')
  return [
    sidebarCollapsed.value ? 'justify-center px-2' : 'px-3',
    active ? 'bg-emerald-500/10 text-emerald-400' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50',
  ]
}

// 手機版底部導航
const mobileNavItems = [
  { path: '/kanban', icon: ListTodo, label: '看板' },
  { path: '/cron', icon: Clock, label: '排程' },
  { path: '/office', icon: Shield, label: 'Aegis', isCenter: true },
  { path: '/tasks', icon: Zap, label: '任務' },
  { path: '/settings', icon: Settings, label: '設定' },
]

function mobileNavClass(path: string) {
  const active = route.path === path || route.path.startsWith(path + '/')
  return active ? 'text-emerald-400' : 'text-slate-500'
}
</script>

<template>
  <div class="h-screen bg-slate-900 text-slate-100 font-sans flex overflow-hidden">

    <!-- Sidebar (Desktop Only) -->
    <aside v-if="!isMobile" :class="sidebarCollapsed ? 'w-14' : 'w-64'" class="bg-slate-800 border-r border-slate-700 flex flex-col transition-all duration-200">
      <!-- Logo Area -->
      <div class="h-16 flex items-center border-b border-slate-700" :class="sidebarCollapsed ? 'justify-center px-2' : 'px-6'">
        <div class="flex items-center gap-2 text-emerald-400">
          <Shield class="w-6 h-6 shrink-0" />
          <span v-if="!sidebarCollapsed" class="font-bold text-xl tracking-tight">Aegis</span>
        </div>
      </div>

      <!-- Menu -->
      <nav class="flex-1 py-4 text-nowrap overflow-y-auto" :class="sidebarCollapsed ? 'px-1.5' : 'px-4'">
        <!-- 總覽 -->
        <div class="space-y-1 mb-2">
          <p v-if="!sidebarCollapsed" class="px-3 text-[10px] font-semibold text-slate-600 tracking-widest uppercase mb-1">總覽</p>
          <router-link v-if="store.settings.onboarding_completed !== 'true'" to="/onboarding" class="w-full flex items-center gap-3 py-2 rounded-lg transition-colors text-sm font-medium" :class="navClass('/onboarding')">
            <Rocket class="w-5 h-5 shrink-0" />
            <span v-if="!sidebarCollapsed" class="flex items-center gap-2">
              設定引導
              <span class="w-2 h-2 rounded-full bg-amber-400 animate-pulse"></span>
            </span>
          </router-link>
          <!-- Dynamic room entries (when domain has rooms) -->
          <template v-if="domainStore.rooms.length > 0">
            <router-link
              v-for="(room, idx) in domainStore.rooms"
              :key="room.id"
              :to="`/office/${room.id}`"
              class="w-full flex items-center gap-3 py-2 rounded-lg transition-colors text-sm font-medium"
              :class="navClass(`/office/${room.id}`)"
            >
              <component :is="idx === 0 ? Home : Building2" class="w-5 h-5 shrink-0" />
              <span v-if="!sidebarCollapsed">{{ room.name }}</span>
            </router-link>
          </template>
          <!-- Fallback: single office entry -->
          <router-link v-else to="/office" class="w-full flex items-center gap-3 py-2 rounded-lg transition-colors text-sm font-medium" :class="navClass('/office')">
            <Building2 class="w-5 h-5 shrink-0" />
            <span v-if="!sidebarCollapsed">{{ store.settings.office_name || '辦公室' }}</span>
          </router-link>
        </div>

        <!-- 工作 -->
        <div class="border-t border-slate-700/40 my-2"></div>
        <div class="space-y-1 mb-2">
          <p v-if="!sidebarCollapsed" class="px-3 text-[10px] font-semibold text-slate-600 tracking-widest uppercase mb-1">工作</p>
          <router-link to="/kanban" class="w-full flex items-center gap-3 py-2 rounded-lg transition-colors text-sm font-medium" :class="navClass('/kanban')">
            <ListTodo class="w-5 h-5 shrink-0" />
            <span v-if="!sidebarCollapsed">專案看板</span>
          </router-link>
          <router-link to="/cron" class="w-full flex items-center gap-3 py-2 rounded-lg transition-colors text-sm font-medium" :class="navClass('/cron')">
            <Clock class="w-5 h-5 shrink-0" />
            <span v-if="!sidebarCollapsed">排程管理</span>
          </router-link>
          <router-link to="/tasks" class="w-full flex items-center gap-3 py-2 rounded-lg transition-colors text-sm font-medium" :class="navClass('/tasks')">
            <Zap class="w-5 h-5 shrink-0" />
            <span v-if="!sidebarCollapsed">運行中任務</span>
          </router-link>
          <router-link to="/files" class="w-full flex items-center gap-3 py-2 rounded-lg transition-colors text-sm font-medium" :class="navClass('/files')">
            <FolderOpen class="w-5 h-5 shrink-0" />
            <span v-if="!sidebarCollapsed">檔案瀏覽</span>
          </router-link>
          <router-link to="/git" class="w-full flex items-center gap-3 py-2 rounded-lg transition-colors text-sm font-medium" :class="navClass('/git')">
            <GitBranch class="w-5 h-5 shrink-0" />
            <span v-if="!sidebarCollapsed">版本控制</span>
          </router-link>
        </div>

        <!-- 管理 -->
        <div class="border-t border-slate-700/40 my-2"></div>
        <div class="space-y-1">
          <p v-if="!sidebarCollapsed" class="px-3 text-[10px] font-semibold text-slate-600 tracking-widest uppercase mb-1">管理</p>
          <router-link to="/settings" class="w-full flex items-center gap-3 py-2 rounded-lg transition-colors text-sm font-medium" :class="navClass('/settings')">
            <Settings class="w-5 h-5 shrink-0" />
            <span v-if="!sidebarCollapsed">系統設定</span>
          </router-link>
        </div>
      </nav>

      <!-- Bottom Fixed: System Status + Collapse Toggle -->
      <div class="border-t border-slate-700" :class="sidebarCollapsed ? 'p-2 pb-2 space-y-2' : 'p-4 pb-2 space-y-3'">
        <template v-if="!sidebarCollapsed">
          <!-- CPU -->
          <div class="flex items-center gap-2">
            <span class="text-[10px] text-slate-500 w-7 shrink-0">CPU</span>
            <div class="flex-1 bg-slate-900 rounded-full h-1.5 overflow-hidden">
              <div :class="barColor(cpuBar)" class="h-1.5 rounded-full transition-all duration-500" :style="{ width: `${cpuBar}%` }"></div>
            </div>
          </div>

          <!-- Memory -->
          <div class="flex items-center gap-2">
            <span class="text-[10px] text-slate-500 w-7 shrink-0">MEM</span>
            <div class="flex-1 bg-slate-900 rounded-full h-1.5 overflow-hidden">
              <div :class="barColor(memBar)" class="h-1.5 rounded-full transition-all duration-500" :style="{ width: `${memBar}%` }"></div>
            </div>
          </div>

          <!-- 工作台 + Theme + Connection + Collapse -->
          <div class="flex items-center gap-1.5">
            <div class="flex items-center gap-1.5 min-w-0 overflow-hidden">
              <div
                v-for="i in store.systemInfo.workstations_total"
                :key="i"
                class="w-5 h-5 shrink-0 rounded border flex items-center justify-center text-[10px] font-bold"
                :class="i <= store.systemInfo.workstations_used
                  ? 'bg-amber-500/20 border-amber-500/30 text-amber-400'
                  : 'bg-slate-900 border-slate-700 text-slate-600'"
              >
                {{ i <= store.systemInfo.workstations_used ? '■' : '□' }}
              </div>
            </div>
            <div class="ml-auto flex items-center gap-1 shrink-0">
              <button
                @click="toggleTheme"
                class="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-colors"
                :title="isDark ? '切換到淺色模式' : '切換到深色模式'"
              >
                <Sun v-if="isDark" class="w-4 h-4" />
                <Moon v-else class="w-4 h-4" />
              </button>
              <Wifi v-if="store.connected" class="w-4 h-4 text-emerald-400 shrink-0" title="已連線" />
              <WifiOff v-else class="w-4 h-4 text-red-400 shrink-0" title="已斷線" />
              <button
                @click="toggleSidebar"
                class="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-700/50 transition-colors"
                title="收起選單"
              >
                <PanelLeftClose class="w-4 h-4" />
              </button>
            </div>
          </div>
        </template>

        <template v-else>
          <!-- Collapsed: connection icon + expand (vertical) -->
          <div class="flex flex-col items-center gap-2">
            <Wifi v-if="store.connected" class="w-4 h-4 text-emerald-400" />
            <WifiOff v-else class="w-4 h-4 text-red-400" />
            <button
              @click="toggleSidebar"
              class="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-700/50 transition-colors"
              title="展開選單"
            >
              <PanelLeftOpen class="w-4 h-4" />
            </button>
          </div>
        </template>
      </div>
    </aside>

    <!-- Main Content -->
    <main class="flex-1 flex flex-col min-w-0 bg-slate-900 relative">
      <!-- Workspace with Background Glow -->
      <div class="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-emerald-900/20 via-slate-900 to-slate-900 pointer-events-none"></div>

      <div class="flex-1 overflow-hidden relative z-0" :class="{ 'pb-14': isMobile }">
        <router-view v-if="settingsReady"></router-view>
      </div>
    </main>

    <!-- Mobile Bottom Navigation -->
    <nav v-if="isMobile" class="fixed bottom-0 left-0 right-0 z-50 bg-slate-800/95 backdrop-blur-lg border-t border-slate-700/50 safe-area-bottom" role="navigation" aria-label="主要導覽">
      <div class="flex items-end justify-around px-2 pt-2 pb-2">
        <template v-for="item in mobileNavItems" :key="item.path">
          <!-- 中央辦公室按鈕（突出） -->
          <router-link
            v-if="item.isCenter"
            :to="item.path"
            class="flex flex-col items-center -mt-6"
            :aria-label="item.label"
            :aria-current="route.path === item.path ? 'page' : undefined"
          >
            <div
              class="w-14 h-14 rounded-full flex items-center justify-center shadow-lg transition-all"
              :class="route.path === item.path
                ? 'bg-emerald-500 text-white shadow-emerald-500/30'
                : 'bg-slate-700 text-slate-300 hover:bg-slate-600'"
            >
              <component :is="item.icon" class="w-7 h-7" aria-hidden="true" />
            </div>
            <span class="text-[10px] mt-1" :class="route.path === item.path ? 'text-emerald-400' : 'text-slate-500'">
              {{ item.label }}
            </span>
          </router-link>

          <!-- 一般導航項目 -->
          <router-link
            v-else
            :to="item.path"
            class="flex flex-col items-center py-1 px-3 min-w-[44px] min-h-[44px]"
            :aria-label="item.label"
            :aria-current="route.path === item.path ? 'page' : undefined"
          >
            <component :is="item.icon" class="w-5 h-5" :class="mobileNavClass(item.path)" aria-hidden="true" />
            <span class="text-[10px] mt-1" :class="mobileNavClass(item.path)">{{ item.label }}</span>
          </router-link>
        </template>
      </div>
    </nav>

    <!-- Toast Notifications -->
    <ToastNotification />
  </div>
</template>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: #334155;
  border-radius: 4px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: #475569;
}
</style>

<!-- Global scrollbar styles -->
<style>
/* 全站捲軸：移除箭頭與底色，只保留滑塊 */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: #475569;
  border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
  background: #64748b;
}
::-webkit-scrollbar-button {
  display: none;
}
::-webkit-scrollbar-corner {
  background: transparent;
}

/* Firefox */
* {
  scrollbar-width: thin;
  scrollbar-color: #475569 transparent;
}

/* Safe area for mobile (iPhone notch/home indicator) */
.safe-area-bottom {
  padding-bottom: env(safe-area-inset-bottom, 0px);
}
</style>
