<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { useWebSocketStore } from './stores/websocket'
import ProjectSidebar from './components/ProjectSidebar.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const ws = useWebSocketStore()

const isLoginPage = computed(() => route.meta.guest === true)

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

  <!-- Main app: sidebar + inset layout -->
  <div v-else class="app-root">
    <aside class="app-sidebar">
      <div class="sidebar-header">
        <span class="sidebar-logo">🤖</span>
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
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
        </button>
      </div>
    </aside>

    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>

<style>
@import './styles/tokens.css';
</style>

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
  font-size: 22px;
  line-height: 1;
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
  background: var(--surface-selected);
  color: var(--secondary-foreground);
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
  transition: all 0.15s;
}

.logout-btn:hover {
  background: var(--surface-hover);
  color: var(--danger);
}

/* ── Main content ───────────────────────────────────────────────── */
.app-main {
  flex: 1;
  overflow-y: auto;
  background: var(--page-canvas);
  padding: 28px 32px;
}
</style>
