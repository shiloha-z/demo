<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { useWebSocketStore } from './stores/websocket'
import { useThemeStore, COLOR_THEME_OPTIONS } from './stores/theme'
import { useProjectStore } from './stores/project'
import { useNotificationStore } from './stores/notification'
import { useMessageStore } from './stores/message'
import { playSystemDing } from './utils/notificationSound'
import ProjectSidebar from './components/ProjectSidebar.vue'
import ChatSidebar from './components/ChatSidebar.vue'
import GlobalLoadingBar from './components/GlobalLoadingBar.vue'
import NotificationDropdown from './components/NotificationDropdown.vue'


const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const ws = useWebSocketStore()
const theme = useThemeStore()
const projectStore = useProjectStore()

const isLoginPage = computed(() => route.meta.guest === true)
const chatVisible = ref(false)
const notifDropdownVisible = ref(false)
const notifStore = useNotificationStore()
const msgStore = useMessageStore()
const sidebarCollapsed = ref(false)
const mobileSidebarOpen = ref(false)
const appMainRef = ref<HTMLElement | null>(null)
const pageScrollPositions = new Map<string, number>()
let pollNotifTimer: ReturnType<typeof setInterval> | null = null
const showUserMenu = ref(false)
const showColorMenu = ref(false)

function toggleUserMenu() {
  showUserMenu.value = !showUserMenu.value
}

function closeUserMenu() {
  showUserMenu.value = false
}

function toggleColorMenu() {
  showColorMenu.value = !showColorMenu.value
}

function closeColorMenu() {
  showColorMenu.value = false
}

function selectColorTheme(key: string) {
  theme.setColorTheme(key as any)
  closeColorMenu()
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
  '/profile': '个人资料',
  '/messages': '消息中心',
  '/audit': '审计中心',
}

const currentPageTitle = computed(() => pageTitles[route.path] || '')
const focusedChatMessageId = computed(() => {
  const id = Number(route.query.message_id)
  return Number.isFinite(id) && id > 0 ? id : null
})

let unsubProject: (() => void) | null = null
let unsubMessage: (() => void) | null = null

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

const selectedProjectId = computed<number | null>({
  get: () => projectStore.currentProject?.id ?? null,
  set: (id: number | null) => {
    const p = projectStore.switchableProjects.find(p => p.id === id) || null
    projectStore.setCurrentProject(p)
  },
})

function toggleChat() {
  chatVisible.value = !chatVisible.value
}

const currentColorTheme = computed(() =>
  COLOR_THEME_OPTIONS.find(t => t.key === theme.colorTheme) ?? COLOR_THEME_OPTIONS[0],
)

