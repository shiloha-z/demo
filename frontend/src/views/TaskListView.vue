<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import { useProjectStore } from '../stores/project'
import { useWebSocketStore } from '../stores/websocket'
import MonacoEditor from '../components/MonacoEditor.vue'
import api, { getErrorMessage } from '../api'

const store = useProjectStore()
const wsStore = useWebSocketStore()

const tasks = ref<any[]>([])
const archivedTasks = ref<any[]>([])
const selectedTask = ref<any>(null)
const taskDetail = ref<any>(null)
const loadingDetail = ref(false)
const showArchived = ref(false)
const archiveChecked = ref<Set<number>>(new Set())
const archiving = ref(false)
const filterProjectId = computed(() => store.currentProject?.id ?? null)

const statusLabels: Record<string, string> = {
  pending: '等待中', running: '执行中', completed: '已完成', failed: '失败',
}
const statusColors: Record<string, string> = {
  pending: 'var(--warning)',
  running: 'var(--primary)',
  completed: 'var(--success)',
  failed: 'var(--danger)',
}
const reviewStatusLabels: Record<string, string> = {
  pending: '待审查', approved: '已通过', rejected: '已驳回',
}
const reviewStatusColors: Record<string, string> = {
  pending: 'var(--warning)',
  approved: 'var(--success)',
  rejected: 'var(--danger)',
}
const roleLabels: Record<string, string> = {
  code_gen: '代码生成', reviewer: '审查', security: '安全',
}
const roleColors: Record<string, string> = {
  code_gen: 'var(--primary)', reviewer: 'var(--warning)', security: 'var(--danger)',
}

let unsubTask: (() => void) | null = null

onMounted(() => {
  unsubTask = wsStore.on('task_update', (data: any) => {
    const pid = store.currentProject?.id
    if (pid && data.project_id === pid) {
      loadTasks()
      if (selectedTask.value?.id === data.id) {
        selectTask(selectedTask.value)
      }
    }
  })
})

onUnmounted(() => {
  if (unsubTask) unsubTask()
})

watch(() => store.currentProject?.id, async (pid) => {
  if (!pid) { tasks.value = []; archivedTasks.value = []; return }
  await loadTasks()
}, { immediate: true })

async function loadTasks() {
  if (!filterProjectId.value) return
  const [active, archived] = await Promise.all([
    api.get(`/projects/${filterProjectId.value}/tasks`),
    api.get(`/projects/${filterProjectId.value}/tasks`, { params: { archived: true } }),
  ])
  tasks.value = active.data
  archivedTasks.value = archived.data
  archiveChecked.value = new Set()
}

async function selectTask(task: any) {
  selectedTask.value = task
  loadingDetail.value = true
  try {
    const { data } = await api.get(`/projects/${task.project_id}/tasks/${task.id}`)
    taskDetail.value = data
  } catch {
    taskDetail.value = null
  } finally {
    loadingDetail.value = false
  }
}

async function archiveTask(task: any, event: Event) {
  event.stopPropagation()
  try {
    await api.post(`/projects/${task.project_id}/tasks/${task.id}/archive`)
    MessagePlugin.success(`任务 #${task.id} 已归档`)
    if (selectedTask.value?.id === task.id) { selectedTask.value = null; taskDetail.value = null }
    await loadTasks()
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '归档失败')) }
}

async function unarchiveTask(task: any, event?: Event) {
  if (event) event.stopPropagation()
  try {
    await api.post(`/projects/${task.project_id}/tasks/${task.id}/unarchive`)
    MessagePlugin.success(`任务 #${task.id} 已恢复`)
    await loadTasks()
    if (!showArchived.value) archiveChecked.value = new Set()
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '恢复失败')) }
}

function toggleCheck(taskId: number) {
  const next = new Set(archiveChecked.value)
  if (next.has(taskId)) next.delete(taskId)
  else next.add(taskId)
  archiveChecked.value = next
}

function toggleAll() {
  if (archiveChecked.value.size === archivedTasks.value.length) {
    archiveChecked.value = new Set()
  } else {
    archiveChecked.value = new Set(archivedTasks.value.map(t => t.id))
  }
}

