<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { useRoute } from 'vue-router'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import { useProjectStore } from '../stores/project'
import { useWebSocketStore } from '../stores/websocket'
import api, { getErrorMessage } from '../api'

const store = useProjectStore()
const wsStore = useWebSocketStore()
const route = useRoute()

const agents = ref<any[]>([])
const availableModels = ref<{ id: string; name: string }[]>([])
const runnerCheckResult = ref<{ available: boolean; checked: boolean; hint: string } | null>(null)
const modelsLoading = ref(false)

// Dialogs
const showCreateAgent = ref(false)
const showCreateTask = ref(false)
const selectedAgent = ref<any>(null)
const newAgent = ref({ name: '', role: 'code_gen', model: '', system_prompt: '', runner_type: 'crewai' })
const newTask = ref({ title: '', description: '', project_id: null as number | null })
const loading = ref(false)

const roleLabels: Record<string, string> = {
  code_gen: '代码工程师',
  reviewer: '代码审查员',
  security: '安全审查员',
}

const roleColors: Record<string, string> = {
  code_gen: 'var(--primary)',
  reviewer: 'var(--success)',
  security: 'var(--danger)',
}

const statusLabels: Record<string, string> = {
  idle: '空闲', working: '工作中', done: '完成', error: '错误',
}

const statusDisplay: Record<string, { icon: string; cls: string }> = {
  idle: { icon: '', cls: 'dot-idle' },
  working: { icon: '', cls: 'dot-working' },
  done: { icon: '✓', cls: 'dot-done' },
  error: { icon: '✕', cls: 'dot-error' },
}

const runnerLabels: Record<string, string> = {
  crewai: 'CrewAI', claude_code: 'Claude Code', opencode: 'OpenCode',
}
const runnerColors: Record<string, string> = {
  crewai: 'var(--primary)', claude_code: '#d97706', opencode: 'var(--success)',
}

let unsubAgent: (() => void) | null = null

onMounted(async () => {
  if (store.projects.length === 0) await store.fetchProjects()
  await loadAgents()
  unsubAgent = wsStore.on('agent_update', () => loadAgents())
})

watch(() => route.path, (path) => {
  if (path === '/agents') loadAgents()
})

onUnmounted(() => {
  if (unsubAgent) unsubAgent()
})

async function loadAgents() {
  try {
    const { data } = await api.get('/agents')
    agents.value = data
  } catch (e: any) {
    MessagePlugin.error(e?.response?.data?.detail || '加载 Agent 列表失败')
  }
}

async function loadModels(runnerType?: string) {
  modelsLoading.value = true
  try {
    const params = runnerType ? { runner_type: runnerType } : {}
    const { data } = await api.get('/models', { params })
    availableModels.value = data.models
    if (availableModels.value.length > 0 && !newAgent.value.model) {
      newAgent.value.model = availableModels.value[0].id
    }
    // Show detection result feedback
    const sourceLabel: Record<string, string> = { api: '实时检测', static: '内置列表', fallback: '默认列表' }
    const source = sourceLabel[data.source] || data.source || '未知'
    if (data.source === 'api') {
      MessagePlugin.success(`模型检测完成：${source} → ${data.count} 个可用模型`)
    } else if (data.hint) {
      MessagePlugin.warning(`模型检测：${source} → ${data.count} 个模型（${data.hint}）`)
    } else {
      MessagePlugin.info(`模型检测：${source} → ${data.count} 个模型`)
    }
  } catch {
    MessagePlugin.error('模型检测失败，请检查后端服务是否运行')
  }
  finally { modelsLoading.value = false }
}

async function createAgent() {
  if (!newAgent.value.name) return
  loading.value = true
  try {
    await api.post('/agents', newAgent.value)
    MessagePlugin.success('Agent 已创建')
    showCreateAgent.value = false
    newAgent.value = { name: '', role: 'code_gen', model: availableModels.value[0]?.id || '', system_prompt: '', runner_type: 'crewai' }
    await loadAgents()
  } finally { loading.value = false }
}

