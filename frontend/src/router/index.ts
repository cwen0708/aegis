import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import Kanban from '../views/Kanban.vue'
import CronJobs from '../views/CronJobs.vue'
import Agents from '../views/Agents.vue'
import Tasks from '../views/Tasks.vue'
import Settings from '../views/Settings.vue'
import Team from '../views/Team.vue'
import Office from '../views/Office.vue'
import Onboarding from '../views/Onboarding.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
    { path: '/onboarding', component: Onboarding },
    { path: '/dashboard', component: Dashboard },
    { path: '/kanban', component: Kanban },
    { path: '/cron', component: CronJobs },
    { path: '/agents', component: Agents },
    { path: '/tasks', component: Tasks },
    { path: '/team', component: Team },
    { path: '/office', component: Office },
    { path: '/settings', component: Settings },
  ]
})

export default router
