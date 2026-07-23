<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { useWebSocketStore } from './stores/websocket'
import { useThemeStore } from './stores/theme'
import { useProjectStore } from './stores/project'
import { useNotificationStore } from './stores/notification'
import { useMessageStore } from './stores/message'
import ProjectSidebar from './components/ProjectSidebar.vue'
import ChatSidebar from './components/ChatSidebar.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const ws = useWebSocketStore()
const theme = useThemeStore()
const projectStore = useProjectStore()

const isLoginPage = computed(() => route.meta.guest === true)
const chatVisible = ref(false)
const notifStore = useNotificationStore()
const msgStore = useMessageStore()
const sidebarCollapsed = ref(false)
let pollNotifTimer: ReturnType<typeof setInterval> | null = null
const showUserMenu = ref(false)

function toggleUserMenu() {
  showUserMenu.value = !showUserMenu.value
}

function closeUserMenu() {
  showUserMenu.value = false
}

const pageTitles: Record<string, string> = {
  '/dashboard': '项目看板',
  '/files': '文件管理',
  '/agents': 'Agent 池',
  '/tasks': '任务列表',
  '/reviews': '审查记录',
  '/versions': '版本历史',
  '/risk-dashboard': '风险驾驶舱',
  '/skills': '技能仓库',
  '/settings': '系统设置',
}

const currentPageTitle = computed(() => pageTitles[route.path] || '')

let unsubProject: (() => void) | null = null

async function refreshProjects() {
  const currentId = projectStore.currentProject?.id
  try {
    await Promise.all([projectStore.fetchProjects(), projectStore.fetchSwitchableProjects()])
    if (currentId) {
      projectStore.setCurrentProject(projectStore.switchableProjects.find(p => p.id === currentId) || null)
    }
  } catch { /* backend may be restarting */ }
}

function joinCurrentProject() {
  if (ws.connected && projectStore.currentProject?.id) {
    ws.send(JSON.stringify({ type: 'join_project', project_id: projectStore.currentProject.id }))
  }
}

onMounted(() => {
  if (!isLoginPage.value) ws.connect()
  unsubProject = ws.on('project_update', refreshProjects)
  // Initial notification count + periodic polling fallback
  msgStore.refresh()
  pollNotifTimer = setInterval(() => msgStore.refresh(), 30_000)
  // Refresh on WebSocket reconnect to catch missed messages
  watch(() => ws.connected, (ok) => { if (ok) msgStore.refresh() })
})

// App stays mounted across login/logout, so connect after navigation instead
// of relying solely on the initial mount state.
watch(isLoginPage, (isLogin) => {
  if (isLogin) ws.disconnect()
  else ws.connect()
})

watch([() => ws.connected, () => projectStore.currentProject?.id], joinCurrentProject, { immediate: true })

onUnmounted(() => {
  unsubProject?.()
  ws.disconnect()
  if (pollNotifTimer) { clearInterval(pollNotifTimer); pollNotifTimer = null }
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
    <aside class="app-sidebar" :class="{ collapsed: sidebarCollapsed }">
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
        <button
          class="sidebar-collapse-btn"
          :title="sidebarCollapsed ? '展开侧栏' : '折叠侧栏'"
          @click="sidebarCollapsed = !sidebarCollapsed"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg>
        </button>
      </div>

      <!-- Content wrapper — fades smoothly during collapse -->
      <div class="sidebar-body">
        <ProjectSidebar :collapsed="sidebarCollapsed" />
      </div>

      <!-- Footer — always clickable, user info fades on collapse -->
      <div class="sidebar-footer">
        <div class="sidebar-user" @click="toggleUserMenu">
          <img v-if="auth.avatarUrl" :src="auth.avatarUrl" class="user-avatar-img" />
          <span v-else class="user-avatar">{{ auth.displayName?.charAt(0) || '?' }}</span>
          <div class="user-info">
            <div class="user-name">{{ auth.displayName }}</div>
            <div class="user-role">开发者</div>
          </div>
          <svg class="user-menu-arrow" :class="{ open: showUserMenu }" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
        </div>

        <!-- Dropdown menu -->
        <Teleport to="body">
          <div v-if="showUserMenu" class="user-menu-backdrop" @click="closeUserMenu" />
        </Teleport>
        <div v-if="showUserMenu" class="user-dropdown">
          <button class="user-dropdown-item" @click="closeUserMenu(); router.push('/profile')">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            <span>个人资料设置</span>
          </button>
          <button class="user-dropdown-item" @click="closeUserMenu(); router.push('/settings')">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
            <span>系统设置</span>
          </button>
          <div class="user-dropdown-divider"></div>
          <button class="user-dropdown-item danger" @click="handleLogout">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
            <span>退出登录</span>
          </button>
        </div>
      </div>
    </aside>

    <div class="app-body" :class="{ 'chat-open': chatVisible }">
      <!-- Top bar -->
      <header class="app-topbar">
        <div class="topbar-left">
          <h2 class="topbar-title">{{ currentPageTitle }}</h2>
        </div>
        <div class="topbar-right">
          <button
            class="topbar-icon-btn notif-toggle-btn"
            :title="`通知 (${notifStore.total})`"
            @click="router.push('/messages')"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
            <span class="notif-badge" v-if="notifStore.total > 0">{{ notifStore.total > 99 ? '99+' : notifStore.total }}</span>
          </button>
          <button
            class="topbar-icon-btn chat-toggle-btn"
            :title="chatVisible ? '关闭聊天' : '打开聊天'"
            @click="chatVisible = !chatVisible; if (chatVisible) notifStore.resetChatUnread()"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          </button>
          <button class="topbar-icon-btn" :title="theme.isDark ? '切换到亮色模式' : '切换到暗色模式'" @click="theme.toggleDark()">
            <svg v-if="theme.isDark" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
            <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
          </button>
        </div>
      </header>

      <!-- Content -->
      <main class="app-main">
        <router-view v-slot="{ Component, route: routerRoute }">
          <transition name="fade-slide" mode="out-in">
            <component :is="Component" :key="routerRoute.fullPath" />
          </transition>
        </router-view>
      </main>
    </div>

    <ChatSidebar v-model:visible="chatVisible" @unread-count="notifStore.incrementChatUnread()" />
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
  transition: width 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}

.app-sidebar.collapsed {
  width: 56px;
}

/* ── Sidebar header ────────────────────────────────────────────── */
.sidebar-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 18px;
  border-bottom: 1px solid var(--surface-border);
  flex-shrink: 0;
  min-height: 57px;
}

