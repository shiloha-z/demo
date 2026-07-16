<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useProjectStore } from '../stores/project'
import { useWebSocketStore } from '../stores/websocket'
import { useMessageStore } from '../stores/message'
import api from '../api'

const props = defineProps<{ collapsed: boolean }>()

const route = useRoute()
const store = useProjectStore()
const wsStore = useWebSocketStore()
const msgStore = useMessageStore()

const pendingCount = ref(0)

async function fetchPendingCount() {
  const pid = store.currentProject?.id
  if (!pid) { pendingCount.value = 0; return }
  try {
    const { data } = await api.get('/reviews/pending-count', { params: { project_id: pid } })
    pendingCount.value = data.count
  } catch { /* ignore */ }
}

onMounted(async () => {
  try {
    if (store.projects.length === 0) await store.fetchProjects()
  } catch { /* backend may not be ready yet */ }
  fetchPendingCount()
  msgStore.refresh()
})

// Refetch when project changes
watch(() => store.currentProject?.id, () => fetchPendingCount())

// Listen for WebSocket events
let unsubReview: (() => void) | null = null
let unsubMessage: (() => void) | null = null
watch(() => wsStore.connected, (ok) => {
  if (ok) {
    unsubReview = wsStore.on('review_update', () => fetchPendingCount())
    unsubMessage = wsStore.on('message_new', () => msgStore.refresh())
  }
}, { immediate: true })

onUnmounted(() => { unsubReview?.(); unsubMessage?.() })

const selectedProjectId = computed({
  get: () => store.currentProject?.id ?? null,
  set: (id: number | null) => {
    const p = store.projects.find(p => p.id === id) || null
    store.setCurrentProject(p)
  },
})

const sections = [
  {
    label: '工作区',
    items: [
      { path: '/dashboard', icon: 'grid', label: '项目看板' },
      { path: '/files',     icon: 'folder', label: '文件管理' },
    ],
  },
  {
    label: 'Agent',
    items: [
      { path: '/agents',  icon: 'bot',   label: 'Agent 池' },
      { path: '/tasks',   icon: 'list',  label: '任务列表' },
      { path: '/reviews', icon: 'check', label: '审查记录', badge: true },
    ],
  },
  {
    label: '历史',
    items: [
      { path: '/versions', icon: 'clock', label: '版本历史' },
    ],
  },
  {
    label: '系统',
    items: [
      { path: '/messages', icon: 'bell', label: '消息中心', badge: true },
    ],
  },
]

const activePath = computed(() => route.path)

// Minimal inline SVG icons — clean 18px line icons
const icons: Record<string, string> = {
  grid:   '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
  folder: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
  bot:    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16.01"/><line x1="16" y1="16" x2="16" y2="16.01"/></svg>',
  check:  '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>',
  clock:  '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
  list:   '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>',
  bell:    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>',
}
</script>

<template>
  <!-- Global project selector -->
  <div class="project-picker" :class="{ collapsed: collapsed }">
    <svg class="picker-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
    <select v-model="selectedProjectId" class="project-select">
      <option :value="null" disabled>选择项目…</option>
      <option v-for="p in store.projects" :key="p.id" :value="p.id">{{ p.name }}</option>
    </select>
  </div>

  <nav class="sidebar-nav" :class="{ collapsed: collapsed }">
    <div v-for="section in sections" :key="section.label" class="nav-section">
      <div class="nav-section-label" :class="{ 'fade-out': collapsed }">{{ section.label }}</div>
      <router-link
        v-for="item in section.items"
        :key="item.path"
        :to="item.path"
        class="nav-item"
        :class="{ active: activePath === item.path }"
        :title="collapsed ? item.label : ''"
      >
        <span class="nav-icon-wrap">
          <span class="nav-icon" v-html="icons[item.icon]"></span>
          <span v-if="item.badge && pendingCount > 0 && collapsed" class="nav-badge-dot"></span>
          <span v-if="item.path === '/messages' && msgStore.unreadCount > 0 && collapsed" class="nav-badge-dot"></span>
        </span>
        <span class="nav-label" :class="{ 'fade-out': collapsed }">{{ item.label }}</span>
        <span v-if="item.badge && pendingCount > 0" class="nav-badge" :class="{ 'fade-out': collapsed }">{{ pendingCount }}</span>
        <span v-if="item.path === '/messages' && msgStore.unreadCount > 0" class="nav-badge" :class="{ 'fade-out': collapsed }">{{ msgStore.unreadCount }}</span>
      </router-link>
    </div>
  </nav>
