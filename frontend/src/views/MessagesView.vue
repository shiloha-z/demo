<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import api from '../api'
import { useMessageStore } from '../stores/message'

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
  created_at: string | null
}

type TabKey = 'all' | 'system' | 'task' | 'review' | 'version'

const router = useRouter()
const msgStore = useMessageStore()
const messages = ref<MessageItem[]>([])
const loading = ref(false)
const activeTab = ref<TabKey>('all')
const unreadTotal = ref(0)

const tabs: { key: TabKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'task', label: '任务' },
  { key: 'review', label: '审查' },
  { key: 'version', label: '版本' },
  { key: 'system', label: '系统' },
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
  if (activeTab.value === 'all') return messages.value
  return messages.value.filter((m) => m.category === activeTab.value)
})

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/messages', { params: { limit: 200 } })
    messages.value = data
    unreadTotal.value = data.filter((m: MessageItem) => !m.read).length
  } catch {
    MessagePlugin.error('加载消息失败')
  } finally {
    loading.value = false
  }
}

async function markRead(id: number) {
  try {
    await api.post(`/messages/${id}/read`)
    const m = messages.value.find((x) => x.id === id)
    if (m) m.read = true
    await msgStore.refresh()
  } catch {
    MessagePlugin.error('操作失败')
  }
}

async function markAllRead() {
  try {
    await api.post('/messages/read-all')
    messages.value.forEach((m) => (m.read = true))
    await msgStore.refresh()
    MessagePlugin.success('已全部标为已读')
  } catch {
    MessagePlugin.error('操作失败')
  }
}

function openLink(link: string) {
  if (link) router.push(link)
}

function fmtTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

// Refresh when a new message arrives over WS
import { useWebSocketStore } from '../stores/websocket'
import { onUnmounted } from 'vue'
const wsStore = useWebSocketStore()
let unsubMsg: (() => void) | null = null
watch(
  () => wsStore.connected,
  (ok) => {
    if (ok && !unsubMsg) {
      unsubMsg = wsStore.on('message_new', () => {
        load()
        msgStore.refresh()
      })
    }
  },
  { immediate: true },
)

onMounted(load)
onUnmounted(() => { unsubMsg?.() })
</script>

<template>
  <div class="page-root">
    <div class="page-header">
      <div>
        <h1 class="page-title">消息中心</h1>
        <p class="page-desc">
          系统提示与项目动态，如工程完成、任务待审核等
          <span v-if="unreadTotal > 0" class="unread-tip">{{ unreadTotal }} 条未读</span>
        </p>
      </div>
      <t-button
        v-if="unreadTotal > 0"
        variant="outline"
        size="small"
        :disabled="loading"
        @click="markAllRead"
      >
        全部已读
      </t-button>
    </div>

    <!-- Tabs -->
    <div class="tabs">
      <button
        v-for="t in tabs"
        :key="t.key"
        class="tab"
        :class="{ active: activeTab === t.key }"
        @click="activeTab = t.key"
      >
        {{ t.label }}
      </button>
    </div>

    <!-- List -->
    <div v-if="loading" class="empty-card">
      <p>加载中...</p>
    </div>
    <div v-else-if="filtered.length === 0" class="empty-card">
      <p>暂无消息</p>
    </div>
    <div v-else class="msg-list">
      <div
        v-for="m in filtered"
        :key="m.id"
        class="msg-card"
        :class="{ unread: !m.read, clickable: !!m.link }"
        @click="m.link ? openLink(m.link) : null"
      >
        <div class="msg-main">
          <div class="msg-top">
            <span class="dot" :class="levelMeta[m.level]?.cls || 'lv-info'"></span>
            <span class="msg-title">{{ m.title }}</span>
            <span v-if="!m.read" class="unread-flag">未读</span>
            <span class="badge" :class="categoryMeta[m.category]?.cls">{{ categoryMeta[m.category]?.label || m.category }}</span>
          </div>
          <p v-if="m.body" class="msg-body">{{ m.body }}</p>
          <div class="msg-foot">
            <span class="msg-time">{{ fmtTime(m.created_at) }}</span>
            <span v-if="m.link" class="msg-link">查看详情 →</span>
            <button
              v-if="!m.read"
              class="mark-btn"
              @click.stop="markRead(m.id)"
            >标为已读</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-root { max-width: 760px; }

