<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { useWebSocketStore } from './stores/websocket'
import { useThemeStore } from './stores/theme'
import ProjectSidebar from './components/ProjectSidebar.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const ws = useWebSocketStore()
const theme = useThemeStore()

const isLoginPage = computed(() => route.meta.guest === true)

const pageTitles: Record<string, string> = {
  '/dashboard': '项目看板',
  '/files': '文件管理',
  '/agents': 'Agent 池',
  '/tasks': '任务列表',
  '/reviews': '审查记录',
  '/versions': '版本历史',
}

const currentPageTitle = computed(() => pageTitles[route.path] || '')

onMounted(() => {
  if (!isLoginPage.value) ws.connect()
})

onUnmounted(() => {
  ws.disconnect()
})

function handleLogout() {
  ws.disconnect()
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <!-- Login page: full-screen, no chrome -->
  <router-view v-if="isLoginPage" />

  <!-- Main app: sidebar + top bar + content -->
  <div v-else class="app-root">
    <aside class="app-sidebar">
      <div class="sidebar-header">
        <div class="sidebar-logo">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
            <rect x="3" y="7" width="18" height="13" rx="3" fill="var(--primary)"/>
            <rect x="3" y="7" width="18" height="13" rx="3" fill="none" stroke="var(--primary-hover)" stroke-width="1"/>
            <circle cx="8.5" cy="13" r="1.5" fill="#fff"/>
            <circle cx="15.5" cy="13" r="1.5" fill="#fff"/>
            <path d="M9 16.5h6" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/>
            <rect x="9" y="3" width="6" height="4" rx="1.5" fill="var(--primary)"/>
            <circle cx="6" cy="10" r="1" fill="var(--primary)"/>
            <circle cx="18" cy="10" r="1" fill="var(--primary)"/>
          </svg>
        </div>
        <span class="sidebar-title">AgentCollab</span>
      </div>
      <ProjectSidebar />
      <div class="sidebar-footer">
        <div class="sidebar-user">
          <span class="user-avatar">{{ auth.displayName?.charAt(0) || '?' }}</span>
          <div class="user-info">
            <div class="user-name">{{ auth.displayName }}</div>
            <div class="user-role">开发者</div>
          </div>
        </div>
        <button class="logout-btn" title="退出登录" @click="handleLogout">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
        </button>
      </div>
    </aside>

    <div class="app-body">
      <!-- Top bar -->
      <header class="app-topbar">
        <div class="topbar-left">
          <h2 class="topbar-title">{{ currentPageTitle }}</h2>
        </div>
        <div class="topbar-right">
          <button class="topbar-icon-btn" :title="theme.isDark ? '切换到亮色模式' : '切换到暗色模式'" @click="theme.toggleDark()">
            <svg v-if="theme.isDark" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
            <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
          </button>
        </div>
      </header>

      <!-- Content -->
      <main class="app-main">
        <router-view v-slot="{ Component }">
          <transition name="fade-slide" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<style scoped>
.app-root {
  display: flex;
  height: 100vh;
  background: var(--app-shell);
  font-family: var(--font-sans);
  color: var(--foreground);
}

/* ── Sidebar ────────────────────────────────────────────────────── */
.app-sidebar {
  width: 240px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--app-shell);
  border-right: 1px solid var(--surface-border);
  user-select: none;
}

.sidebar-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 18px;
  border-bottom: 1px solid var(--surface-border);
}

.sidebar-logo {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
}

.sidebar-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--foreground);
  letter-spacing: -0.3px;
}

.sidebar-footer {
  margin-top: auto;
  border-top: 1px solid var(--surface-border);
  padding: 12px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.sidebar-user {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
}

.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  background: var(--primary);
  color: var(--primary-foreground);
  font-size: 14px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.user-info {
  min-width: 0;
}

.user-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--foreground);
  line-height: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-role {
  font-size: 11px;
  color: var(--muted-foreground);
  line-height: 1.3;
}

.logout-btn {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  border: none;
  background: transparent;
  color: var(--muted-foreground);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all var(--transition-fast);
}

.logout-btn:hover {
  background: var(--danger-light);
  color: var(--danger);
}

/* ── App body ───────────────────────────────────────────────────── */
.app-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

.app-topbar {
  height: 52px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
  background: var(--surface);
  border-bottom: 1px solid var(--surface-border);
}

.topbar-title {
  font-size: 15px;
  font-weight: 600;
  margin: 0;
  color: var(--foreground);
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

.topbar-icon-btn {
  width: 34px;
  height: 34px;
  border-radius: var(--radius-md);
  border: none;
  background: transparent;
  color: var(--muted-foreground);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--transition-fast);
}

.topbar-icon-btn:hover {
  background: var(--surface-hover);
  color: var(--foreground);
}

/* ── Main content ───────────────────────────────────────────────── */
.app-main {
  flex: 1;
  overflow-y: auto;
  background: var(--page-canvas);
  padding: 24px 28px;
}
</style>
