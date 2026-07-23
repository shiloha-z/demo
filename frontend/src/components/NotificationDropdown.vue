<script setup lang="ts">
import { ref, computed, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'
import { useMessageStore } from '../stores/message'
import { useWebSocketStore } from '../stores/websocket'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()

interface MessageItem {
  id: number
  recipient_id: number | null
  project_id: number | null
  category: string
  level: string
  title: string
  body: string
  link: string
  read: boolean
  resolved: boolean
  created_at: string | null
}

type TabKey = 'all' | 'task' | 'review' | 'member' | 'version' | 'system'

const router = useRouter()
const msgStore = useMessageStore()
const wsStore = useWebSocketStore()

const messages = ref<MessageItem[]>([])
const loading = ref(false)
const activeTab = ref<TabKey>('all')

const tabs: { key: TabKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'task', label: '任务' },
  { key: 'review', label: '审查' },
  { key: 'member', label: '成员' },
]

const categoryMeta: Record<string, { label: string; cls: string }> = {
  system: { label: '系统', cls: 'cat-system' },
  task: { label: '任务', cls: 'cat-task' },
  review: { label: '审查', cls: 'cat-review' },
  version: { label: '版本', cls: 'cat-version' },
  member: { label: '成员', cls: 'cat-member' },
}

const levelMeta: Record<string, { label: string; cls: string }> = {
  info: { label: '提示', cls: 'lv-info' },
  success: { label: '成功', cls: 'lv-success' },
  warning: { label: '注意', cls: 'lv-warning' },
  error: { label: '错误', cls: 'lv-error' },
}

const filtered = computed(() => {
  if (activeTab.value === 'all') return messages.value.slice(0, 30)
  return messages.value.filter(m => m.category === activeTab.value).slice(0, 30)
})

const unreadTotal = computed(() => messages.value.filter(m => !m.read).length)

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/messages', { params: { limit: 100 } })
    messages.value = data
  } catch { /* ignore */ }
  finally { loading.value = false }
}

async function markRead(id: number) {
  try {
    await api.post(`/messages/${id}/read`)
    const m = messages.value.find(x => x.id === id)
    if (m) m.read = true
    await msgStore.refresh()
  } catch { /* ignore */ }
}

async function markAllRead() {
  try {
    await api.post('/messages/read-all')
    messages.value.forEach(m => (m.read = true))
    await msgStore.refresh()
  } catch { /* ignore */ }
}

function openLink(m: MessageItem) {
  if (!m.read) markRead(m.id)
  if (m.link) {
    emit('close')
    router.push(m.link)
  }
}

function goToFullPage() {
  emit('close')
  router.push('/messages')
}

function fmtTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const isToday = d.toDateString() === now.toDateString()
  if (isToday) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

// ── Mark all as seen on open ────────────────────────────────────
async function refreshOnOpen() {
  await load()
  // Silently mark all as seen so the red dot clears immediately.
  const hadUnread = messages.value.some(m => !m.read)
  if (hadUnread) {
    try { await api.post('/messages/read-all') } catch { /* ignore */ }
    messages.value.forEach(m => (m.read = true))
    await msgStore.refresh()
  }
}

watch(() => props.visible, (visible) => {
  if (visible) refreshOnOpen()
}, { immediate: true })

// ── Refresh on new message ──────────────────────────────────────
let unsubMsg: (() => void) | null = null
watch(() => wsStore.connected, (ok) => {
  if (ok && !unsubMsg) {
    unsubMsg = wsStore.on('message_new', () => {
      if (props.visible) load()
    })
  }
}, { immediate: true })

onUnmounted(() => { unsubMsg?.() })

