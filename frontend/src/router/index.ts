import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
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
      path: '/reviews',
      name: 'DiffReview',
      component: () => import('../views/DiffReviewView.vue'),
    },
    {
      path: '/versions',
      name: 'VersionHistory',
      component: () => import('../views/VersionHistoryView.vue'),
    },
  ],
})

export default router
