import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import Kanban from '../views/Kanban.vue'
import CronJobs from '../views/CronJobs.vue'
import CronJobDetail from '../views/CronJobDetail.vue'
import Agents from '../views/Agents.vue'
import Tasks from '../views/Tasks.vue'
import Team from '../views/Team.vue'
import Office from '../views/Office.vue'
import Onboarding from '../views/Onboarding.vue'
import Login from '../views/Login.vue'
import SettingsLayout from '../views/settings/SettingsLayout.vue'
import SettingsGeneral from '../views/settings/SettingsGeneral.vue'
import SettingsTools from '../views/settings/SettingsTools.vue'
import SettingsChannels from '../views/settings/SettingsChannels.vue'
import SettingsProjects from '../views/settings/SettingsProjects.vue'
import SettingsArchive from '../views/settings/SettingsArchive.vue'
import SettingsInvitations from '../views/settings/SettingsInvitations.vue'
import SettingsUpdate from '../views/settings/SettingsUpdate.vue'
import SettingsOneStack from '../views/settings/SettingsOneStack.vue'
import SettingsProjectDetail from '../views/settings/SettingsProjectDetail.vue'
import SettingsTerminal from '../views/settings/SettingsTerminal.vue'
import FileBrowser from '../views/FileBrowser.vue'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/office' },
    { path: '/login', component: Login },
    { path: '/onboarding', component: Onboarding },
    { path: '/office', component: Office },
    { path: '/kanban', component: Kanban, meta: { requiresAuth: true } },
    { path: '/cron', component: CronJobs, meta: { requiresAuth: true } },
    { path: '/cron/:id', component: CronJobDetail, meta: { requiresAuth: true } },
    { path: '/tasks', component: Tasks, meta: { requiresAuth: true } },
    { path: '/files', component: FileBrowser, meta: { requiresAuth: true } },
    { path: '/files/:projectId', component: FileBrowser, meta: { requiresAuth: true } },
    {
      path: '/settings',
      component: SettingsLayout,
      redirect: '/settings/general',
      meta: { requiresAuth: true },
      children: [
        { path: 'general', component: SettingsGeneral },
        { path: 'tools', component: SettingsTools },
        { path: 'channels', component: SettingsChannels },
        { path: 'projects', component: SettingsProjects },
        { path: 'projects/:id', component: SettingsProjectDetail },
        { path: 'invitations', component: SettingsInvitations },
        { path: 'archive', component: SettingsArchive },
        { path: 'team', component: Team },
        { path: 'agents', component: Agents },
        { path: 'status', component: Dashboard },
        { path: 'onestack', component: SettingsOneStack },
        { path: 'update', component: SettingsUpdate },
        { path: 'terminal', component: SettingsTerminal },
      ],
    },
  ],
})

// Navigation guard: 依系統設定決定是否強制登入才能瀏覽
router.beforeEach(async (to) => {
  // /settings 本身不擋（內建密碼閘門）
  if (to.path.startsWith('/settings') || to.path === '/login' || to.path === '/onboarding') {
    return
  }

  if (to.meta.requiresAuth) {
    const auth = useAuthStore()

    // 確保已載入設定
    if (!auth.policyLoaded) {
      await auth.fetchAuthPolicy()
    }

    // 如果開啟路由守衛 → 強制登入
    if (auth.requireLoginToView && !auth.isAuthenticated) {
      return { path: '/settings', query: { redirect: to.fullPath } }
    }
  }
})

export default router