</template>

<style scoped>
/* ── Fade-out utility ──────────────────────────────────────────── */
.fade-out {
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.2s ease;
}

/* ── Global project picker ─────────────────────────────────────── */
.project-picker {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px; margin: 4px 10px 0;
  background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-md);
  overflow: hidden;
  transition: border-color var(--transition-fast), padding 0.25s cubic-bezier(0.4, 0, 0.2, 1), margin 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.project-picker.collapsed {
  padding: 8px 6px;
  margin: 4px 6px 0;
  justify-content: center;
  gap: 0;
  position: relative;
}

.project-picker.collapsed .picker-icon {
  opacity: 0.7;
}

.project-picker.collapsed .project-select {
  position: absolute;
  inset: 0;
  width: 100%;
  opacity: 0;
  cursor: pointer;
}
.project-picker:hover { border-color: var(--ring); }
.picker-icon { color: var(--muted-foreground); flex-shrink: 0; opacity: 0.6; }
.project-select {
  flex: 1; min-width: 0; padding: 4px 0;
  border: none; background: transparent; color: var(--foreground);
  font-size: 13px; font-weight: 500; font-family: var(--font-sans);
  outline: none; cursor: pointer;
}

.sidebar-nav {
  flex: 1;
  overflow-y: auto;
  padding: 8px 10px;
}

.nav-section {
  margin-bottom: 16px;
}

.nav-section-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--muted-foreground);
  text-transform: uppercase;
  letter-spacing: 0.8px;
  padding: 6px 10px 4px;
  white-space: nowrap;
  overflow: hidden;
  transition: opacity 0.2s ease, max-height 0.25s cubic-bezier(0.4, 0, 0.2, 1), padding 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.sidebar-nav.collapsed .nav-section-label {
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  border-radius: var(--radius-md);
  color: var(--muted-foreground);
  text-decoration: none;
  font-size: 13.5px;
  font-weight: 500;
  transition: padding 0.25s cubic-bezier(0.4, 0, 0.2, 1),
              gap 0.25s cubic-bezier(0.4, 0, 0.2, 1),
              background var(--transition-fast),
              color var(--transition-fast);
  cursor: pointer;
  position: relative;
}

.nav-item:hover {
  background: var(--surface-hover);
  color: var(--foreground);
}

.nav-item.active {
  background: var(--primary-light);
  color: var(--primary);
  font-weight: 600;
}

.nav-icon-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.nav-icon {
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  opacity: 0.7;
  transition: opacity 0.2s ease;
}

.nav-item.active .nav-icon {
  opacity: 1;
}

.nav-label {
  line-height: 1;
  white-space: nowrap;
  overflow: hidden;
  max-width: 200px;
  transition: opacity 0.2s ease, max-width 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.sidebar-nav.collapsed .nav-label {
  max-width: 0;
}

/* ── Badge ─────────────────────────────────────────────────────── */
.nav-badge {
  margin-left: auto;
  min-width: 18px; height: 18px;
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--danger);
  color: #fff;
  font-size: 10px; font-weight: 700; line-height: 1;
  border-radius: 9px; padding: 0 5px;
  transition: opacity 0.2s ease, max-width 0.25s cubic-bezier(0.4, 0, 0.2, 1), padding 0.25s cubic-bezier(0.4, 0, 0.2, 1), margin 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}

.sidebar-nav.collapsed .nav-badge {
  max-width: 0;
  padding: 0;
  margin: 0;
}

/* ── Collapsed badge dot ────────────────────────────────────────── */
.nav-badge-dot {
  position: absolute;
  top: -1px;
  right: -1px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--danger);
  border: 2px solid var(--app-shell);
}

/* ── Collapsed nav ──────────────────────────────────────────────── */
.sidebar-nav.collapsed {
  padding: 8px 6px;
}

.sidebar-nav.collapsed .nav-section {
  margin-bottom: 8px;
}

.sidebar-nav.collapsed .nav-item {
  justify-content: center;
  padding: 10px 0;
  gap: 0;
}

.sidebar-nav.collapsed .nav-icon {
  opacity: 0.65;
}

.sidebar-nav.collapsed .nav-item.active .nav-icon {
  opacity: 1;
}
</style>
