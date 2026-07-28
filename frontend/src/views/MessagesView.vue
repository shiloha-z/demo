<script setup lang="ts">
import { ref, onActivated, computed } from 'vue'
import { useRouter } from 'vue-router'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import api from '../api'
import { useMessageStore, type MessageItem } from '../stores/message'
import { messageLocation, navigateToMessage } from '../utils/messageNavigation'

type TabKey = 'all' | 'system' | 'task' | 'review' | 'member' | 'version'

const router = useRouter()
const msgStore = useMessageStore()
const messages = computed(() => msgStore.items)
const loading = computed(() => msgStore.loading)
const activeTab = ref<TabKey>('all')
const unreadTotal = computed(() => msgStore.unreadCount)

const tabs: { key: TabKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'task', label: '任务' },
  { key: 'review', label: '审查' },
  { key: 'member', label: '成员' },
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
  try {
    await Promise.all([msgStore.load(true), msgStore.refresh()])
  } catch {
    MessagePlugin.error('加载消息失败')
  }
}

async function loadMore() {
  try {
    await msgStore.load(false)
  } catch {
    MessagePlugin.error('加载更多消息失败')
  }
}

async function markRead(id: number) {
  try {
    await msgStore.markRead(id)
  } catch {
    MessagePlugin.error('标记已读失败，状态已恢复')
  }
}

async function markAllRead() {
  try {
    await msgStore.markAllRead()
    MessagePlugin.success('已全部标为已读')
  } catch {
    MessagePlugin.error('操作失败，未读状态已恢复')
  }
}

async function deleteMessage(m: MessageItem) {
  const dlg = DialogPlugin.confirm({
    header: '确认删除',
    body: `确定要删除消息「${m.title}」吗？`,
    confirmBtn: { content: '删除', theme: 'danger' },
    cancelBtn: '取消',
    onConfirm: async () => {
      try {
        await msgStore.dismiss(m.id)
        MessagePlugin.success('已删除')
      } catch {
        MessagePlugin.error('删除失败')
      }
      dlg.destroy()
    },
  })
}

async function deleteAllMessages() {
  if (filtered.value.length === 0) return
  const visibleCount = filtered.value.length
  const category = activeTab.value === 'all' ? undefined : activeTab.value
  const dlg = DialogPlugin.confirm({
    header: '确认删除全部',
    body: `确定要从你的消息中心移除当前${category ? '分类' : '列表'}中的消息吗？当前已加载 ${visibleCount} 条。`,
    confirmBtn: { content: '删除全部', theme: 'danger' },
    cancelBtn: '取消',
    onConfirm: async () => {
      try {
        const count = await msgStore.dismissAll(category)
        MessagePlugin.success(`已移除 ${count} 条消息`)
      } catch {
        MessagePlugin.error('删除失败')
      }
      dlg.destroy()
    },
  })
}

const processingJoins = ref<Record<number, boolean>>({})

function parseJoinRequest(link: string): number | null {
  const m = link.match(/join_request=(\d+)/)
  return m ? Number(m[1]) : null
}

async function handleJoinAction(msg: MessageItem, action: 'approve' | 'reject') {
  const requestId = parseJoinRequest(msg.link)
  if (!requestId || !msg.project_id) return
  processingJoins.value[msg.id] = true
  try {
    const url = `/projects/${msg.project_id}/applications/${requestId}/${action === 'approve' ? 'approve' : 'reject'}`
    await api.post(url)
    if (!msg.read) void msgStore.markRead(msg.id).catch(() => msgStore.refresh())
    MessagePlugin.success(action === 'approve' ? '已通过' : '已驳回')
    // Replace the action buttons with the result
    msg.link = ''  // clear so buttons disappear
    msg.title = action === 'approve' ? '已通过加入申请' : '已驳回加入申请'
  } catch (e: any) {
    MessagePlugin.error(e?.response?.data?.detail || '操作失败')
  } finally {
    processingJoins.value[msg.id] = false
  }
}

function openLink(m: MessageItem) {
  if (m && !m.read) markRead(m.id)
  void navigateToMessage(m, router)
}

function fmtTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