async function batchDelete() {
  if (archiveChecked.value.size === 0) return
  const count = archiveChecked.value.size
  const confirmDialog = DialogPlugin.confirm({
    header: '确认批量删除',
    body: `确定要永久删除 ${count} 个已归档任务吗？此操作不可撤销。`,
    confirmBtn: { content: '删除', theme: 'danger' },
    cancelBtn: '取消',
    onConfirm: async () => {
      archiving.value = true
      try {
        await api.post(`/projects/${filterProjectId.value}/tasks/batch-delete`, {
          task_ids: [...archiveChecked.value],
        })
        MessagePlugin.success(`已删除 ${count} 个任务`)
        await loadTasks()
      } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '批量删除失败')) }
      finally { archiving.value = false }
      confirmDialog.destroy()
    },
  })
}

async function deleteOne(task: any, event?: Event) {
  if (event) event.stopPropagation()
  const confirmDialog = DialogPlugin.confirm({
    header: '确认删除',
    body: `确定要永久删除任务 #${task.id}「${task.title}」吗？`,
    confirmBtn: { content: '删除', theme: 'danger' },
    cancelBtn: '取消',
    onConfirm: async () => {
      try {
        await api.delete(`/projects/${task.project_id}/tasks/${task.id}`)
        MessagePlugin.success('已删除')
        await loadTasks()
      } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '删除失败')) }
      confirmDialog.destroy()
    },
  })
}

async function approveReview() {
  if (!taskDetail.value?.review) return
  try {
    await api.post(`/reviews/${taskDetail.value.review.id}/approve`)
    MessagePlugin.success('审查已通过，已提交到 Git')
    if (selectedTask.value) await selectTask(selectedTask.value)
    await loadTasks()
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '操作失败')) }
}

async function rejectReview() {
  if (!taskDetail.value?.review) return
  try {
    await api.post(`/reviews/${taskDetail.value.review.id}/reject`)
    MessagePlugin.warning('审查已驳回')
    if (selectedTask.value) await selectTask(selectedTask.value)
    await loadTasks()
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '操作失败')) }
}

function formatDate(d: string) {
  if (!d) return ''
  return new Date(d).toLocaleString('zh-CN')
}

function renderMarkdown(text: string) {
  if (!text) return ''
  return text
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n- (.+)/g, '\n<li>$1</li>')
    .replace(/\n\n/g, '<br/>')
}
</script>