/* ── Header ─────────────────────────────────────────────────────────── */
.page-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  margin-bottom: 18px; gap: 12px;
}
.page-title { margin: 0; font-size: 20px; font-weight: 700; color: var(--foreground); }
.page-desc { margin: 4px 0 0; font-size: 13px; color: var(--muted-foreground); }
.unread-tip {
  margin-left: 8px; color: var(--primary); font-weight: 600;
}

/* ── Tabs ───────────────────────────────────────────────────────────── */
.tabs {
  display: flex; gap: 4px; margin-bottom: 14px;
  border-bottom: 1px solid var(--surface-border);
}
.tab {
  padding: 8px 14px; border: none; background: transparent;
  color: var(--muted-foreground); font-size: 13.5px; font-weight: 500;
  cursor: pointer; border-bottom: 2px solid transparent;
  transition: all var(--transition-fast);
}
.tab:hover { color: var(--foreground); }
.tab.active { color: var(--primary); border-bottom-color: var(--primary); font-weight: 600; }

/* ── Empty ──────────────────────────────────────────────────────────── */
.empty-card {
  padding: 48px; text-align: center; color: var(--muted-foreground);
  background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg);
}

/* ── Message list ───────────────────────────────────────────────────── */
.msg-list { display: flex; flex-direction: column; gap: 10px; }
.msg-card {
  background: var(--surface);
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg);
  padding: 14px 16px;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}
.msg-card.unread {
  border-color: var(--primary-light);
  background: var(--primary-light);
}
.msg-card.clickable { cursor: pointer; }
.msg-card.clickable:hover { border-color: var(--ring); box-shadow: var(--shadow-surface); }

.msg-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.msg-title { font-size: 14px; font-weight: 600; color: var(--foreground); }
.unread-flag {
  font-size: 10px; font-weight: 700; color: var(--primary);
  background: var(--primary-light); padding: 1px 6px; border-radius: 8px;
}
.msg-body {
  margin: 8px 0 0; font-size: 13px; line-height: 1.6; color: var(--muted-foreground);
}
.msg-foot {
  margin-top: 10px; display: flex; align-items: center; gap: 12px;
  font-size: 12px; color: var(--muted-foreground);
}
.msg-time { opacity: 0.8; }
.msg-link { color: var(--primary); font-weight: 500; }
.mark-btn {
  margin-left: auto; border: 1px solid var(--surface-border);
  background: var(--page-canvas); color: var(--muted-foreground);
  font-size: 12px; padding: 3px 10px; border-radius: var(--radius-md);
  cursor: pointer; transition: all var(--transition-fast);
}
.mark-btn:hover { color: var(--foreground); border-color: var(--ring); }

/* ── Level dot ──────────────────────────────────────────────────────── */
.dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.lv-info { background: var(--muted-foreground); }
.lv-success { background: #22c55e; }
.lv-warning { background: #f59e0b; }
.lv-error { background: var(--danger); }

/* ── Category badge ─────────────────────────────────────────────────── */
.badge {
  margin-left: auto; font-size: 11px; font-weight: 600;
  padding: 2px 8px; border-radius: 8px;
}
.cat-system { color: var(--muted-foreground); background: var(--surface-hover); }
.cat-task { color: #3b82f6; background: rgba(59,130,246,0.12); }
.cat-review { color: #a855f7; background: rgba(168,85,247,0.12); }
.cat-version { color: #14b8a6; background: rgba(20,184,166,0.12); }
.cat-member { color: #ec4899; background: rgba(236,72,153,0.12); }
</style>
