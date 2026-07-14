<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useProjectStore } from '../stores/project'
import { useWebSocketStore } from '../stores/websocket'
import MonacoEditor from '../components/MonacoEditor.vue'
import api from '../api'

const store = useProjectStore()
const wsStore = useWebSocketStore()

const tasks = ref<any[]>([])
const selectedTask = ref<any>(null)
const taskDetail = ref<any>(null)
const loadingDetail = ref(false)
const filterProjectId = computed(() => store.currentProject?.id ?? null)

const statusLabels: Record<string, string> = {
  pending: '等待中', running: '执行中', completed: '已完成', failed: '失败',
}
const statusColors: Record<string, string> = {
  pending: 'var(--muted-foreground)',
  running: 'var(--brand)',
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

let unsubTask: (() => void) | null = null

onMounted(() => {
  // Real-time: refresh task list on any task_update
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
  if (!pid) { tasks.value = []; return }
  await loadTasks()
}, { immediate: true })

async function loadTasks() {
  if (!filterProjectId.value) return
  const { data } = await api.get(`/projects/${filterProjectId.value}/tasks`)
  tasks.value = data
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

async function approveReview() {
  if (!taskDetail.value?.review) return
  try {
    await api.post(`/reviews/${taskDetail.value.review.id}/approve`)
    ElMessage.success('审查已通过，已提交到 Git')
    if (selectedTask.value) await selectTask(selectedTask.value)
    await loadTasks()
  } catch { ElMessage.error('操作失败') }
}

async function rejectReview() {
  if (!taskDetail.value?.review) return
  try {
    await api.post(`/reviews/${taskDetail.value.review.id}/reject`)
    ElMessage.warning('审查已驳回')
    if (selectedTask.value) await selectTask(selectedTask.value)
    await loadTasks()
  } catch { ElMessage.error('操作失败') }
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
        <button class="btn-ghost-sm" @click="loadTasks()" title="刷新">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        </button>
      </div>
    </div>

    <div v-if="!filterProjectId" class="empty-card">
      <div class="empty-icon">📋</div>
      <h3>请先选择一个项目</h3>
    </div>

    <template v-else>
      <div v-if="tasks.length === 0" class="empty-card">
        <div class="empty-icon">📝</div>
        <h3>暂无任务</h3>
        <p>前往 <router-link to="/agents">Agent 池</router-link> 创建任务</p>
      </div>

      <div v-else class="task-layout">
        <!-- Left: task list -->
        <div class="task-list">
          <div
            v-for="t in tasks"
            :key="t.id"
            class="task-item"
            :class="{ active: selectedTask?.id === t.id }"
            @click="selectTask(t)"
          >
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
              <span v-if="t.created_at">{{ formatDate(t.created_at) }}</span>
            </div>
          </div>
        </div>

        <!-- Right: detail panel -->
        <div class="task-detail" v-if="selectedTask && taskDetail">
          <!-- Task info header -->
          <div class="detail-header">
            <div>
              <h3>{{ taskDetail.title }}</h3>
              <div class="detail-tags">
                <span class="tag-status" :style="{ background: statusColors[taskDetail.status] + '18', color: statusColors[taskDetail.status] }">
                  {{ statusLabels[taskDetail.status] || taskDetail.status }}
                </span>
                <span class="tag-agent">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/></svg>
                  {{ taskDetail.agent_name }}
                </span>
                <span class="tag-model">{{ taskDetail.agent_model }}</span>
                <span class="tag-project">{{ taskDetail.project_name }}</span>
              </div>
            </div>
            <div class="detail-time" v-if="taskDetail.created_at">
              {{ formatDate(taskDetail.created_at) }}
            </div>
          </div>

          <!-- Description -->
          <div v-if="taskDetail.description" class="detail-section">
            <h4 class="detail-label">任务描述</h4>
            <div class="desc-box">{{ taskDetail.description }}</div>
          </div>

          <!-- Loading -->
          <div v-if="loadingDetail" class="loading-box">
            <span class="spinner"></span> 加载中...
          </div>

          <!-- Review / Result -->
          <template v-else-if="taskDetail.review">
            <div class="detail-section">
              <div class="detail-label-row">
                <h4 class="detail-label">审查结果</h4>
                <span class="review-status-badge" :style="{ color: reviewStatusColors[taskDetail.review.status] }">
                  {{ reviewStatusLabels[taskDetail.review.status] || taskDetail.review.status }}
                </span>
                <div class="review-actions" v-if="taskDetail.review.status === 'pending'">
                  <button class="btn-reject-sm" @click="rejectReview">驳回</button>
                  <button class="btn-approve-sm" @click="approveReview">通过</button>
                </div>
              </div>

              <!-- Diff -->
              <div class="diff-container" v-if="taskDetail.review.diff_content && taskDetail.review.diff_content !== '# No code changes detected'">
                <MonacoEditor
                  :content="taskDetail.review.diff_content"
                  language="diff"
                />
              </div>
              <div v-else class="no-diff">无代码变更</div>

              <!-- Agent summary -->
              <div class="summary-box" v-if="taskDetail.review.agent_review_summary" v-html="renderMarkdown(taskDetail.review.agent_review_summary)" />

              <!-- Human feedback -->
              <div v-if="taskDetail.review.human_feedback" class="feedback-box">
                <h4>人工反馈</h4>
                <p>{{ taskDetail.review.human_feedback }}</p>
              </div>
            </div>
          </template>

          <!-- No review yet (still running / pending) -->
          <div v-else class="no-review">
            <span class="spinner" v-if="taskDetail.status === 'running' || taskDetail.status === 'pending'"></span>
            <p v-if="taskDetail.status === 'running'">Agent 正在执行中...</p>
            <p v-else-if="taskDetail.status === 'pending'">等待执行...</p>
            <p v-else-if="taskDetail.status === 'failed'">任务执行失败，无审查结果</p>
          </div>
        </div>

        <div v-else class="empty-detail">
          <span class="empty-icon">👈</span>
          <p>选择左侧任务查看详情</p>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page-root { height: 100%; display: flex; flex-direction: column; max-width: 1400px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-shrink: 0; }
.page-title { font-size: 22px; font-weight: 700; margin: 0; }
.page-desc { font-size: 13.5px; color: var(--muted-foreground); margin: 4px 0 0; }
.header-right { display: flex; align-items: center; gap: 8px; }

.project-select {
  padding: 7px 12px; border: 1px solid var(--input); border-radius: var(--radius-md);
  font-size: 13.5px; background: var(--surface); color: var(--foreground); outline: none; min-width: 200px;
}

.btn-ghost-sm {
  width: 32px; height: 32px; border-radius: var(--radius-md); border: none;
  background: transparent; color: var(--muted-foreground); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
}
.btn-ghost-sm:hover { background: var(--surface-hover); color: var(--foreground); }

/* ── Layout ──────────────────────────────────────── */
.task-layout {
  flex: 1; display: flex; gap: 0;
  border: 1px solid var(--surface-border); border-radius: var(--radius-lg);
  overflow: hidden; min-height: 0;
}

.task-list {
  width: 300px; border-right: 1px solid var(--surface-border);
  background: var(--app-shell); overflow-y: auto; flex-shrink: 0;
}
.task-item {
  padding: 12px 14px; border-bottom: 1px solid var(--surface-border);
  cursor: pointer; transition: background 0.12s;
}
.task-item:hover { background: var(--surface-hover); }
.task-item.active { background: var(--surface-selected); }
.task-item-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.task-id { font-size: 12px; font-weight: 700; color: var(--muted-foreground); font-family: var(--font-mono); }
.task-status { font-size: 11px; font-weight: 600; display: flex; align-items: center; gap: 4px; }
.task-title-text { font-size: 13.5px; font-weight: 600; color: var(--foreground); margin-bottom: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-meta { display: flex; justify-content: space-between; font-size: 11px; color: var(--muted-foreground); }

.status-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; display: inline-block; }
.status-dot.running { animation: pulse 1.5s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

/* ── Detail ──────────────────────────────────────── */
.task-detail { flex: 1; overflow-y: auto; padding: 20px 24px; background: var(--page-canvas); }
.detail-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.detail-header h3 { font-size: 17px; font-weight: 700; margin: 0 0 8px; }
.detail-tags { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.tag-status { padding: 2px 8px; border-radius: 99px; font-size: 11px; font-weight: 600; }
.tag-agent, .tag-model, .tag-project {
  padding: 2px 7px; border-radius: 99px; font-size: 11px; font-weight: 500;
  color: var(--muted-foreground); background: var(--surface-hover);
  display: flex; align-items: center; gap: 3px;
}
.detail-time { font-size: 12px; color: var(--muted-foreground); flex-shrink: 0; }

.detail-section { margin-bottom: 20px; }
.detail-label { font-size: 12px; font-weight: 700; color: var(--muted-foreground); margin: 0 0 8px; text-transform: uppercase; letter-spacing: 0.5px; }
.detail-label-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
.detail-label-row .detail-label { margin: 0; }
.review-status-badge { font-size: 12px; font-weight: 700; }

.review-actions { display: flex; gap: 6px; margin-left: auto; }
.btn-approve-sm {
  padding: 5px 12px; border-radius: var(--radius-md); border: none;
  background: var(--success); color: #fff; font-size: 12px; font-weight: 600; cursor: pointer;
}
.btn-approve-sm:hover { opacity: 0.85; }
.btn-reject-sm {
  padding: 5px 12px; border-radius: var(--radius-md); border: none;
  background: oklch(0.577 0.245 27 / 0.1); color: var(--danger); font-size: 12px; font-weight: 600; cursor: pointer;
}
.btn-reject-sm:hover { background: oklch(0.577 0.245 27 / 0.18); }

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
  margin-top: 12px; background: oklch(0.577 0.245 27 / 0.06);
  border: 1px solid oklch(0.577 0.245 27 / 0.2); border-radius: var(--radius-md);
  padding: 12px 14px;
}
.feedback-box h4 { font-size: 12px; font-weight: 700; color: var(--danger); margin: 0 0 4px; }
.feedback-box p { font-size: 13px; margin: 0; white-space: pre-wrap; }

.no-review { display: flex; align-items: center; gap: 10px; padding: 32px; color: var(--muted-foreground); font-size: 14px; }
.spinner { width: 16px; height: 16px; border: 2px solid var(--surface-border); border-top-color: var(--brand); border-radius: 50%; animation: spin 0.8s linear infinite; display: inline-block; }
@keyframes spin { to { transform: rotate(360deg); } }

.loading-box { display: flex; align-items: center; gap: 10px; padding: 32px; color: var(--muted-foreground); font-size: 14px; }

/* ── Empty ──────────────────────────────────────── */
.empty-card { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 64px 32px; }
.empty-icon { font-size: 40px; margin-bottom: 12px; }
.empty-card h3 { font-size: 16px; font-weight: 600; margin: 0 0 6px; }
.empty-card p { font-size: 13px; color: var(--muted-foreground); margin: 0; }
.empty-card a { color: var(--brand); }

.empty-detail { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; background: var(--page-canvas); }
.empty-detail .empty-icon { font-size: 28px; }
.empty-detail p { font-size: 13px; color: var(--muted-foreground); }
</style>