// ── Click outside ───────────────────────────────────────────────
function onBackdropClick(e: MouseEvent) {
  if ((e.target as HTMLElement)?.classList.contains('notif-dropdown-backdrop')) {
    emit('close')
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="notification-pop">
      <div v-if="visible" class="notif-dropdown-backdrop" @click="onBackdropClick">
        <div class="notif-dropdown" @click.stop>
        <!-- Header -->
        <div class="nd-header">
          <span class="nd-title">消息中心</span>
          <span v-if="unreadTotal > 0" class="nd-unread">{{ unreadTotal }} 条未读</span>
          <div class="nd-header-actions">
            <button v-if="unreadTotal > 0" class="nd-btn" @click="markAllRead">全部已读</button>
            <button class="nd-btn nd-btn-link" @click="goToFullPage">查看全部 →</button>
          </div>
        </div>

        <!-- Tabs -->
        <div class="nd-tabs">
          <button
            v-for="t in tabs"
            :key="t.key"
            class="nd-tab"
            :class="{ active: activeTab === t.key }"
            @click="activeTab = t.key"
          >{{ t.label }}</button>
        </div>

        <!-- List -->
        <div class="nd-body">
          <div v-if="loading" class="nd-empty">加载中...</div>
          <div v-else-if="filtered.length === 0" class="nd-empty">暂无消息</div>
          <div v-else class="nd-list">
            <div
              v-for="m in filtered"
              :key="m.id"
              class="nd-item"
              :class="{ unread: !m.read, resolved: m.resolved, clickable: !!m.link && !m.resolved }"
              @click="m.link ? openLink(m) : null"
            >
              <div class="nd-item-top">
                <span class="nd-dot" :class="levelMeta[m.level]?.cls || 'lv-info'"></span>
                <span class="nd-item-title" :class="{ 'nd-resolved-title': m.resolved }">{{ m.title }}</span>
                <span v-if="m.resolved" class="nd-resolved-tag">已处理</span>
                <span v-else-if="!m.read" class="nd-unread-dot"></span>
              </div>
              <p v-if="m.body" class="nd-item-body">{{ m.body }}</p>
              <div class="nd-item-foot">
                <span class="nd-time">{{ fmtTime(m.created_at) }}</span>
                <span class="nd-cat" :class="categoryMeta[m.category]?.cls">{{ categoryMeta[m.category]?.label || m.category }}</span>
                <button v-if="!m.read" class="nd-mark-btn" @click.stop="markRead(m.id)">已读</button>
              </div>
            </div>
          </div>
        </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* ── Backdrop ──────────────────────────────────────────────────── */
.notif-dropdown-backdrop {
  position: fixed; inset: 0; z-index: 200;
  background: transparent;
}
.notif-dropdown {
  position: fixed;
  top: 52px; right: 80px;
  width: 400px; max-height: 520px;
  background: var(--page-canvas);
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg);
  box-shadow: 0 8px 32px rgba(0,0,0,0.18);
  display: flex; flex-direction: column;
  transform-origin: right top;
  z-index: 201;
}
.notification-pop-enter-active .notif-dropdown {
  transition:
    opacity var(--motion-base) var(--motion-ease-enter),
    transform var(--motion-base) var(--motion-ease-enter);
}
.notification-pop-leave-active .notif-dropdown {
  transition:
    opacity var(--motion-fast) var(--motion-ease-exit),
    transform var(--motion-fast) var(--motion-ease-exit);
}
.notification-pop-enter-from .notif-dropdown,
.notification-pop-leave-to .notif-dropdown {
  opacity: 0;
  transform: translateY(-6px) scale(0.98);
}

/* ── Header ────────────────────────────────────────────────────── */
.nd-header {
  display: flex; align-items: center; gap: 8px;
  padding: 14px 16px 10px;
  border-bottom: 1px solid var(--surface-border);
  flex-shrink: 0;
}
.nd-title { font-size: 15px; font-weight: 700; color: var(--foreground); }
.nd-unread { font-size: 12px; color: var(--primary); font-weight: 600; }
.nd-header-actions { margin-left: auto; display: flex; gap: 8px; }
.nd-btn {
  font-size: 12px; border: 1px solid var(--surface-border);
  background: var(--page-canvas); color: var(--muted-foreground);
  padding: 3px 10px; border-radius: var(--radius-md); cursor: pointer;
  transition: all var(--transition-fast);
}
.nd-btn:hover { color: var(--foreground); border-color: var(--ring); }
.nd-btn-link { border-color: transparent; color: var(--primary); }
.nd-btn-link:hover { color: var(--primary); border-color: transparent; opacity: 0.8; }

/* ── Tabs ──────────────────────────────────────────────────────── */
.nd-tabs {
  display: flex; gap: 0; flex-shrink: 0;
  padding: 0 12px; border-bottom: 1px solid var(--surface-border);
}
.nd-tab {
  padding: 7px 12px; font-size: 12.5px; border: none; cursor: pointer;
  background: transparent; color: var(--muted-foreground); font-weight: 500;
  border-bottom: 2px solid transparent; transition: all var(--transition-fast);
}
.nd-tab:hover { color: var(--foreground); }
.nd-tab.active { color: var(--primary); border-bottom-color: var(--primary); font-weight: 600; }

/* ── Body ──────────────────────────────────────────────────────── */
.nd-body { flex: 1; overflow-y: auto; min-height: 0; }
.nd-empty { padding: 32px; text-align: center; font-size: 13px; color: var(--muted-foreground); }

.nd-list { display: flex; flex-direction: column; }
.nd-item {
  padding: 10px 16px; border-bottom: 1px solid var(--surface-border);
  transition: background var(--transition-fast);
}
.nd-item.unread { background: var(--primary-lighter); }
.nd-item.resolved { opacity: 0.6; }
.nd-item.clickable { cursor: pointer; }
.nd-item.clickable:hover { background: var(--surface-hover); }

.nd-item-top { display: flex; align-items: center; gap: 6px; }
.nd-item-title { font-size: 13px; font-weight: 600; color: var(--foreground); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nd-unread-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--primary); flex-shrink: 0; margin-left: auto; }
.nd-resolved-tag {
  font-size: 10px; font-weight: 600; color: var(--muted-foreground);
  background: var(--surface-hover); padding: 1px 6px; border-radius: 6px;
  margin-left: auto;
}
.nd-resolved-title { color: var(--muted-foreground); text-decoration: line-through; }

.nd-item-body {
  margin: 4px 0 0; font-size: 12px; line-height: 1.5;
  color: var(--muted-foreground);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.nd-item-foot {
  margin-top: 6px; display: flex; align-items: center; gap: 8px;
  font-size: 11px; color: var(--muted-foreground);
}
.nd-time { opacity: 0.7; }
.nd-cat { font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 6px; }
.cat-system { color: var(--muted-foreground); background: var(--surface-hover); }
.cat-task { color: #3b82f6; background: rgba(59,130,246,0.12); }
.cat-review { color: #a855f7; background: rgba(168,85,247,0.12); }
.cat-version { color: #14b8a6; background: rgba(20,184,166,0.12); }
.cat-member { color: #ec4899; background: rgba(236,72,153,0.12); }

.nd-mark-btn {
  margin-left: auto; font-size: 11px; border: none; background: transparent;
  color: var(--primary); cursor: pointer; padding: 1px 6px;
}
.nd-mark-btn:hover { text-decoration: underline; }

/* ── Dot ───────────────────────────────────────────────────────── */
.nd-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.lv-info { background: var(--muted-foreground); }
.lv-success { background: #22c55e; }
.lv-warning { background: #f59e0b; }
.lv-error { background: var(--danger); }
</style>
