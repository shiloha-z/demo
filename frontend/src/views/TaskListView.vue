<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import { useProjectStore } from '../stores/project'
import { useWebSocketStore } from '../stores/websocket'
import DiffViewer from '../components/DiffViewer.vue'
import PipelineStepper from '../components/PipelineStepper.vue'
import TaskTimeline from '../components/TaskTimeline.vue'
import type { StageState } from '../components/PipelineStepper.vue'
import api, { getErrorMessage } from '../api'
import { renderMarkdown } from '../utils/markdown'

const store = useProjectStore()
const wsStore = useWebSocketStore()

const tasks = ref<any[]>([])
const archivedTasks = ref<any[]>([])
const selectedTask = ref<any>(null)
const taskDetail = ref<any>(null)
const loadingDetail = ref(false)
const sortBy = ref('created_desc')
const showArchived = ref(false)
const archiveChecked = ref<Set<number>>(new Set())
const taskProgress = ref<{ message: string; step: string; timestamp: string }[]>([])
const archiving = ref(false)
const timelineDrawerVisible = ref(false)
const showWorkspace = ref(false)
const taskFiles = ref<any[]>([])
const selectedTaskFile = ref<any>(null)
const loadingTaskFiles = ref(false)
const statusFilter = ref('all')
const filterProjectId = computed(() => store.currentProject?.id ?? null)

// Pipeline stepper state
const pipelineStages = ref<StageState[]>([
  { key: 'code_gen',   label: '代码工程师', icon: 'code',   status: 'waiting', startedAt: null, doneAt: null },
  { key: 'reviewer',   label: '代码审查员', icon: 'eye',    status: 'waiting', startedAt: null, doneAt: null },
  { key: 'security',   label: '安全审查员', icon: 'shield', status: 'waiting', startedAt: null, doneAt: null },
  { key: 'summarizer', label: '审查汇总员', icon: 'file',   status: 'waiting', startedAt: null, doneAt: null },
])

// Real-time code preview
const codePreviewDiff = ref<string | null>(null)

const statusLabels: Record<string, string> = {
  pending: '等待中', running: '执行中', paused: '已暂停', reviewing: '待审核',
  approved: '已通过', rejected: '已驳回', completed: '已完成', failed: '失败',
}
const statusColors: Record<string, string> = {
  pending: 'var(--warning)',
  running: 'var(--primary)',
  paused: '#8b5cf6',
  reviewing: '#f59e0b',
  approved: 'var(--success)',
  rejected: 'var(--danger)',
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
const runnerLabels: Record<string, string> = {
  crewai: 'CrewAI', claude_code: 'Claude Code', opencode: 'OpenCode',
}
const runnerColors: Record<string, string> = {
  crewai: 'var(--primary)', claude_code: '#d97706', opencode: 'var(--success)',
}
const roleColors: Record<string, string> = {
  code_gen: 'var(--primary)', reviewer: 'var(--warning)', security: 'var(--danger)',
}

// ── Step icon mapping ──────────────────────────────────────────
const stepIcons: Record<string, string> = {
  start: '🚀', goal: '📋', desc: '📝', prepare: '📂', branch: '🌿',
  agent_start: '🤖', model: '🧠',
  step_1_codegen: '⚙️', step_1_detail: '🔍', step_1_done: '✅',
  step_2_done: '✅', step_3_done: '✅', step_4_done: '✅',
  report_done: '📄', commit: '💾', committed: '📌',
  diff: '📊', diff_done: '📊', diff_empty: '⚠️',
  code_preview: '👁️', cleanup: '🔙', done: '🎉',
  error: '❌',
}

function stepIcon(step: string): string {
  return stepIcons[step] || '🔄'
}

function formatTimestamp(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

// ── Timeline tasks computed from loaded tasks ──────────────────
const timelineTasks = computed(() => {
  return tasks.value
    .filter(t => t.started_at)
    .map(t => ({
      id: t.id,
      title: t.title,
      status: t.status,
      startedAt: t.started_at,
      completedAt: t.completed_at,
      createdAt: t.created_at,
      agentName: t.agent_name || `Agent #${t.agent_id}`,
      agentRole: t.agent_role || '',
    }))
})

// ── WebSocket subscriptions ────────────────────────────────────
let unsubTask: (() => void) | null = null
let unsubProgress: (() => void) | null = null
let unsubStage: (() => void) | null = null
let unsubPreview: (() => void) | null = null

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
  unsubProgress = wsStore.on('task_progress', (data: any) => {
    if (selectedTask.value?.id === data.task_id) {
      taskProgress.value.push({
        message: data.message,
        step: data.step,
        timestamp: data.timestamp || new Date().toISOString(),
      })
    }
  })
  unsubStage = wsStore.on('pipeline_stage', (data: any) => {
    if (selectedTask.value?.id === data.task_id) {
      const stage = pipelineStages.value.find(s => s.key === data.stage)
      if (stage) {
        stage.status = data.status
        if (data.status === 'running' && !stage.startedAt) {
          stage.startedAt = data.timestamp
        }
        if (data.status === 'done') {
          stage.doneAt = data.timestamp
        }
        // Trigger reactivity
        pipelineStages.value = [...pipelineStages.value]
      }
    }
  })
  unsubPreview = wsStore.on('code_preview', (data: any) => {
    if (selectedTask.value?.id === data.task_id) {
      codePreviewDiff.value = data.diff
    }
  })
})