<template>
  <div class="page-root">
    <div class="page-header">
      <div>
        <h1 class="page-title">任务列表</h1>
        <p class="page-desc">查看 Agent 任务的执行状态与详细结果</p>
      </div>
      <div class="header-right">
        <t-button shape="square" variant="text" @click="loadTasks()" title="刷新">
          <template #icon>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
          </template>
        </t-button>
      </div>
    </div>

    <div v-if="!filterProjectId" class="empty-card empty-card--full">
      <div class="empty-icon">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
      </div>
      <h3>请先选择一个项目</h3>
    </div>

    <template v-else>
      <div v-if="tasks.length === 0 && archivedTasks.length === 0" class="empty-card empty-card--full">
        <div class="empty-icon">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
        </div>
        <h3>暂无任务</h3>
        <p>前往 <router-link to="/agents">Agent 池</router-link> 创建任务</p>
      </div>

      <div v-else class="task-layout">
        <!-- ── Left: task list ─────────────────────────────── -->
        <div class="task-list">
          <!-- Active tasks -->
          <div
            v-for="t in tasks"
            :key="t.id"
            class="task-item"
            :class="{ active: selectedTask?.id === t.id }"
            @click="selectTask(t)"
          >
            <div class="task-item-top">
              <span class="task-id">#{{ t.id }}</span>
              <div class="task-item-actions">
                <button
                  v-if="t.status === 'completed' || t.status === 'failed'"
                  class="archive-btn"
                  title="归档"
                  @click="archiveTask(t, $event)"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg>
                </button>
                <span class="task-status" :style="{ color: statusColors[t.status] }">
                  <span class="status-dot" :class="t.status"></span>
                  {{ statusLabels[t.status] || t.status }}
                </span>
              </div>
            </div>
            <div class="task-title-text">{{ t.title }}</div>
            <div class="task-meta">
              <span class="agent-badge" v-if="t.agent_role" :style="{ color: roleColors[t.agent_role] || 'var(--muted-foreground)', background: (roleColors[t.agent_role] || 'var(--muted-foreground)') + '14' }">
                {{ roleLabels[t.agent_role] || t.agent_role }}
              </span>
              <span>{{ t.agent_name || 'Agent #' + t.agent_id }}</span>
              <span v-if="t.created_at">{{ formatDate(t.created_at) }}</span>
            </div>
          </div>

          <!-- Archived tasks section -->
          <div class="archived-section" v-if="archivedTasks.length > 0">
            <button class="archived-header" @click="showArchived = !showArchived">
              <svg
                width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
                :class="{ rotated: showArchived }"
                style="transition: transform var(--transition-fast);"
              >
                <polyline points="9 18 15 12 9 6"/>
              </svg>
              <span>归档任务 ({{ archivedTasks.length }})</span>
            </button>

            <div v-if="showArchived" class="archived-list">
              <!-- Batch toolbar -->
              <div class="archived-toolbar">
                <label class="check-all-label" @click.stop>
                  <input type="checkbox" :checked="archiveChecked.size === archivedTasks.length && archivedTasks.length > 0" @change="toggleAll" />
                  <span>全选</span>
                </label>
                <t-button
                  size="small"
                  theme="danger"
                  variant="outline"
                  :disabled="archiveChecked.size === 0 || archiving"
                  @click="batchDelete"
                >
                  批量删除 ({{ archiveChecked.size }})
                </t-button>
              </div>

              <div
                v-for="t in archivedTasks"
                :key="t.id"
                class="archived-item"
              >
                <input
                  type="checkbox"
                  :checked="archiveChecked.has(t.id)"
                  @click.stop
                  @change="toggleCheck(t.id)"
                  class="archive-checkbox"
                />
                <div class="archived-item-body" @click="selectTask(t)">
                  <div class="task-item-top">
                    <span class="task-id">#{{ t.id }}</span>
                    <span class="task-status" :style="{ color: statusColors[t.status] }">
                      <span class="status-dot" :class="t.status"></span>
                      {{ statusLabels[t.status] || t.status }}
                    </span>
                  </div>
                  <div class="task-title-text">{{ t.title }}</div>
                  <div class="task-meta">
                    <span>{{ t.agent_name || 'Agent #' + t.agent_id }}</span>
                  </div>
                </div>
                <div class="archived-item-acts">
                  <button class="restore-btn" title="恢复" @click="unarchiveTask(t, $event)">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>
                  </button>
                  <button class="del-btn" title="删除" @click="deleteOne(t, $event)">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ── Right: task detail ─────────────────────────── -->
        <div class="task-detail" v-if="selectedTask && taskDetail">
          <div class="detail-header">
            <div>
              <h3>{{ taskDetail.title }}</h3>
              <div class="detail-tags">
                <span class="tag" :style="{ background: statusColors[taskDetail.status] + '18', color: statusColors[taskDetail.status] }">
                  {{ statusLabels[taskDetail.status] || taskDetail.status }}
                </span>
                <span class="tag tag-neutral">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/></svg>
                  {{ taskDetail.agent_name }}
                </span>
                <span v-if="taskDetail.agent_role" class="tag" :style="{ background: (roleColors[taskDetail.agent_role] || 'var(--muted-foreground)') + '18', color: roleColors[taskDetail.agent_role] || 'var(--muted-foreground)' }">
                  {{ roleLabels[taskDetail.agent_role] || taskDetail.agent_role }}
                </span>
                <span class="tag tag-neutral tag-mono">{{ taskDetail.agent_model }}</span>
                <span class="tag tag-neutral">{{ taskDetail.project_name }}</span>
              </div>
            </div>
            <div class="detail-time" v-if="taskDetail.created_at">
              {{ formatDate(taskDetail.created_at) }}
            </div>
          </div>

          <div v-if="taskDetail.description" class="detail-section">
            <h4 class="detail-label">任务描述</h4>
            <div class="desc-box">{{ taskDetail.description }}</div>
          </div>

          <div v-if="loadingDetail" class="loading-box">
            <span class="spinner"></span> 加载中...
          </div>

          <template v-else-if="taskDetail.review">
            <div class="detail-section">
              <div class="detail-label-row">
                <h4 class="detail-label">审查结果</h4>
                <span class="review-status-badge" :style="{ color: reviewStatusColors[taskDetail.review.status] }">
                  {{ reviewStatusLabels[taskDetail.review.status] || taskDetail.review.status }}
                </span>
                <div class="review-actions" v-if="taskDetail.review.status === 'pending'">
                  <t-button size="small" theme="danger" variant="outline" @click="rejectReview">驳回</t-button>
                  <t-button size="small" theme="success" @click="approveReview">通过</t-button>
                </div>
              </div>

              <div class="diff-container" v-if="taskDetail.review.diff_content && taskDetail.review.diff_content !== '# No code changes detected'">
                <MonacoEditor :content="taskDetail.review.diff_content" language="diff" />
              </div>
              <div v-else class="no-diff">无代码变更</div>

              <div class="summary-box" v-if="taskDetail.review.agent_review_summary" v-html="renderMarkdown(taskDetail.review.agent_review_summary)" />

              <div v-if="taskDetail.review.human_feedback" class="feedback-box">
                <h4>人工反馈</h4>
                <p>{{ taskDetail.review.human_feedback }}</p>
              </div>
            </div>
          </template>

          <div v-else class="no-review">
            <span class="spinner" v-if="taskDetail.status === 'running' || taskDetail.status === 'pending'"></span>
            <p v-if="taskDetail.status === 'running'">Agent 正在执行中...</p>
            <p v-else-if="taskDetail.status === 'pending'">等待执行...</p>
            <p v-else-if="taskDetail.status === 'failed'">任务执行失败，无审查结果</p>
          </div>
        </div>

        <div v-else class="empty-detail">
          <div class="empty-detail-icon">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M9 11l3 3 8-8"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
          </div>
          <p>选择左侧任务查看详情</p>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page-root { height: 100%; display: flex; flex-direction: column; max-width: 1400px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-shrink: 0; }
