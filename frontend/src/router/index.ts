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
import SettingsLayout from '../views/settings/SettingsLayout.vue'
import SettingsGeneral from '../views/settings/SettingsGeneral.vue'
import SettingsTools from '../views/settings/SettingsTools.vue'
import SettingsChannels from '../views/settings/SettingsChannels.vue'
import SettingsProjects from '../views/settings/SettingsProjects.vue'
import SettingsArchive from '../views/settings/SettingsArchive.vue'
import SettingsInvitations from '../views/settings/SettingsInvitations.vue'
import SettingsUpdate from '../views/settings/SettingsUpdate.vue'
import SettingsOneStack from '../views/settings/SettingsOneStack.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/office' },
    { path: '/onboarding', component: Onboarding },
    { path: '/kanban', component: Kanban },
    { path: '/cron', component: CronJobs },
    { path: '/cron/:id', component: CronJobDetail },
    { path: '/tasks', component: Tasks },
    { path: '/office', component: Office },
    {
      path: '/settings',
      component: SettingsLayout,
      redirect: '/settings/general',
      children: [
        { path: 'general', component: SettingsGeneral },
        { path: 'tools', component: SettingsTools },
        { path: 'channels', component: SettingsChannels },
        { path: 'projects', component: SettingsProjects },
        { path: 'invitations', component: SettingsInvitations },
        { path: 'archive', component: SettingsArchive },
        { path: 'team', component: Team },
        { path: 'agents', component: Agents },
        { path: 'status', component: Dashboard },
        { path: 'onestack', component: SettingsOneStack },
        { path: 'update', component: SettingsUpdate },
      ],
    },
  ]
})

export default router