onMounted(() => {
  if (!isLoginPage.value) ws.connect()
  unsubProject = ws.on('project_update', refreshProjects)
  unsubMessage = ws.on('message_new', (message) => {
    msgStore.receive(message)
    void msgStore.refresh()
    playSystemDing()
  })
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

watch(() => route.query.project_id, async (rawProjectId) => {
  if (isLoginPage.value) return
  const projectId = Number(rawProjectId)
  if (!projectId || projectStore.currentProject?.id === projectId) return
  let project = projectStore.switchableProjects.find(item => item.id === projectId)
  if (!project) {
    try {
      await projectStore.fetchSwitchableProjects()
      project = projectStore.switchableProjects.find(item => item.id === projectId)
    } catch {
      return
    }
  }
  if (project) projectStore.setCurrentProject(project)
}, { immediate: true })

watch(() => route.query.open_chat, (openChat) => {
  if (openChat === 'team' || openChat === 'dm') chatVisible.value = true
}, { immediate: true })

watch([() => ws.connected, () => projectStore.currentProject?.id], joinCurrentProject, { immediate: true })

// Close notification dropdown on route change
watch(() => route.fullPath, () => {
  notifDropdownVisible.value = false
  mobileSidebarOpen.value = false
  showUserMenu.value = false
})

watch(() => route.name, async (nextName, previousName) => {
  const scroller = appMainRef.value
  if (!scroller) return
  if (previousName) {
    pageScrollPositions.set(String(previousName), scroller.scrollTop)
  }
  await nextTick()
  scroller.scrollTop = nextName
    ? (pageScrollPositions.get(String(nextName)) ?? 0)
    : 0
})

onUnmounted(() => {
  unsubProject?.()
  unsubMessage?.()
  ws.disconnect()
  if (pollNotifTimer) { clearInterval(pollNotifTimer); pollNotifTimer = null }
})

function handleLogout() {
  ws.disconnect()
  msgStore.reset()
  notifStore.resetChatUnread()
  auth.logout()
  router.push('/login')
}
</script>

<template>  <GlobalLoadingBar />

  <!-- Login page: full-screen, no chrome -->
  <router-view v-if="isLoginPage" />

  <!-- Main app: sidebar + top bar + content -->
  <div v-else class="app-root">
    <Transition name="overlay-fade">
      <button
        v-if="mobileSidebarOpen"
        class="mobile-sidebar-backdrop"
        aria-label="关闭导航"
        @click="mobileSidebarOpen = false"
      />
    </Transition>
    <aside class="app-sidebar" :class="{ collapsed: sidebarCollapsed, 'mobile-open': mobileSidebarOpen }">
      <div class="sidebar-header">
        <div class="sidebar-logo">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
            <rect x="3" y="7" width="18" height="13" rx="3" fill="#fff"/>
            <circle cx="8.5" cy="13" r="1.5" fill="var(--primary)"/>
            <circle cx="15.5" cy="13" r="1.5" fill="var(--primary)"/>
            <path d="M9 16.5h6" stroke="var(--primary)" stroke-width="1.5" stroke-linecap="round"/>
            <rect x="9" y="3" width="6" height="4" rx="1.5" fill="#fff"/>
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
          <img
            v-if="auth.avatarUrl"
            v-image-loading="auth.avatarUrl"
            :src="auth.avatarUrl"
            class="user-avatar-img"
          />
          <span v-else class="user-avatar">{{ auth.displayName?.charAt(0) || '?' }}</span>
          <div class="user-info">
            <div class="user-name">{{ auth.displayName }}</div>
            <div class="user-role">开发者</div>
          </div>
          <svg class="user-menu-arrow" :class="{ open: showUserMenu }" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
        </div>

        <!-- Dropdown menu — teleported to body so it escapes the sidebar stacking context -->
        <Teleport to="body">
          <Transition name="overlay-fade">
            <div v-if="showUserMenu" class="user-menu-backdrop" @click="closeUserMenu" />
          </Transition>
          <Transition name="menu-pop">
            <div v-if="showUserMenu" class="user-dropdown">
              <button class="user-dropdown-item" @click="closeUserMenu(); router.push('/profile')">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                <span>个人资料设置</span>
              </button>
              <button class="user-dropdown-item" @click="closeUserMenu(); router.push('/settings')">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09A1.65 1.65 0 0 0 19.4 15z"/></svg>
                <span>系统设置</span>
              </button>
              <div class="user-dropdown-divider"></div>
              <button class="user-dropdown-item danger" @click="handleLogout">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
                <span>退出登录</span>
              </button>
            </div>
          </Transition>
        </Teleport>
      </div>
    </aside>

    <div class="app-body" :class="{ 'chat-open': chatVisible }">
      <!-- Top bar -->
      <header class="app-topbar">
        <div class="topbar-left">
          <button
            class="topbar-icon-btn mobile-menu-btn"
            aria-label="打开导航"
            @click="sidebarCollapsed = false; mobileSidebarOpen = true"
          >
            <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/></svg>
          </button>
          <h2 class="topbar-title">{{ currentPageTitle }}</h2>
        </div>
        <div class="topbar-center">
          <t-select
            v-model="selectedProjectId"
            class="topbar-project-select"
            placeholder="选择项目…"
            borderless
            :popup-props="{ overlayClassName: 'project-select-popup' }"
          >
            <t-option
              v-for="p in projectStore.switchableProjects"
              :key="p.id"
              :value="p.id"
              :label="p.name"
            />
          </t-select>
        </div>
        <div class="topbar-right">
          <button
            class="topbar-icon-btn"
            :class="{ 'is-active': showColorMenu }"
            :title="`主题色：${currentColorTheme.label}`"
            @click="toggleColorMenu"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 0 20"/><line x1="12" y1="2" x2="12" y2="22"/></svg>
            <span class="indicator-dot" :style="{ background: `linear-gradient(135deg, ${currentColorTheme.colors[0]}, ${currentColorTheme.colors[1]})` }"></span>
          </button>
          <Teleport to="body">
            <Transition name="overlay-fade">
              <div v-if="showColorMenu" class="color-menu-backdrop" @click="closeColorMenu" />
            </Transition>
            <Transition name="menu-pop">
              <div v-if="showColorMenu" class="color-menu">
                <div class="color-menu-header">主题色</div>
                <button
                  v-for="opt in COLOR_THEME_OPTIONS"
                  :key="opt.key"
                  class="color-menu-item"
                  :class="{ active: theme.colorTheme === opt.key }"
                  @click="selectColorTheme(opt.key)"
                >
                  <span class="color-swatch" :style="{ background: `linear-gradient(135deg, ${opt.colors[0]}, ${opt.colors[1]})` }"></span>
                  <span class="color-label">{{ opt.label }}</span>
                  <svg v-if="theme.colorTheme === opt.key" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                </button>
              </div>
            </Transition>
          </Teleport>
          <button class="topbar-icon-btn" :title="theme.isDark ? '切换到亮色模式' : '切换到暗色模式'" @click="theme.toggleDark()">
            <svg v-if="theme.isDark" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
            <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
          </button>
          <button
            class="topbar-icon-btn"
            :class="{ 'is-active': notifDropdownVisible }"
            :title="`通知 (${msgStore.unreadCount})`"
            @click="notifDropdownVisible = !notifDropdownVisible"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
            <span class="badge-dot" v-if="msgStore.unreadCount > 0">{{ msgStore.unreadCount > 99 ? '99+' : msgStore.unreadCount }}</span>
          </button>
          <button
            class="topbar-icon-btn"
            :class="{ 'is-active': chatVisible }"
            :title="chatVisible ? '关闭聊天' : `打开聊天 (${notifStore.chatUnread})`"
            @click="toggleChat"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            <span class="badge-dot" v-if="notifStore.chatUnread > 0">{{ notifStore.chatUnread > 99 ? '99+' : notifStore.chatUnread }}</span>
          </button>
        </div>
      </header>

      <!-- Content -->
      <main ref="appMainRef" class="app-main">
        <router-view v-slot="{ Component, route: routerRoute }">
          <transition name="fade-slide" mode="out-in">
            <!-- Cache route instances by page, not by full URL. Query-string
                 changes (for example review_id) no longer destroy editors,
                 filters, selections, and already loaded data. -->
            <KeepAlive :max="12">
              <component
                :is="Component"
                :key="routerRoute.name || routerRoute.path"
              />
            </KeepAlive>
          </transition>
        </router-view>
      </main>
    </div>

    <ChatSidebar
      v-model:visible="chatVisible"
      :focus-message-id="focusedChatMessageId"
      @unread-count="notifStore.incrementChatUnread"
      @conversation-viewed="notifStore.clearChatUnread"
    />
    <NotificationDropdown :visible="notifDropdownVisible" @close="notifDropdownVisible = false" />
  </div>
</template>

<style scoped>
.app-root {
  display: flex;
  height: 100vh;
  background: var(--app-shell);
  font-family: var(--font-sans);
  color: var(--foreground);
  position: relative;
  overflow: hidden;
}

/* Decorative gradient orbs — sit behind glass panels so backdrop-filter
   has something to blur.  Subtle enough to stay out of the way. */
.app-root::before {
  content: '';
  position: fixed;
  inset: -5%;
  z-index: 0;
  pointer-events: none;
  background:
    radial-gradient(ellipse 80% 60% at 15% 20%, var(--primary-light), transparent 60%),
    radial-gradient(ellipse 60% 70% at 85% 75%, oklch(0.62 0.18 200 / 0.06), transparent 55%),
    radial-gradient(ellipse 50% 50% at 50% 50%, oklch(0.58 0.1 320 / 0.04), transparent 50%);
  animation: ambient-drift 18s var(--motion-ease-standard) infinite alternate;
  will-change: transform;
}
.dark .app-root::before {
  background:
    radial-gradient(ellipse 80% 60% at 15% 20%, var(--primary-light), transparent 60%),
    radial-gradient(ellipse 60% 70% at 85% 75%, oklch(0.68 0.16 200 / 0.10), transparent 55%),
    radial-gradient(ellipse 50% 50% at 50% 50%, oklch(0.6 0.08 320 / 0.06), transparent 50%);
}

.app-root::after {
  content: '';
  position: fixed;
  inset: -8%;
  z-index: 0;
  pointer-events: none;
  background:
    radial-gradient(circle 180px at 9% 15%, var(--ambient-spot-primary) 0 12%, transparent 72%),
    radial-gradient(circle 150px at 43% 8%, var(--ambient-spot-cyan) 0 10%, transparent 72%),
    radial-gradient(circle 210px at 76% 34%, var(--ambient-spot-violet) 0 13%, transparent 74%),
    radial-gradient(circle 170px at 91% 78%, var(--ambient-spot-warm) 0 11%, transparent 72%),
    radial-gradient(circle 130px at 32% 86%, var(--ambient-spot-primary) 0 9%, transparent 74%);
  filter: blur(7px) saturate(1.2);
  opacity: 0.86;
  animation: ambient-spots 22s var(--motion-ease-standard) infinite alternate;
  will-change: transform;
}

@keyframes ambient-drift {
  from { transform: translate3d(-1.2%, -0.8%, 0) scale(1); }
  to { transform: translate3d(1.2%, 0.8%, 0) scale(1.025); }
}

@keyframes ambient-spots {
  from { transform: translate3d(-1.5%, 0, 0) scale(0.99); }
  to { transform: translate3d(1.5%, 1%, 0) scale(1.035); }
}

/* ── Sidebar ────────────────────────────────────────────────────── */
.app-sidebar {
  width: 240px;
  flex-shrink: 0;
  position: relative;
  z-index: 100;
  display: flex;
  flex-direction: column;
  background: color-mix(in oklch, var(--sidebar-bg) 74%, transparent);
  -webkit-backdrop-filter: blur(var(--glass-blur-lg)) saturate(var(--glass-saturate));
  backdrop-filter: blur(var(--glass-blur-lg)) saturate(var(--glass-saturate));
  border-right: 1px solid var(--glass-border);
  box-shadow: var(--glass-highlight);
  user-select: none;
  transition: width var(--motion-slow) var(--motion-ease-standard);
  will-change: width;
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
  transition:
    padding var(--motion-slow) var(--motion-ease-standard),
    gap var(--motion-slow) var(--motion-ease-standard);
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
  transition:
    opacity var(--motion-base) var(--motion-ease-standard),
    max-width var(--motion-slow) var(--motion-ease-standard),
    margin var(--motion-slow) var(--motion-ease-standard),
    padding var(--motion-slow) var(--motion-ease-standard),
    transform var(--motion-base) var(--motion-ease-spring),
    box-shadow var(--transition-base);
  border-radius: 10px;
  background: var(--primary-gradient);
  box-shadow: 0 7px 18px var(--primary-glow);
}

.sidebar-header:hover .sidebar-logo {
  transform: rotate(-4deg) scale(1.06);
  box-shadow: 0 10px 24px var(--primary-glow);
}

.sidebar-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--foreground);
  letter-spacing: -0.3px;
  white-space: nowrap;
  transition:
    opacity var(--motion-base) var(--motion-ease-standard),
    max-width var(--motion-slow) var(--motion-ease-standard),
    margin var(--motion-slow) var(--motion-ease-standard),
    padding var(--motion-slow) var(--motion-ease-standard);
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
  max-width: 0;
  overflow: hidden;
  margin: 0;
  padding: 0;
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
  transition:
    background-color var(--transition-fast),
    padding var(--motion-slow) var(--motion-ease-standard),
    gap var(--motion-slow) var(--motion-ease-standard);
}