.sidebar-logo {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  transition: opacity 0.2s ease;
}

.sidebar-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--foreground);
  letter-spacing: -0.3px;
  white-space: nowrap;
  transition: opacity 0.2s ease;
}

.app-sidebar.collapsed .sidebar-header {
  padding: 12px 0;
  justify-content: center;
  gap: 0;
}

.app-sidebar.collapsed .sidebar-logo,
.app-sidebar.collapsed .sidebar-title {
  opacity: 0;
  pointer-events: none;
  position: absolute;
}

.sidebar-collapse-btn {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  border: none;
  background: transparent;
  color: var(--muted-foreground);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: opacity var(--transition-fast), background var(--transition-fast), color var(--transition-fast);
  opacity: 0.45;
}

.app-sidebar:not(.collapsed) .sidebar-collapse-btn {
  margin-left: auto;
}

.sidebar-collapse-btn:hover,
.app-sidebar:not(.collapsed):hover .sidebar-collapse-btn,
.app-sidebar.collapsed .sidebar-collapse-btn {
  opacity: 1;
}

.sidebar-collapse-btn:hover {
  background: var(--surface-hover);
  color: var(--foreground);
}

/* ── Sidebar body ──────────────────────────────────────────────── */
.sidebar-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

.sidebar-footer {
  margin-top: auto;
  border-top: 1px solid var(--surface-border);
  position: relative;
  flex-shrink: 0;
  min-width: 0;
}

.sidebar-user {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 12px 14px;
  cursor: pointer;
  transition: background var(--transition-fast), padding 0.25s cubic-bezier(0.4, 0, 0.2, 1), gap 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.sidebar-user:hover {
  background: var(--surface-hover);
}

.app-sidebar.collapsed .sidebar-user {
  justify-content: center;
  padding: 12px 0;
  gap: 0;
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

.user-avatar-img {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  object-fit: cover;
  flex-shrink: 0;
}

.user-info {
  min-width: 0;
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  transition: opacity 0.2s ease, flex 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.app-sidebar.collapsed .user-info {
  opacity: 0;
  pointer-events: none;
  flex: 0;
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

.user-menu-arrow {
  flex-shrink: 0;
  color: var(--muted-foreground);
  transition: transform var(--transition-fast), opacity 0.2s ease;
}

.user-menu-arrow.open {
  transform: rotate(180deg);
}

.app-sidebar.collapsed .user-menu-arrow {
  opacity: 0;
  pointer-events: none;
}

/* ── User dropdown ─────────────────────────────────────────────── */
.user-menu-backdrop {
  position: fixed;
  inset: 0;
  z-index: 99;
}

.user-dropdown {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 10px;
  right: 10px;
  background: var(--surface);
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-md);
  box-shadow: 0 8px 24px rgba(0,0,0,0.14);
  z-index: 100;
  padding: 6px;
  display: flex;
  flex-direction: column;
}

.user-dropdown-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border: none;
  background: transparent;
  color: var(--foreground);
  font-size: 13px;
  font-family: var(--font-sans);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: all var(--transition-fast);
  text-align: left;
}

.user-dropdown-item:hover {
  background: var(--surface-hover);
}

.user-dropdown-item.danger {
  color: var(--danger);
}

.user-dropdown-item.danger:hover {
  background: var(--danger-light);
}

.user-dropdown-divider {
  height: 1px;
  background: var(--surface-border);
  margin: 4px 0;
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

.chat-toggle-btn {
  position: relative;
}
.notif-toggle-btn {
  position: relative;
}
.notif-badge {
  position: absolute;
  top: 2px; right: 2px;
  min-width: 16px; height: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: var(--danger);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  line-height: 16px;
  text-align: center;
  pointer-events: none;
}

/* ── Main content ───────────────────────────────────────────────── */
.app-main {
  flex: 1;
  overflow-y: auto;
  background: var(--page-canvas);
  padding: 24px 28px;
}
</style>