.header-right { display: flex; align-items: center; gap: 8px; }

.task-layout {
  flex: 1; display: flex; gap: 0;
  border: 1px solid var(--surface-border); border-radius: var(--radius-lg);
  overflow: hidden; min-height: 0;
  box-shadow: var(--shadow-surface);
}

.task-list {
  width: 300px; border-right: 1px solid var(--surface-border);
  background: var(--app-shell); overflow-y: auto; flex-shrink: 0;
  display: flex; flex-direction: column;
}
.task-item {
  padding: 12px 14px; border-bottom: 1px solid var(--surface-border);
  cursor: pointer; transition: background var(--transition-fast);
}
.task-item:hover { background: var(--surface-hover); }
.task-item.active { background: var(--primary-lighter); border-left: 3px solid var(--primary); padding-left: 11px; }
.task-item-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.task-item-actions { display: flex; align-items: center; gap: 4px; }
.task-id { font-size: 12px; font-weight: 700; color: var(--muted-foreground); font-family: var(--font-mono); }
.task-status { font-size: 11px; font-weight: 600; display: flex; align-items: center; gap: 4px; }
.task-title-text { font-size: 13.5px; font-weight: 600; color: var(--foreground); margin-bottom: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-meta { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--muted-foreground); flex-wrap: wrap; }
.agent-badge {
  font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: var(--radius-sm);
  white-space: nowrap; flex-shrink: 0;
}

/* Archive button on active tasks */
.archive-btn {
  width: 24px; height: 24px; border-radius: var(--radius-sm);
  border: none; background: transparent; color: var(--muted-foreground);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: all var(--transition-fast); opacity: 0;
}
.task-item:hover .archive-btn { opacity: 1; }
.archive-btn:hover { background: var(--surface-hover); color: var(--foreground); }

/* Archived section */
.archived-section { border-top: 2px solid var(--surface-border); margin-top: auto; }
.archived-header {
  display: flex; align-items: center; gap: 6px;
  width: 100%; padding: 10px 14px;
  border: none; background: transparent; color: var(--muted-foreground);
  font-size: 12px; font-weight: 600; cursor: pointer;
  transition: color var(--transition-fast);
}
.archived-header:hover { color: var(--foreground); }
.archived-header .rotated { transform: rotate(90deg); }

