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
// SettingsTools removed — CLI tools merged into Dashboard (status page)
import SettingsChannels from '../views/settings/SettingsChannels.vue'
import SettingsProjects from '../views/settings/SettingsProjects.vue'
import SettingsArchive from '../views/settings/SettingsArchive.vue'
import SettingsUsers from '../views/settings/SettingsUsers.vue'
import SettingsUpdate from '../views/settings/SettingsUpdate.vue'
import SettingsOneStack from '../views/settings/SettingsOneStack.vue'
import SettingsProjectDetail from '../views/settings/SettingsProjectDetail.vue'
import SettingsTeamDetail from '../views/settings/SettingsTeamDetail.vue'
import SettingsUserDetail from '../views/settings/SettingsUserDetail.vue'
import SettingsTerminal from '../views/settings/SettingsTerminal.vue'
import SettingsRoomDetail from '../views/settings/SettingsRoomDetail.vue'
import FileBrowser from '../views/FileBrowser.vue'
import GitManager from '../views/GitManager.vue'
import RelationGraph from '../views/RelationGraph.vue'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/office' },
    { path: '/login', component: Login },
    { path: '/onboarding', component: Onboarding },
    { path: '/office/:roomId?', name: 'office', component: Office },
    { path: '/kanban', component: Kanban, meta: { requiresAuth: true } },
    { path: '/cron', component: CronJobs, meta: { requiresAuth: true } },
    { path: '/cron/:id', component: CronJobDetail, meta: { requiresAuth: true } },
    { path: '/tasks', component: Tasks, meta: { requiresAuth: true } },
    { path: '/files', component: FileBrowser, meta: { requiresAuth: true } },
    { path: '/files/:projectId', component: FileBrowser, meta: { requiresAuth: true } },
    { path: '/git', component: GitManager, meta: { requiresAuth: true } },
    { path: '/graph', component: RelationGraph, meta: { requiresAuth: true } },
    {
      path: '/settings',
      component: SettingsLayout,
      redirect: '/settings/general',
      meta: { requiresAuth: true },
      children: [
        { path: 'general', component: SettingsGeneral },
        { path: 'tools', redirect: '/settings/status' },
        { path: 'channels', component: SettingsChannels },
        { path: 'channels/telegram', component: () => import('../views/settings/channels/ChannelTelegram.vue') },
        { path: 'channels/line', component: () => import('../views/settings/channels/ChannelLine.vue') },
        { path: 'channels/discord', component: () => import('../views/settings/channels/ChannelDiscord.vue') },
        { path: 'channels/slack', component: () => import('../views/settings/channels/ChannelSlack.vue') },
        { path: 'channels/wecom', component: () => import('../views/settings/channels/ChannelWecom.vue') },
        { path: 'channels/feishu', component: () => import('../views/settings/channels/ChannelFeishu.vue') },
        { path: 'channels/email', component: () => import('../views/settings/channels/ChannelEmail.vue') },
        { path: 'raw-messages', component: () => import('../views/settings/SettingsRawMessages.vue') },
        { path: 'projects', component: SettingsProjects },
        { path: 'projects/:id', component: SettingsProjectDetail },
        { path: 'rooms', component: () => import('../views/settings/SettingsRooms.vue') },
        { path: 'rooms/:id', component: SettingsRoomDetail },
        { path: 'domains', component: () => import('../views/settings/SettingsDomains.vue') },
        { path: 'domains/:id', component: () => import('../views/settings/SettingsDomainDetail.vue') },
        { path: 'users', component: SettingsUsers },
        { path: 'users/:id', component: SettingsUserDetail },
        { path: 'invitations', redirect: '/settings/users' },
        { path: 'archive', component: SettingsArchive },
        { path: 'team', component: Team },
        { path: 'team/:id', component: SettingsTeamDetail },
        { path: 'agents', component: Agents },
        { path: 'status', component: Dashboard },
        { path: 'onestack', component: SettingsOneStack },
        { path: 'update', component: SettingsUpdate },
        { path: 'terminal', component: SettingsTerminal },
      ],
    },
  ],
})

// Navigation guard: 依系統設定決定是否強制登入才能瀏覽 + 網域房間存取控制
router.beforeEach(async (to) => {
  // /settings 本身不擋（內建密碼閘門）
  if (to.path.startsWith('/settings') || to.path === '/login' || to.path === '/onboarding') {
    return
  }

  if (to.meta.requiresAuth) {
    const auth = useAuthStore()
    const { useDomainStore } = await import('../stores/domain')
    const domainStore = useDomainStore()

    // 確保已載入設定
    if (!auth.policyLoaded) {
      await auth.fetchAuthPolicy()
    }

    // 優先使用網域設定，fallback 到全域設定
    const requireLogin = domainStore.resolved && domainStore.domain
      ? domainStore.requireLogin
      : auth.requireLoginToView

    if (requireLogin && !auth.isAuthenticated) {
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }
})

export default router
