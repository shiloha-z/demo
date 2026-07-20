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

// Auth guard + global loading bar
let _loadingTimer: ReturnType<typeof setTimeout> | null = null

router.beforeEach((to) => {
  // Show loading bar after a short delay (skip flash on instant nav)
  if (_loadingTimer) clearTimeout(_loadingTimer)
  _loadingTimer = setTimeout(() => {
    document.body.classList.add('router-loading')
  }, 200)

  const token = localStorage.getItem('token')
  if (to.meta.guest) {
    if (token) return '/dashboard'
  } else {
    if (!token) return '/login'
  }
})

router.afterEach(() => {
  if (_loadingTimer) clearTimeout(_loadingTimer)
  document.body.classList.remove('router-loading')
})

router.onError(() => {
  if (_loadingTimer) clearTimeout(_loadingTimer)
  document.body.classList.remove('router-loading')
})

export default router