onUnmounted(() => {
  if (unsubTask) unsubTask()
  if (unsubProgress) unsubProgress()
  if (unsubStage) unsubStage()
  if (unsubPreview) unsubPreview()
})

watch(() => store.currentProject?.id, async (pid) => {
  if (!pid) { tasks.value = []; archivedTasks.value = []; return }
  await loadTasks()
}, { immediate: true })

async function loadTasks() {
  if (!filterProjectId.value) return
  const [active, archived] = await Promise.all([
    api.get(`/projects/${filterProjectId.value}/tasks`, { params: { sort: sortBy.value } }),
    api.get(`/projects/${filterProjectId.value}/tasks`, { params: { archived: true } }),
  ])
  tasks.value = active.data
  archivedTasks.value = archived.data
  archiveChecked.value = new Set()
}

const filteredTasks = computed(() => {
  if (statusFilter.value === 'all') return tasks.value
  return tasks.value.filter((t: any) => t.status === statusFilter.value)
})

async function selectTask(task: any) {
  if (selectedTask.value?.id !== task.id) {
    taskProgress.value = []
    codePreviewDiff.value = null
    showWorkspace.value = false
    taskFiles.value = []
    selectedTaskFile.value = null
    // Reset pipeline stages
    pipelineStages.value = [
      { key: 'code_gen',   label: '代码工程师', icon: 'code',   status: task.status === 'running' ? 'running' : 'waiting', startedAt: null, doneAt: null },
      { key: 'reviewer',   label: '代码审查员', icon: 'eye',    status: 'waiting', startedAt: null, doneAt: null },
      { key: 'security',   label: '安全审查员', icon: 'shield', status: 'waiting', startedAt: null, doneAt: null },
      { key: 'summarizer', label: '审查汇总员', icon: 'file',   status: 'waiting', startedAt: null, doneAt: null },
    ]
    // If task is already done/reviewing, mark all as done
    if (task.status === 'reviewing' || task.status === 'approved' || task.status === 'rejected') {
      pipelineStages.value.forEach(s => { s.status = 'done' })
      pipelineStages.value = [...pipelineStages.value]
    }
  }
  selectedTask.value = task
  loadingDetail.value = true
  try {
    const { data } = await api.get(`/projects/${task.project_id}/tasks/${task.id}`)
    taskDetail.value = data
    // Backfill code preview from stored review diff (WebSocket event may have been missed)
    if (!codePreviewDiff.value && data?.review?.diff_content && data.review.diff_content !== '# No code changes detected') {
      codePreviewDiff.value = data.review.diff_content
    }
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

const feedbackDialogVisible = ref(false)
const feedbackText = ref('')
const feedbackSubmitting = ref(false)

function openRejectDialog() {
  feedbackText.value = ''
  feedbackDialogVisible.value = true
}

async function submitRejectWithFeedback() {
  if (!taskDetail.value?.review || !feedbackText.value.trim()) return
  feedbackSubmitting.value = true
  try {
    await api.post(`/reviews/${taskDetail.value.review.id}/reject`, {
      feedback: feedbackText.value.trim(),
    })
    MessagePlugin.warning('已驳回，Agent 将根据反馈重新执行')
    feedbackDialogVisible.value = false
    if (selectedTask.value) await selectTask(selectedTask.value)
    await loadTasks()
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '操作失败')) }
  finally { feedbackSubmitting.value = false }
}