.archived-list { border-top: 1px solid var(--surface-border); }

.archived-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 12px; background: var(--surface-hover);
  border-bottom: 1px solid var(--surface-border);
}
.check-all-label { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--muted-foreground); cursor: pointer; user-select: none; }

.archived-item {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 10px 8px 8px; border-bottom: 1px solid var(--surface-border);
  transition: background var(--transition-fast);
  opacity: 0.7;
}
.archived-item:hover { background: var(--surface-hover); opacity: 1; }
.archive-checkbox { flex-shrink: 0; cursor: pointer; }
.archived-item-body { flex: 1; min-width: 0; cursor: pointer; }
.archived-item-acts { display: flex; gap: 2px; flex-shrink: 0; opacity: 0; transition: opacity var(--transition-fast); }
.archived-item:hover .archived-item-acts { opacity: 1; }

.restore-btn, .del-btn {
  width: 24px; height: 24px; border-radius: var(--radius-sm);
  border: none; background: transparent; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all var(--transition-fast);
}
.restore-btn { color: var(--muted-foreground); }
.restore-btn:hover { background: var(--primary-light); color: var(--primary); }
.del-btn { color: var(--muted-foreground); }
.del-btn:hover { background: var(--danger-light); color: var(--danger); }

/* ── Detail panel (unchanged) ────────────────────────── */
.task-detail { flex: 1; overflow-y: auto; padding: 20px 24px; background: var(--page-canvas); }
.detail-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.detail-header h3 { font-size: 17px; font-weight: 700; margin: 0 0 8px; }
.detail-tags { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.detail-time { font-size: 12px; color: var(--muted-foreground); flex-shrink: 0; }

.detail-section { margin-bottom: 20px; }
.detail-label { font-size: 12px; font-weight: 700; color: var(--muted-foreground); margin: 0 0 8px; text-transform: uppercase; letter-spacing: 0.5px; }
.detail-label-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
.detail-label-row .detail-label { margin: 0; }
.review-status-badge { font-size: 12px; font-weight: 700; }

.review-actions { display: flex; gap: 6px; margin-left: auto; }

.desc-box {
  background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-md); padding: 12px 14px;
  font-size: 13.5px; line-height: 1.6; color: var(--foreground); white-space: pre-wrap;
}

.diff-container {
  border: 1px solid var(--surface-border); border-radius: var(--radius-md);
  overflow: hidden; min-height: 150px; max-height: 400px; margin-bottom: 12px;
}
.no-diff { font-size: 13px; color: var(--muted-foreground); padding: 16px; text-align: center; background: var(--surface); border: 1px solid var(--surface-border); border-radius: var(--radius-md); margin-bottom: 12px; }

.summary-box {
  background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-md); padding: 14px 16px;
  font-size: 13.5px; line-height: 1.7; white-space: pre-wrap;
}
.summary-box :deep(h3) { font-size: 14px; font-weight: 700; margin: 0 0 6px; }
.summary-box :deep(h4) { font-size: 13px; font-weight: 600; margin: 8px 0 4px; }
.summary-box :deep(li) { margin-left: 16px; }

.feedback-box {
  margin-top: 12px; background: var(--danger-light);
  border: 1px solid oklch(0.586 0.225 27 / 0.2); border-radius: var(--radius-md);
  padding: 12px 14px;
}
.feedback-box h4 { font-size: 12px; font-weight: 700; color: var(--danger); margin: 0 0 4px; }
.feedback-box p { font-size: 13px; margin: 0; white-space: pre-wrap; }

.no-review { display: flex; align-items: center; gap: 10px; padding: 32px; color: var(--muted-foreground); font-size: 14px; }
.loading-box { display: flex; align-items: center; gap: 10px; padding: 32px; color: var(--muted-foreground); font-size: 14px; }

.empty-detail { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; background: var(--page-canvas); }
.empty-detail-icon { color: var(--muted-foreground); opacity: 0.5; }
.empty-detail p { font-size: 13px; color: var(--muted-foreground); }
</style>