.sidebar-user:hover {
  background: var(--surface-hover);
}

.app-sidebar.collapsed .sidebar-user {
  justify-content: center;
  padding: 12px 0;
  gap: 0;
  position: relative;
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
  transition:
    opacity var(--motion-base) var(--motion-ease-standard),
    flex var(--motion-slow) var(--motion-ease-standard);
}

.app-sidebar.collapsed .user-info {
  opacity: 0;
  pointer-events: none;
  position: absolute;
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
  transition:
    transform var(--transition-fast),
    opacity var(--motion-base) var(--motion-ease-standard);
}

.user-menu-arrow.open {
  transform: rotate(180deg);
}

.app-sidebar.collapsed .user-menu-arrow {
  opacity: 0;
  pointer-events: none;
  position: absolute;
}

/* ── User dropdown ─────────────────────────────────────────────── */
.user-menu-backdrop {
  position: fixed;
  inset: 0;
  z-index: 99;
  background: rgba(15, 23, 42, 0.08);
  -webkit-backdrop-filter: blur(3px);
  backdrop-filter: blur(3px);
}

.user-dropdown {
  position: fixed;
  bottom: 80px;
  left: 16px;
  width: 220px;
  background: var(--glass-surface-strong);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-menu), var(--glass-highlight);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  z-index: 9999;
  padding: 6px;
  display: flex;
  flex-direction: column;
  transform-origin: left bottom;
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
  transition:
    background-color var(--transition-fast),
    color var(--transition-fast);
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
  position: relative;
  z-index: 1;
}

