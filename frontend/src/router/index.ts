import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '../views/LoginView.vue'
import DashboardView from '../views/DashboardView.vue'
import RiskDashboardView from '../views/RiskDashboardView.vue'
import FileManagerView from '../views/FileManagerView.vue'
import AgentPanelView from '../views/AgentPanelView.vue'
import TaskListView from '../views/TaskListView.vue'
import DiffReviewView from '../views/DiffReviewView.vue'
import VersionHistoryView from '../views/VersionHistoryView.vue'
import ProfileView from '../views/ProfileView.vue'
import SettingsView from '../views/SettingsView.vue'
import MessagesView from '../views/MessagesView.vue'
import SkillRepositoryView from '../views/SkillRepositoryView.vue'
import AuditLogView from '../views/AuditLogView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: LoginView,
      meta: { guest: true },
    },
    {
      path: '/',
      redirect: '/dashboard',
    },
    {
      path: '/dashboard',
      name: 'Dashboard',
      component: DashboardView,
    },
    {
      path: '/risk-dashboard',
      name: 'RiskDashboard',
      component: RiskDashboardView,
    },
    {
      path: '/files',
      name: 'FileManager',
      component: FileManagerView,
    },
    {
      path: '/agents',
      name: 'AgentPanel',
      component: AgentPanelView,
    },
    {
      path: '/tasks',
      name: 'TaskList',
      component: TaskListView,
    },
    {
      path: '/reviews',
      name: 'DiffReview',
      component: DiffReviewView,
    },
    {
      path: '/versions',
      name: 'VersionHistory',
      component: VersionHistoryView,
    },
    {
      path: '/profile',
      name: 'Profile',
      component: ProfileView,
    },
    {
      path: '/settings',
      name: 'Settings',
      component: SettingsView,
    },
    {
      path: '/messages',
      name: 'Messages',
      component: MessagesView,
    },
    {
      path: '/skills',
      name: 'SkillRepository',
      component: SkillRepositoryView,
    },
    {
      path: '/audit',
      name: 'AuditCenter',
      component: AuditLogView,
    },
  ],
})

router.beforeEach((to) => {
  const token = localStorage.getItem('token')
  if (to.meta.guest) {
    if (token) return '/dashboard'
  } else {
    if (!token) return '/login'
  }
})

export default router