async function closeReview() {
  if (!taskDetail.value?.review) return
  const confirmDialog = DialogPlugin.confirm({
    header: '确认结束',
    body: '确定要结束此审查吗？任务将被标记为驳回且不会重新执行。',
    confirmBtn: { content: '确认结束', theme: 'danger' },
    cancelBtn: '取消',
    onConfirm: async () => {
      try {
        await api.post(`/reviews/${taskDetail.value.review.id}/close`)
        MessagePlugin.warning('审查已结束')
        if (selectedTask.value) await selectTask(selectedTask.value)
        await loadTasks()
      } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '操作失败')) }
      confirmDialog.destroy()
    },
  })
}

function formatDate(d: string) {
  if (!d) return ''
  return new Date(d).toLocaleString('zh-CN')
}

function hasActivePipeline(task: any): boolean {
  return task?.status === 'running' || task?.status === 'pending'
}

// ── Task workspace ──────────────────────────────────────────────
function toggleWorkspace() {
  showWorkspace.value = !showWorkspace.value
  if (showWorkspace.value) {
    loadTaskFiles(selectedTask.value.id)
  }
}

async function loadTaskFiles(taskId: number) {
  const pid = store.currentProject?.id
  if (!pid) return
  loadingTaskFiles.value = true
  taskFiles.value = []
  try {
    const { data } = await api.get(`/projects/${pid}/tasks/${taskId}/files`)
    taskFiles.value = data.files || []
  } catch { taskFiles.value = [] }
  finally { loadingTaskFiles.value = false }
}

async function loadTaskFile(taskId: number, path: string) {
  const pid = store.currentProject?.id
  if (!pid) return
  try {
    const { data } = await api.get(`/projects/${pid}/tasks/${taskId}/file`, { params: { path } })
    selectedTaskFile.value = { path, content: data.content }
  } catch { /* ignore */ }
}

function fileIcon(filename: string): string {
  const ext = (filename || '').split('.').pop()?.toLowerCase() || ''
  const map: Record<string, string> = {
    py: '🐍', js: '🟨', ts: '🟦', vue: '💚', jsx: '⚛️', tsx: '⚛️',
    css: '🎨', scss: '🎨', html: '🌐', md: '📝', json: '📋',
    yaml: '⚙️', yml: '⚙️', toml: '⚙️', xml: '📋',
    go: '🔵', rs: '🦀', java: '☕', c: '⚙️', cpp: '⚙️', h: '📄',
    png: '🖼️', jpg: '🖼️', jpeg: '🖼️', gif: '🖼️', svg: '🖼️',
  }
  return map[ext] || '📄'
}

// ── Create task dialog ──────────────────────────────────────────
const showCreateTask = ref(false)
const agents = ref<any[]>([])
const newTaskForm = ref({ agent_id: null as number | null, title: '', description: '' })
const creatingTask = ref(false)

async function loadAgents() {
  try {
    const { data } = await api.get('/agents')
    agents.value = data
  } catch { /* ignore */ }
}

function openCreateTaskDialog() {
  if (!filterProjectId.value) {
    MessagePlugin.warning('请先在侧边栏选择一个项目')
    return
  }
  newTaskForm.value = { agent_id: null, title: '', description: '' }
  loadAgents()
  showCreateTask.value = true
}

async function submitCreateTask() {
  if (!newTaskForm.value.title || !newTaskForm.value.agent_id || !filterProjectId.value) return
  creatingTask.value = true
  try {
    await api.post(`/projects/${filterProjectId.value}/tasks`, {
      title: newTaskForm.value.title,
      description: newTaskForm.value.description,
      agent_id: newTaskForm.value.agent_id,
    })
    MessagePlugin.success('任务已创建，待开始执行')
    showCreateTask.value = false
    await loadTasks()
  } catch (e: any) {
    MessagePlugin.error(getErrorMessage(e, '创建任务失败'))
  } finally {
    creatingTask.value = false
  }
}

async function startTask(task: any, event: Event) {
  event.stopPropagation()
  try {
    await api.post(`/projects/${task.project_id}/tasks/${task.id}/start`)
    MessagePlugin.success(`任务 #${task.id} 已开始执行`)
    await loadTasks()
  } catch (e: any) {
    MessagePlugin.error(getErrorMessage(e, '启动任务失败'))
  }
}

async function stopTask(task: any, event: Event) {
  event.stopPropagation()
  try {
    await api.post(`/projects/${task.project_id}/tasks/${task.id}/stop`)
    MessagePlugin.success(`任务 #${task.id} 已暂停`)
    await loadTasks()
    if (selectedTask.value?.id === task.id) {
      selectedTask.value = null
      taskDetail.value = null
    }
  } catch (e: any) {
    MessagePlugin.error(getErrorMessage(e, '暂停任务失败'))
  }
}

