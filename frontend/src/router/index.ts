import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('../views/LoginView.vue'),
      meta: { guest: true },
    },
    {
      path: '/',
      redirect: '/dashboard',
    },
    {
      path: '/dashboard',
      name: 'Dashboard',
      component: () => import('../views/DashboardView.vue'),
    },
    {
      path: '/risk-dashboard',
      name: 'RiskDashboard',
      component: () => import('../views/RiskDashboardView.vue'),
    },
    {
      path: '/files',
      name: 'FileManager',
      component: () => import('../views/FileManagerView.vue'),
    },
    {
      path: '/agents',
      name: 'AgentPanel',
      component: () => import('../views/AgentPanelView.vue'),
    },
    {
      path: '/tasks',
      name: 'TaskList',
      component: () => import('../views/TaskListView.vue'),
    },
    {
      path: '/reviews',
      name: 'DiffReview',
      component: () => import('../views/DiffReviewView.vue'),
    },
    {
      path: '/versions',
      name: 'VersionHistory',
      component: () => import('../views/VersionHistoryView.vue'),
    },
    {
      path: '/profile',
      name: 'Profile',
      component: () => import('../views/ProfileView.vue'),
    },
    {
      path: '/settings',
      name: 'Settings',
      component: () => import('../views/SettingsView.vue'),
    },
    {
      path: '/messages',
      name: 'Messages',
      component: () => import('../views/MessagesView.vue'),
    },
    {
      path: '/skills',
      name: 'SkillRepository',
      component: () => import('../views/SkillRepositoryView.vue'),
    },
    {
      path: '/audit',
      name: 'AuditCenter',
      component: () => import('../views/AuditLogView.vue'),
    },
  ],
})

// Auth guard
router.beforeEach((to) => {
  const token = localStorage.getItem('token')
  if (to.meta.guest) {
    // Already logged in → go to dashboard
    if (token) return '/dashboard'
  } else {
    // Not logged in → go to login
    if (!token) return '/login'
  }
})

export default router