.app-topbar {
  height: 60px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
  position: relative;
  background: var(--glass-surface);
  -webkit-backdrop-filter: blur(var(--glass-blur-lg)) saturate(var(--glass-saturate));
  backdrop-filter: blur(var(--glass-blur-lg)) saturate(var(--glass-saturate));
  border-bottom: 1px solid var(--glass-border);
  box-shadow: var(--glass-highlight);
}

.topbar-title {
  font-size: 15px;
  font-weight: 680;
  margin: 0;
  color: var(--foreground);
  letter-spacing: -0.2px;
}

.topbar-left {
  flex: 1 1 0;
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.topbar-center {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  min-width: 0;
  margin: 0 8px;
}
.topbar-project-select {
  max-width: 200px; min-width: 120px;
}
.topbar-project-select :deep(.t-input) {
  border: none !important;
  background: transparent !important;
  box-shadow: none !important;
  padding: 0 !important;
  font-size: 13px; font-weight: 600;
  color: var(--primary);
  height: auto; min-height: 0;
  cursor: pointer;
}
.topbar-project-select :deep(.t-input__inner) {
  font-size: 13px; font-weight: 600;
  color: var(--primary);
  cursor: pointer;
  padding: 2px 22px 2px 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.topbar-project-select :deep(.t-input__prefix),
.topbar-project-select :deep(.t-tag) {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.topbar-project-select :deep(.t-input__suffix) { opacity: 0.6; }

.topbar-right {
  flex: 1 1 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  min-width: 0;
}

/* ── Unified topbar icon buttons ──────────────────────────────────── */
.topbar-icon-btn {
  position: relative;
  width: 34px; height: 34px;
  border-radius: var(--radius-md);
  border: none;
  background: transparent;
  color: var(--muted-foreground);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition:
    background-color var(--transition-fast),
    color var(--transition-fast),
    transform 0.22s var(--motion-ease-spring);
}
.topbar-icon-btn svg {
  transition: transform 0.22s var(--motion-ease-spring);
}
.topbar-icon-btn:hover {
  background: var(--surface-hover);
  color: var(--foreground);
}
.topbar-icon-btn:hover svg {
  transform: scale(1.12);
}
/* Active / toggled-on highlight */
.topbar-icon-btn.is-active {
  color: var(--primary) !important;
  background: var(--primary-light) !important;
  box-shadow: inset 0 0 0 1px color-mix(in oklch, var(--primary) 16%, transparent);
}
/* Shared badge — notification + chat count */
.topbar-icon-btn .badge-dot {
  position: absolute;
  top: 1px; right: 1px;
  min-width: 16px; height: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: var(--danger);
  color: #fff;
  font-size: 10px; font-weight: 700;
  line-height: 16px; text-align: center;
  pointer-events: none;
  transform-origin: center;
  animation: badge-pop 320ms var(--motion-ease-spring) both;
}
/* Shared indicator dot — color-theme swatch */
.topbar-icon-btn .indicator-dot {
  position: absolute;
  bottom: 4px; right: 4px;
  width: 8px; height: 8px;
  border-radius: 50%;
  border: 1.5px solid var(--surface);
  pointer-events: none;
}
.color-menu-backdrop {
  position: fixed; inset: 0; z-index: 9998;
}
.color-menu {
  position: fixed;
  top: 56px; right: 62px;
  width: 170px;
  background: var(--glass-surface-strong);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-floating), var(--glass-highlight);
  backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  z-index: 9999;
  padding: 6px;
  display: flex; flex-direction: column;
}
.color-menu-header {
  font-size: 10.5px; font-weight: 700; color: var(--muted-foreground);
  text-transform: uppercase; letter-spacing: 0.6px;
  padding: 5px 10px 7px;
}
.color-menu-item {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 10px; border: none; border-radius: var(--radius-sm);
  background: transparent; color: var(--foreground);
  font-size: 13px; font-family: var(--font-sans); cursor: pointer;
  text-align: left; width: 100%;
  transition: background var(--transition-fast);
}
.color-menu-item:hover { background: var(--surface-hover); }
.color-menu-item.active { color: var(--primary); font-weight: 600; }
.color-menu-item svg { margin-left: auto; color: var(--primary); flex-shrink: 0; }
.color-swatch {
  width: 20px; height: 20px; border-radius: 6px; flex-shrink: 0;
  box-shadow: 0 0 0 1px var(--surface-border), inset 0 1px 0 rgba(255,255,255,0.2);
}
.color-label { flex: 1; }

@keyframes badge-pop {
  from { opacity: 0; transform: scale(0.45); }
  to { opacity: 1; transform: scale(1); }
}

/* ── Main content ───────────────────────────────────────────────── */
.app-main {
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  /* The light spots live on app-root only. Keeping this layer translucent
     makes the main area and chat panel sample the same fixed backdrop. */
  background: var(--workspace-canvas);
  padding: 30px 32px 48px;
}

.mobile-menu-btn,
.mobile-sidebar-backdrop {
  display: none;
}

@media (max-width: 820px) {
  .app-sidebar {
    position: fixed;
    inset: 0 auto 0 0;
    z-index: 300;
    width: min(86vw, 280px);
    transform: translateX(-102%);
    box-shadow: var(--shadow-floating);
    transition: transform var(--motion-slow) var(--motion-ease-enter);
    will-change: transform;
  }

  .app-sidebar.collapsed {
    width: min(86vw, 280px);
  }

  .app-sidebar.mobile-open {
    transform: translateX(0);
  }

  .app-sidebar.collapsed .sidebar-header {
    padding: 16px 18px;
    justify-content: flex-start;
    gap: 10px;
  }

  .app-sidebar.collapsed .sidebar-logo,
  .app-sidebar.collapsed .sidebar-title {
    max-width: none;
    opacity: 1;
    pointer-events: auto;
  }

  .app-sidebar.collapsed .sidebar-collapse-btn {
    margin-left: auto;
  }

  .mobile-sidebar-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 299;
    padding: 0;
    border: 0;
    background: rgb(15 23 42 / 0.42);
    -webkit-backdrop-filter: blur(12px);
    backdrop-filter: blur(12px);
  }

  .mobile-menu-btn {
    display: flex;
    margin-left: -8px;
  }

  .app-topbar {
    height: 56px;
    padding: 0 18px;
  }

  .app-main {
    padding: 22px 18px 40px;
  }

}

@media (max-width: 480px) {
  .topbar-title {
    max-width: 100px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .topbar-right {
    gap: 2px;
  }

  .app-main {
    padding-inline: 14px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .app-root::before,
  .app-root::after {
    animation: none;
    transform: none;
  }
}
</style>