async function deleteAgent(id: number, name: string) {
  const confirmDialog = DialogPlugin.confirm({
    header: '确认删除',
    body: `确定要删除 Agent「${name}」吗？此操作不可撤销。`,
    confirmBtn: { content: '删除', theme: 'danger' },
    cancelBtn: '取消',
    onConfirm: async () => {
      try {
        await api.delete(`/agents/${id}`)
        MessagePlugin.success('Agent 已删除')
        await loadAgents()
      } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '删除失败')) }
      confirmDialog.destroy()
    },
  })
}

async function createTask() {
  if (!newTask.value.title || !newTask.value.project_id || !selectedAgent.value) return
  loading.value = true
  try {
    await api.post(`/projects/${newTask.value.project_id}/tasks`, {
      title: newTask.value.title,
      description: newTask.value.description,
      agent_id: selectedAgent.value.id,
    })
    MessagePlugin.success('任务已创建，Agent 开始执行...')
    showCreateTask.value = false
    newTask.value = { title: '', description: '', project_id: null }
  } finally { loading.value = false }
}

function openTaskDialog(agent: any) {
  if (!store.currentProject?.id) {
    MessagePlugin.warning('请先在侧边栏选择一个项目')
    return
  }
  selectedAgent.value = agent
  newTask.value = { title: '', description: '', project_id: store.currentProject.id }
  showCreateTask.value = true
}

async function checkRunnerAvailability(runnerType: string) {
  if (!['claude_code', 'opencode'].includes(runnerType)) {
    runnerCheckResult.value = null
    return
  }
  try {
    const { data } = await api.get('/agents/check-runner', { params: { runner_type: runnerType } })
    runnerCheckResult.value = data
  } catch {
    runnerCheckResult.value = null
  }
}

function lastResultLabel(status: string | null): string {
  if (!status) return ''
  const map: Record<string, string> = {
    approved: '最近通过', rejected: '最近驳回', reviewing: '最近完成',
    failed: '最近失败', completed: '最近完成',
  }
  return map[status] || status
}
</script>