async function resumeTask(task: any, event: Event) {
  event.stopPropagation()
  try {
    await api.post(`/projects/${task.project_id}/tasks/${task.id}/resume`)
    MessagePlugin.success(`任务 #${task.id} 已重新开始执行`)
    await loadTasks()
  } catch (e: any) {
    MessagePlugin.error(getErrorMessage(e, '恢复任务失败'))
  }
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
        <t-button theme="primary" size="small" @click="openCreateTaskDialog">
          <template #icon>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          </template>
          创建任务
        </t-button>
        <t-select v-model="statusFilter" size="small" style="width: 100px" placeholder="全部状态">
          <t-option value="all" label="全部状态" />
          <t-option value="pending" label="等待中" />
          <t-option value="running" label="执行中" />
          <t-option value="paused" label="已暂停" />
          <t-option value="reviewing" label="待审核" />
          <t-option value="approved" label="已通过" />
          <t-option value="rejected" label="已驳回" />
          <t-option value="failed" label="失败" />
        </t-select>
        <t-select v-model="sortBy" size="small" style="width: 110px" @change="loadTasks()">
          <t-option value="created_desc" label="最新创建" />
          <t-option value="created_asc" label="最早创建" />
          <t-option value="status" label="按状态" />
          <t-option value="title_asc" label="标题 A-Z" />
          <t-option value="title_desc" label="标题 Z-A" />
        </t-select>
        <t-button shape="square" variant="text" @click="loadTasks()" title="刷新">
          <template #icon>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
          </template>
        </t-button>
        <t-button size="small" variant="outline" @click="timelineDrawerVisible = true" title="任务时间线">
          <template #icon>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
          </template>
          时间线
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
            v-for="t in filteredTasks"
            :key="t.id"
            class="task-item"
            :class="{ active: selectedTask?.id === t.id }"
            @click="selectTask(t)"
          >
            <div class="task-item-top">
              <span class="task-id">#{{ t.id }}</span>
              <div class="task-item-actions">
                <button
                  v-if="t.status === 'running'"
                  class="stop-btn"
                  title="停止"
                  @click="stopTask(t, $event)"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none"><rect x="4" y="4" width="16" height="16" rx="2"/></svg>
                </button>
                <button
                  v-if="t.status === 'paused'"
                  class="resume-btn"
                  title="重新执行"
                  @click="resumeTask(t, $event)"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>
                </button>
                <button
                  v-if="t.status === 'pending'"
                  class="start-btn"
                  title="开始执行"
                  @click="startTask(t, $event)"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                </button>
                <button
                  v-if="t.status !== 'pending' && t.status !== 'running' && t.status !== 'reviewing' && t.status !== 'paused'"
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
                <span v-if="taskDetail.agent_runner_type" class="tag" :style="{ background: (runnerColors[taskDetail.agent_runner_type] || 'var(--muted-foreground)') + '18', color: runnerColors[taskDetail.agent_runner_type] || 'var(--muted-foreground)' }">
                  {{ runnerLabels[taskDetail.agent_runner_type] || taskDetail.agent_runner_type }}
                </span>
                <span class="tag tag-neutral">{{ taskDetail.project_name }}</span>
              </div>
            </div>
            <div class="detail-header-right">
              <button
                v-if="['running','paused','reviewing'].includes(taskDetail.status)"
                class="workspace-btn"
                :class="{ active: showWorkspace }"
                @click="toggleWorkspace()"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                <span>工作空间</span>
              </button>
              <div class="detail-time" v-if="taskDetail.created_at">
                {{ formatDate(taskDetail.created_at) }}
              </div>
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
            <!-- Pipeline Stepper — show if task completed with stages -->
            <div v-if="taskDetail.status === 'reviewing' || taskDetail.status === 'approved' || taskDetail.status === 'rejected'" class="detail-section">
              <h4 class="detail-label">流水线阶段</h4>
              <PipelineStepper :stages="pipelineStages" />
            </div>

            <!-- Progress log — with timestamps -->
            <div v-if="taskProgress.length > 0" class="progress-log">
              <div v-for="(entry, i) in taskProgress" :key="i" class="progress-entry" :class="entry.step">
                <span class="progress-time">{{ formatTimestamp(entry.timestamp) }}</span>
                <span class="progress-icon">{{ stepIcon(entry.step) }}</span>
                <span class="progress-msg">{{ entry.message }}</span>
              </div>
            </div>

            <!-- Real-time code preview -->
            <div v-if="codePreviewDiff" class="detail-section">
              <h4 class="detail-label">代码预览（实时）</h4>
              <div class="diff-container">
                <DiffViewer :diff="codePreviewDiff" />
              </div>
            </div>

            <div class="detail-section">
              <div class="detail-label-row">
                <h4 class="detail-label">审查结果</h4>
                <span class="review-status-badge" :style="{ color: reviewStatusColors[taskDetail.review.status] }">
                  {{ reviewStatusLabels[taskDetail.review.status] || taskDetail.review.status }}
                </span>
                <div class="review-actions" v-if="taskDetail.review.status === 'pending'">
                  <t-button size="small" theme="warning" variant="outline" @click="openRejectDialog">驳回并修改</t-button>
                  <t-button size="small" theme="success" @click="approveReview">通过</t-button>
                  <t-button size="small" theme="default" variant="text" @click="closeReview">结束</t-button>
                </div>
              </div>

              <div class="diff-container" v-if="taskDetail.review.diff_content && taskDetail.review.diff_content !== '# No code changes detected'">
                <DiffViewer :diff="taskDetail.review.diff_content" />
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
            <!-- Pipeline Stepper — show real-time during execution -->
            <div v-if="hasActivePipeline(taskDetail)" class="detail-section">
              <h4 class="detail-label">流水线阶段</h4>
              <PipelineStepper :stages="pipelineStages" />
            </div>

            <!-- Progress log with timestamps -->
            <div v-if="taskProgress.length > 0" class="progress-log">
              <div v-for="(entry, i) in taskProgress" :key="i" class="progress-entry" :class="entry.step">
                <span class="progress-time">{{ formatTimestamp(entry.timestamp) }}</span>
                <span class="progress-icon">{{ stepIcon(entry.step) }}</span>
                <span class="progress-msg">{{ entry.message }}</span>
              </div>
            </div>

            <!-- Real-time code preview (during execution) -->
            <div v-if="codePreviewDiff" class="detail-section">
              <h4 class="detail-label">代码预览（实时）</h4>
              <div class="diff-container">
                <DiffViewer :diff="codePreviewDiff" />
              </div>
            </div>

            <div class="no-review-status">
              <span class="spinner" v-if="taskDetail.status === 'running' || taskDetail.status === 'pending'"></span>
              <p v-if="taskDetail.status === 'running'">Agent 正在执行中...</p>
              <p v-else-if="taskDetail.status === 'pending'">等待执行...</p>
              <p v-else-if="taskDetail.status === 'reviewing'">Agent 执行完成，等待审查中...</p>
              <p v-else-if="taskDetail.status === 'failed'">任务执行失败，无审查结果</p>
              <p v-else>当前状态：{{ statusLabels[taskDetail.status] || taskDetail.status }}</p>
            </div>
          </div>

          <!-- Workspace file panel -->
          <div v-if="showWorkspace" class="workspace-panel">
            <div class="workspace-panel-header">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
              <span>工作空间 · 任务 #{{ selectedTask.id }}</span>
              <button class="workspace-close-btn" @click="showWorkspace = false">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
            <div class="workspace-panel-body">
              <div v-if="loadingTaskFiles" class="workspace-loading">
                <span class="spinner"></span> 加载中...
              </div>
              <div v-else-if="taskFiles.length === 0" class="workspace-empty">
                暂无文件（任务可能尚未提交代码）
              </div>
              <div v-else class="workspace-file-list">
                <div
                  v-for="f in taskFiles"
                  :key="f.path"
                  class="workspace-file-item"
                  :class="{ active: selectedTaskFile?.path === f.path }"
                  @click="loadTaskFile(selectedTask.id, f.path)"
                >
                  <span class="workspace-file-icon">{{ f.type === 'tree' ? '📁' : fileIcon(f.name) }}</span>
                  <span class="workspace-file-name">{{ f.name }}</span>
                </div>
              </div>
            </div>
            <div v-if="selectedTaskFile" class="workspace-file-content">
              <div class="workspace-file-content-header">
                <span>{{ selectedTaskFile.path }}</span>
                <button class="workspace-close-btn" @click="selectedTaskFile = null">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
              </div>
              <pre class="workspace-file-code">{{ selectedTaskFile.content }}</pre>
            </div>
          </div>
        </div>

        <div v-else class="empty-detail">
          <div class="empty-detail-icon">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M9 11l3 3 8-8"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
          </div>
          <p>选择左侧任务查看详情</p>
        </div>
      </div>

      <!-- Timeline slide panel — overlays the entire layout -->
      <div class="timeline-slide-panel" :class="{ open: timelineDrawerVisible }">
        <div class="timeline-slide-header">
          <span>任务执行时间线</span>
          <button class="timeline-slide-close" @click="timelineDrawerVisible = false">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="timeline-slide-body">
          <TaskTimeline :tasks="timelineTasks" />
        </div>
      </div>
    </template>

    <!-- Create Task Dialog -->
    <t-dialog v-model:visible="showCreateTask" header="创建任务" width="500px">
      <div class="dialog-form">
        <div class="task-project-info">
          目标项目：<strong>{{ store.currentProject?.name }}</strong>
        </div>
        <label class="field-label">选择 Agent</label>
        <t-select v-model="newTaskForm.agent_id" placeholder="请选择一个 Agent">
          <t-option v-for="a in agents" :key="a.id" :value="a.id" :label="`${a.name} (${roleLabels[a.role] || a.role})`" />
        </t-select>
        <label class="field-label">任务标题</label>
        <t-input v-model="newTaskForm.title" placeholder="例如：写一个用户登录接口" />
        <label class="field-label">详细描述</label>
        <textarea v-model="newTaskForm.description" class="field-textarea" rows="4" placeholder="描述清楚你要 Agent 做什么..." />
      </div>
      <template #footer>
        <t-button theme="default" variant="text" @click="showCreateTask = false">取消</t-button>
        <t-button theme="primary" :disabled="!newTaskForm.title || !newTaskForm.agent_id" :loading="creatingTask" @click="submitCreateTask">创建</t-button>
      </template>
    </t-dialog>

    <!-- Feedback dialog for reject-with-feedback -->
    <t-dialog v-model:visible="feedbackDialogVisible" header="驳回并反馈" width="480px" :confirm-btn="{ content: '提交反馈', theme: 'warning', loading: feedbackSubmitting }" :cancel-btn="{ content: '取消' }" @confirm="submitRejectWithFeedback">
      <div class="feedback-dialog-body">
        <p class="feedback-hint">请说明驳回原因和改进方向，Agent 将根据反馈重新执行此任务。</p>
        <t-textarea v-model="feedbackText" placeholder="例如：登录页面缺少密码强度校验、需要添加手机号验证码登录方式..." :autosize="{ minRows: 3, maxRows: 6 }" />
      </div>
    </t-dialog>
  </div>

</template>

<style scoped>
.page-root { height: 100%; display: flex; flex-direction: column; max-width: 1400px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-shrink: 0; }
.header-right { display: flex; align-items: center; gap: 8px; }

.task-layout {
  flex: 1; display: flex; gap: 0; position: relative;
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

.archive-btn {
  width: 24px; height: 24px; border-radius: var(--radius-sm);
  border: none; background: transparent; color: var(--muted-foreground);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: all var(--transition-fast); opacity: 0;
}
.task-item:hover .archive-btn { opacity: 1; }
.archive-btn:hover { background: var(--surface-hover); color: var(--foreground); }

.start-btn {
  width: 24px; height: 24px; border-radius: var(--radius-sm);
  border: none; background: var(--primary-light); color: var(--primary);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: all var(--transition-fast);
}
.start-btn:hover { background: var(--primary); color: #fff; }

.stop-btn {
  width: 24px; height: 24px; border-radius: var(--radius-sm);
  border: none; background: var(--danger-light); color: var(--danger);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: all var(--transition-fast);
}
.stop-btn:hover { background: var(--danger); color: #fff; }

.resume-btn {
  width: 24px; height: 24px; border-radius: var(--radius-sm);
  border: none; background: oklch(0.55 0.2 260 / 0.12); color: #8b5cf6;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: all var(--transition-fast);
}
.resume-btn:hover { background: #8b5cf6; color: #fff; }

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

/* ── Detail panel ──────────────────────────────────── */
.task-detail { flex: 1; overflow-y: auto; padding: 20px 24px; background: var(--page-canvas); }
.detail-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.detail-header h3 { font-size: 17px; font-weight: 700; margin: 0 0 8px; }
.detail-tags { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.detail-header-right { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.detail-time { font-size: 12px; color: var(--muted-foreground); flex-shrink: 0; }

/* ── Workspace button ────────────────────────────── */
.workspace-btn {
  display: flex; align-items: center; gap: 5px;
  padding: 5px 12px; border: 1px solid var(--surface-border);
  border-radius: var(--radius-md); background: var(--surface);
  color: var(--muted-foreground); font-size: 12px; font-weight: 500;
  font-family: var(--font-sans); cursor: pointer;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}
.workspace-btn:hover, .workspace-btn.active {
  border-color: var(--primary); color: var(--primary);
  background: var(--primary-light);
}

/* ── Workspace panel ─────────────────────────────── */
.workspace-panel {
  border-top: 1px solid var(--surface-border);
  margin-top: 4px;
  display: flex;
  flex-direction: column;
  max-height: 320px;
}
.workspace-panel-header {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 14px;
  font-size: 12px; font-weight: 600; color: var(--foreground);
  background: var(--surface-hover);
  flex-shrink: 0;
}
.workspace-close-btn {
  margin-left: auto;
  width: 22px; height: 22px;
  border: none; background: transparent; color: var(--muted-foreground);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  border-radius: var(--radius-sm);
}
.workspace-close-btn:hover { background: var(--surface-hover); color: var(--foreground); }
.workspace-panel-body {
  flex: 1; overflow-y: auto; padding: 6px 10px;
}
.workspace-loading, .workspace-empty {
  font-size: 12px; color: var(--muted-foreground); padding: 16px; text-align: center;
}
.workspace-file-list { display: flex; flex-direction: column; }
.workspace-file-item {
  display: flex; align-items: center; gap: 6px;
  padding: 4px 8px; border-radius: var(--radius-sm);
  cursor: pointer; font-size: 12px; color: var(--foreground);
  transition: background var(--transition-fast);
}
.workspace-file-item:hover { background: var(--surface-hover); }
.workspace-file-item.active { background: var(--primary-light); color: var(--primary); }
.workspace-file-icon { flex-shrink: 0; font-size: 13px; }
.workspace-file-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.workspace-file-content { border-top: 1px solid var(--surface-border); flex-shrink: 0; }
.workspace-file-content-header {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 14px; font-size: 11px; color: var(--muted-foreground);
  background: var(--surface-hover);
}
.workspace-file-code {
  margin: 0; padding: 8px 14px;
  font-size: 11px; font-family: var(--font-mono);
  line-height: 1.5; max-height: 200px; overflow: auto;
  background: var(--page-canvas); color: var(--foreground);
  white-space: pre-wrap; word-break: break-all;
}

/* ── Timeline slide panel ─────────────────────────── */
.timeline-slide-panel {
  position: absolute;
  top: 0; right: 0; bottom: 0;
  width: 480px; max-width: 100%;
  background: var(--page-canvas);
  border-left: 1px solid var(--surface-border);
  box-shadow: -4px 0 24px rgba(0, 0, 0, 0.12);
  transform: translateX(100%);
  transition: transform var(--transition-base);
  display: flex; flex-direction: column;
  z-index: 10;
}
.timeline-slide-panel.open {
  transform: translateX(0);
}

.timeline-slide-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--surface-border);
  font-size: 13px;
  font-weight: 700;
  color: var(--foreground);
  flex-shrink: 0;
}
.timeline-slide-close {
  width: 28px; height: 28px;
  border-radius: var(--radius-sm);
  border: none; background: transparent;
  color: var(--muted-foreground);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all var(--transition-fast);
}
.timeline-slide-close:hover {
  background: var(--surface-hover);
  color: var(--foreground);
}

.timeline-slide-body {
  flex: 1; overflow-y: auto; padding: 0;
}

.detail-section { margin-bottom: 20px; }
.detail-label { font-size: 12px; font-weight: 700; color: var(--muted-foreground); margin: 0 0 8px; text-transform: uppercase; letter-spacing: 0.5px; }
.detail-label-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
.detail-label-row .detail-label { margin: 0; }
.review-status-badge { font-size: 12px; font-weight: 700; }

.review-actions { display: flex; gap: 6px; margin-left: auto; }

.feedback-dialog-body { display: flex; flex-direction: column; gap: 10px; }
.feedback-hint { font-size: 13px; color: var(--muted-foreground); margin: 0; line-height: 1.5; }

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
  font-size: 13.5px; line-height: 1.7;
}
.summary-box :deep(h1) { font-size: 16px; font-weight: 700; margin: 0 0 8px; border-bottom: 1px solid var(--surface-border); padding-bottom: 6px; }
.summary-box :deep(h2) { font-size: 15px; font-weight: 700; margin: 12px 0 6px; }
.summary-box :deep(h3) { font-size: 14px; font-weight: 700; margin: 10px 0 4px; }
.summary-box :deep(h4) { font-size: 13px; font-weight: 600; margin: 8px 0 4px; }
.summary-box :deep(p) { margin: 0 0 8px; }
.summary-box :deep(ul), .summary-box :deep(ol) { margin: 0 0 8px; padding-left: 20px; }
.summary-box :deep(li) { margin-bottom: 2px; }
.summary-box :deep(code) {
  background: var(--surface-hover); padding: 1px 5px; border-radius: 3px;
  font-family: var(--font-mono); font-size: 12px;
}
.summary-box :deep(pre) {
  background: var(--page-canvas); border: 1px solid var(--surface-border);
  border-radius: var(--radius-md); padding: 10px 14px; overflow-x: auto;
  margin: 8px 0; font-size: 12px; line-height: 1.5;
}
.summary-box :deep(pre code) { background: none; padding: 0; }
.summary-box :deep(blockquote) {
  border-left: 3px solid var(--primary); padding: 4px 12px;
  margin: 8px 0; color: var(--muted-foreground); background: var(--surface-hover);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}
.summary-box :deep(table) { border-collapse: collapse; width: 100%; margin: 8px 0; }
.summary-box :deep(th), .summary-box :deep(td) {
  border: 1px solid var(--surface-border); padding: 6px 10px;
  text-align: left; font-size: 12px;
}
.summary-box :deep(th) { background: var(--surface-hover); font-weight: 600; }
.summary-box :deep(hr) { border: none; border-top: 1px solid var(--surface-border); margin: 12px 0; }
.summary-box :deep(strong) { font-weight: 700; }
.summary-box :deep(a) { color: var(--primary); }
.summary-box :deep(del) { text-decoration: line-through; opacity: 0.7; }

.feedback-box {
  margin-top: 12px; background: var(--danger-light);
  border: 1px solid oklch(0.586 0.225 27 / 0.2); border-radius: var(--radius-md);
  padding: 12px 14px;
}
.feedback-box h4 { font-size: 12px; font-weight: 700; color: var(--danger); margin: 0 0 4px; }
.feedback-box p { font-size: 13px; margin: 0; white-space: pre-wrap; }

.no-review { padding: 20px 0; color: var(--muted-foreground); font-size: 14px; }
.no-review-status { display: flex; align-items: center; gap: 10px; padding: 8px 0; }

/* ── Enhanced progress log ─────────────────────────── */
.progress-log {
  background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-md); padding: 10px 14px;
  margin-bottom: 12px; max-height: 360px; overflow-y: auto;
}
.progress-entry {
  display: flex; align-items: flex-start; gap: 8px;
  padding: 3px 0; font-size: 12.5px;
  color: var(--foreground);
}
.progress-entry.step_1_codegen,
.progress-entry.step_2_review,
.progress-entry.step_3_security,
.progress-entry.step_4_summary {
  font-weight: 600; color: var(--primary);
}
.progress-entry.step_1_done,
.progress-entry.step_2_done,
.progress-entry.step_3_done,
.progress-entry.step_4_done,
.progress-entry.done {
  font-weight: 600; color: var(--success);
}
.progress-entry.error { color: var(--danger); font-weight: 600; }
.progress-time {
  font-size: 10.5px; color: var(--muted-foreground);
  font-family: var(--font-mono); flex-shrink: 0;
  min-width: 56px; text-align: right; padding-top: 1px;
}
.progress-icon {
  font-size: 13px; flex-shrink: 0; width: 20px; text-align: center;
}
.progress-msg { word-break: break-word; }

.loading-box { display: flex; align-items: center; gap: 10px; padding: 32px; color: var(--muted-foreground); font-size: 14px; }

.empty-detail { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; background: var(--page-canvas); }
.empty-detail-icon { color: var(--muted-foreground); opacity: 0.5; }
.empty-detail p { font-size: 13px; color: var(--muted-foreground); }

/* ── Create task dialog ─────────────────────────────── */
.dialog-form { display: flex; flex-direction: column; gap: 12px; }
.task-project-info { font-size: 13px; color: var(--muted-foreground); }
.field-label { font-size: 12px; font-weight: 600; color: var(--foreground); }
.field-textarea {
  width: 100%; padding: 8px 12px; border: 1px solid var(--surface-border);
  border-radius: var(--radius-md); font-size: 13px; font-family: inherit;
  background: var(--surface); color: var(--foreground);
  resize: vertical; box-sizing: border-box;
}
.field-textarea:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 2px oklch(0.55 0.2 260 / 0.12); }
</style>