onActivated(load)
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
      <div class="header-btns">
        <t-button
          v-if="unreadTotal > 0"
          variant="outline"
          size="small"
          :disabled="loading"
          @click="markAllRead"
        >
          全部已读
        </t-button>
        <t-button
          v-if="messages.length > 0"
          variant="outline"
          size="small"
          theme="danger"
          :disabled="loading"
          @click="deleteAllMessages"
        >
          删除全部
        </t-button>
      </div>
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
    <div v-if="loading && messages.length === 0" class="empty-card">
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
        :class="{ unread: !m.read, resolved: m.resolved, clickable: !!messageLocation(m) && !parseJoinRequest(m.link) && !m.resolved }"
        @click="messageLocation(m) && !parseJoinRequest(m.link) ? openLink(m) : null"
      >
        <div class="msg-main">
          <div class="msg-top">
            <span class="dot" :class="levelMeta[m.level]?.cls || 'lv-info'"></span>
            <span class="msg-title" :class="{ 'msg-title-resolved': m.resolved }">{{ m.title }}</span>
            <span v-if="m.resolved" class="resolved-flag">已处理</span>
            <span v-else-if="!m.read" class="unread-flag">未读</span>
            <span class="badge" :class="categoryMeta[m.category]?.cls">{{ categoryMeta[m.category]?.label || m.category }}</span>
          </div>
          <p v-if="m.body" class="msg-body">{{ m.body }}</p>
          <div v-if="m.category === 'member' && parseJoinRequest(m.link)" class="msg-actions">
            <t-button size="small" theme="success" :loading="processingJoins[m.id]" @click.stop="handleJoinAction(m, 'approve')">通过</t-button>
            <t-button size="small" theme="default" :loading="processingJoins[m.id]" @click.stop="handleJoinAction(m, 'reject')">驳回</t-button>
          </div>
          <div class="msg-foot">
            <span class="msg-time">{{ fmtTime(m.created_at) }}</span>
            <span v-if="messageLocation(m) && !parseJoinRequest(m.link)" class="msg-link">查看详情 →</span>
            <button
              v-if="!m.read"
              class="mark-btn"
              @click.stop="markRead(m.id)"
            >标为已读</button>
            <button
              class="delete-msg-btn"
              @click.stop="deleteMessage(m)"
              title="删除"
            >×</button>
          </div>
        </div>
      </div>
    </div>
    <div v-if="messages.length > 0 && msgStore.hasMore" class="load-more-row">
      <t-button
        variant="outline"
        size="small"
        :loading="msgStore.loadingMore"
        @click="loadMore"
      >
        加载更多
      </t-button>
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
.header-btns { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }
.page-title { margin: 0; font-size: 20px; font-weight: 700; color: var(--foreground); }
.page-desc { margin: 4px 0 0; font-size: 13px; color: var(--muted-foreground); }
.unread-tip {
  margin-left: 8px; color: var(--primary); font-weight: 600;
}

/* ── Tabs ───────────────────────────────────────────────────────────── */
.tabs {
  display: flex; gap: 4px; width: fit-content; margin-bottom: 16px;
  padding: 4px;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  background: var(--glass-surface-soft);
  box-shadow: var(--glass-highlight);
  -webkit-backdrop-filter: blur(var(--glass-blur-sm));
  backdrop-filter: blur(var(--glass-blur-sm));
}
.tab {
  padding: 7px 13px; border: none; border-radius: var(--radius-md); background: transparent;
  color: var(--muted-foreground); font-size: 13.5px; font-weight: 500;
  cursor: pointer;
  transition:
    color var(--transition-fast),
    background-color var(--transition-fast),
    box-shadow var(--transition-fast),
    transform var(--motion-fast) var(--motion-ease-spring);
}
.tab:hover { color: var(--foreground); }
.tab:active { transform: scale(0.97); }
.tab.active {
  color: var(--primary);
  background: var(--glass-surface-strong);
  box-shadow: var(--shadow-surface), inset 0 0 0 1px var(--primary-light);
  font-weight: 650;
}

/* ── Empty ──────────────────────────────────────────────────────────── */
.empty-card {
  padding: 48px; text-align: center; color: var(--muted-foreground);
  background: var(--card-bg); border: var(--card-border);
  border-radius: var(--card-radius);
}

/* ── Message list ───────────────────────────────────────────────────── */
.msg-list { display: flex; flex-direction: column; gap: 10px; }
.load-more-row { display: flex; justify-content: center; padding: 18px 0 4px; }
.msg-card {
  background: var(--card-bg);
  border: var(--card-border);
  border-radius: var(--radius-lg);
  padding: 14px 16px;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}
.msg-card.unread {
  border-color: var(--primary-light);
  background: var(--primary-light);
}
.msg-card.resolved { opacity: 0.55; }
.msg-card.clickable { cursor: pointer; }
.msg-card.clickable:hover { border-color: var(--ring); box-shadow: var(--shadow-surface); }

.msg-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.msg-title { font-size: 14px; font-weight: 600; color: var(--foreground); }
.unread-flag {
  font-size: 10px; font-weight: 700; color: var(--primary);
  background: var(--primary-light); padding: 1px 6px; border-radius: 8px;
}
.resolved-flag {
  font-size: 10px; font-weight: 600; color: var(--muted-foreground);
  background: var(--surface-hover); padding: 1px 6px; border-radius: 8px;
}
.msg-title-resolved { color: var(--muted-foreground); text-decoration: line-through; }
.msg-body {
  margin: 8px 0 0; font-size: 13px; line-height: 1.6; color: var(--muted-foreground);
}
.msg-actions {
  margin-top: 10px; display: flex; gap: 8px;
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
.delete-msg-btn {
  border: 1px solid transparent; background: transparent;
  color: var(--muted-foreground); font-size: 16px; font-weight: 700;
  width: 24px; height: 24px; border-radius: var(--radius-sm);
  cursor: pointer; display: inline-flex; align-items: center; justify-content: center;
  transition: all var(--transition-fast); line-height: 1; padding: 0;
}
.delete-msg-btn:hover { color: var(--danger); background: var(--danger-light); border-color: var(--danger); }

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