<template>
  <div class="page-root">
    <div class="page-header">
      <div>
        <h1 class="page-title">Agent 池</h1>
        <p class="page-desc">全局 Agent 管理，可在任意项目中复用</p>
      </div>
      <t-button theme="primary" @click="showCreateAgent = true; loadModels(newAgent.runner_type); checkRunnerAvailability(newAgent.runner_type)">
        <template #icon>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        </template>
        创建 Agent
      </t-button>
    </div>

    <!-- Agents -->
    <div v-if="agents.length === 0" class="empty-card">
      <div class="empty-icon">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16.01"/><line x1="16" y1="16" x2="16" y2="16.01"/></svg>
      </div>
      <h3>暂无 Agent</h3>
      <p>创建你的第一个 AI Agent，可在任意项目中指派任务</p>
      <t-button theme="primary" variant="outline" @click="showCreateAgent = true; loadModels(newAgent.runner_type)">创建 Agent</t-button>
    </div>

    <div v-else class="agent-grid">
      <article v-for="a in agents" :key="a.id" class="agent-card" :class="{ 'agent-working': a.status === 'working' }">
        <!-- Avatar -->
        <div class="agent-avatar" :style="{ background: roleColors[a.role] || 'var(--muted-foreground)' }">
          {{ a.name.charAt(0) }}
        </div>

        <!-- Body -->
        <div class="agent-body">
          <div class="agent-name-row">
            <span class="agent-name">{{ a.name }}</span>
            <span class="status-dot" :class="statusDisplay[a.status]?.cls || 'dot-idle'" />
          </div>
          <div class="agent-meta">
            <span class="role-badge" :style="{ background: (roleColors[a.role] || 'var(--muted-foreground)') + '18', color: roleColors[a.role] }">
              {{ roleLabels[a.role] || a.role }}
            </span>
            <span class="model-tag">{{ a.model }}</span>
            <span class="runner-badge" :style="{ background: (runnerColors[a.runner_type] || 'var(--muted-foreground)') + '14', color: runnerColors[a.runner_type] || 'var(--muted-foreground)' }">
              {{ runnerLabels[a.runner_type] || a.runner_type || 'CrewAI' }}
            </span>
          </div>

          <!-- Working state: show current task -->
          <div v-if="a.status === 'working' && a.current_task_title" class="agent-current-task">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            <span class="current-task-title">{{ a.current_task_title }}</span>
          </div>

          <!-- Idle/done state: show stats -->
          <div v-else class="agent-stats">
            <span v-if="a.total_tasks > 0" class="stat-item">
              执行 <strong>{{ a.total_tasks }}</strong> 次
            </span>
            <span v-if="a.approval_rate" class="stat-item stat-approval" :class="{ 'rate-high': (a.approved_tasks / a.total_tasks) >= 0.5 }">
              通过率 <strong>{{ a.approval_rate }}</strong>
            </span>
            <span v-if="a.last_task_status" class="stat-item stat-last">
              {{ lastResultLabel(a.last_task_status) }}
            </span>
          </div>
        </div>

        <!-- Actions -->
        <div class="agent-actions">
          <t-button size="small" variant="text" @click="openTaskDialog(a)">指派任务</t-button>
          <t-button size="small" variant="text" theme="danger" @click="deleteAgent(a.id, a.name)" title="删除">
            <template #icon>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
            </template>
          </t-button>
        </div>
      </article>
    </div>

    <!-- Create Agent Dialog -->
    <t-dialog v-model:visible="showCreateAgent" header="创建 Agent" width="480px">
      <div class="dialog-form">
        <label class="field-label">名称</label>
        <t-input v-model="newAgent.name" placeholder="例如：小码" />
        <label class="field-label">角色</label>
        <t-select v-model="newAgent.role">
          <t-option value="code_gen" label="代码工程师" />
          <t-option value="reviewer" label="代码审查员" />
          <t-option value="security" label="安全审查员" />
        </t-select>
        <label class="field-label">执行框架</label>
        <t-select v-model="newAgent.runner_type" @change="(v: string) => { loadModels(v); checkRunnerAvailability(v) }">
          <t-option value="crewai" label="CrewAI — 多 Agent 流水线" />
          <t-option value="claude_code" label="Claude Code — Anthropic 官方 SDK" />
          <t-option value="opencode" label="OpenCode — 开源通用框架" />
        </t-select>
        <!-- Runner CLI not found warning -->
        <div v-if="runnerCheckResult && runnerCheckResult.checked && !runnerCheckResult.available" class="runner-warning">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          <div class="runner-warning-body">
            <strong>未检测到 {{ runnerCheckResult.cli_name }} CLI</strong>
            <p>{{ runnerCheckResult.hint }}</p>
          </div>
        </div>
        <div class="model-label-row">
          <label class="field-label">模型</label>
          <t-button
            size="small"
            variant="text"
            :loading="modelsLoading"
            @click="loadModels(newAgent.runner_type)"
          >
            <template #icon>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
            </template>
            检测模型
          </t-button>
        </div>
        <t-select v-model="newAgent.model">
          <t-option v-if="modelsLoading" value="" label="检测中..." />
          <t-option v-else-if="availableModels.length === 0" value="" label="暂无可用模型，点击上方按钮检测" />
          <t-option v-for="m in availableModels" :key="m.id" :value="m.id" :label="m.name || m.id" />
        </t-select>
        <label class="field-label">系统提示词（选填）</label>
        <textarea v-model="newAgent.system_prompt" class="field-textarea" rows="3" placeholder="自定义 Agent 行为..." />
      </div>
      <template #footer>
        <t-button theme="default" variant="text" @click="showCreateAgent = false">取消</t-button>
        <t-button theme="primary" :disabled="!newAgent.name" @click="createAgent">创建</t-button>
      </template>
    </t-dialog>

    <!-- Create Task Dialog -->
    <t-dialog v-model:visible="showCreateTask" header="指派任务" width="500px">
      <div class="dialog-form">
        <p class="task-agent-label">Agent：<strong>{{ selectedAgent?.name }}</strong></p>
        <div v-if="!newTask.project_id" class="no-project-warning">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          请先在侧边栏选择一个项目
        </div>
        <div v-else class="task-project-info">
          目标项目：<strong>{{ store.currentProject?.name }}</strong>
        </div>
        <label class="field-label">任务标题</label>
        <t-input v-model="newTask.title" placeholder="例如：写一个用户登录接口" />
        <label class="field-label">详细描述</label>
        <textarea v-model="newTask.description" class="field-textarea" rows="4" placeholder="描述清楚你要 Agent 做什么..." />
      </div>
      <template #footer>
        <t-button theme="default" variant="text" @click="showCreateTask = false">取消</t-button>
        <t-button theme="primary" :disabled="!newTask.title || !newTask.project_id" @click="createTask">开始执行</t-button>
      </template>
    </t-dialog>
  </div>
</template>

<style scoped>
.page-root { max-width: 1000px; }

/* ── Agent cards ─────────────────────────────────────────────────── */
.agent-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 10px; }
.agent-card {
  display: flex; align-items: flex-start; gap: 14px;
  padding: 16px 18px; background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg); box-shadow: var(--shadow-surface);
  transition: border-color var(--transition-base), box-shadow var(--transition-base), transform var(--transition-base);
}
.agent-card:hover { border-color: var(--primary); box-shadow: var(--shadow-card-hover); transform: translateY(-1px); }
.agent-card.agent-working {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px oklch(0.55 0.2 260 / 0.1);
}
.agent-avatar {
  width: 42px; height: 42px; border-radius: var(--radius-md); flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 700; font-size: 17px;
}
.agent-body { flex: 1; min-width: 0; }
.agent-name-row { display: flex; align-items: center; gap: 6px; }
.agent-name { font-size: 14px; font-weight: 600; color: var(--foreground); }
.agent-meta { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted-foreground); margin-top: 3px; flex-wrap: wrap; }
.role-badge { padding: 1px 7px; border-radius: 99px; font-size: 11px; font-weight: 600; }
.model-tag { padding: 1px 6px; border-radius: 99px; font-size: 10px; color: var(--muted-foreground); background: var(--surface-hover); font-family: var(--font-mono); }
.agent-actions { display: flex; gap: 2px; flex-shrink: 0; margin-top: 2px; }

/* Current task indicator */
.agent-current-task {
  display: flex; align-items: center; gap: 6px;
  margin-top: 8px; padding: 6px 10px;
  background: var(--primary-light); border-radius: var(--radius-sm);
  font-size: 12px; color: var(--primary);
  overflow: hidden;
}
.current-task-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
.current-task-elapsed { font-family: var(--font-mono); font-size: 11px; opacity: 0.8; flex-shrink: 0; }

/* Stats */
.agent-stats {
  display: flex; align-items: center; gap: 8px;
  margin-top: 8px; font-size: 11.5px; color: var(--muted-foreground);
  flex-wrap: wrap;
}
.stat-item strong { color: var(--foreground); font-weight: 700; }
.stat-approval.rate-high { color: var(--success); }
.stat-last {
  padding: 1px 6px; border-radius: 99px;
  font-size: 10px; font-weight: 600;
  background: var(--surface-hover);
}

.task-agent-label { font-size: 13px; color: var(--muted-foreground); margin: 0; }
.task-project-info { font-size: 13px; color: var(--muted-foreground); padding: 8px 12px; background: var(--primary-lighter); border-radius: var(--radius-md); }
.no-project-warning {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; color: var(--warning); padding: 10px 12px;
  background: var(--warning-light); border-radius: var(--radius-md);
}

/* Model label row */
.model-label-row {
  display: flex; align-items: center; justify-content: space-between;
}

/* Runner CLI detection warning */
.runner-warning {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 10px 12px;
  background: #fff3cd; border: 1px solid #ffc107;
  border-radius: var(--radius-md);
  color: #856404; font-size: 13px;
}
.runner-warning svg { flex-shrink: 0; margin-top: 1px; color: #e6a100; }
.runner-warning-body strong { font-weight: 600; }
.runner-warning-body p { margin: 3px 0 0; font-size: 12px; opacity: 0.85; }

</style>
