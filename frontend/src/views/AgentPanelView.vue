<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
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

// Dialogs
const showCreateAgent = ref(false)
const showCreateTask = ref(false)
const selectedAgent = ref<any>(null)
const newAgent = ref({ name: '', role: 'code_gen', model: '', system_prompt: '' })
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

let unsubAgent: (() => void) | null = null

onMounted(async () => {
  if (store.projects.length === 0) await store.fetchProjects()
  await loadAgents()
  // Real-time: refresh agent list on any agent_update
  unsubAgent = wsStore.on('agent_update', () => loadAgents())
})

// Re-fetch agents when navigating back to this page
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

async function loadModels() {
  try {
    const { data } = await api.get('/models')
    availableModels.value = data.models
    if (availableModels.value.length > 0 && !newAgent.value.model) {
      newAgent.value.model = availableModels.value[0].id
    }
  } catch { /* ignore */ }
}

async function createAgent() {
  if (!newAgent.value.name) return
  loading.value = true
  try {
    await api.post('/agents', newAgent.value)
    MessagePlugin.success('Agent 已创建')
    showCreateAgent.value = false
    newAgent.value = { name: '', role: 'code_gen', model: availableModels.value[0]?.id || '', system_prompt: '' }
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
</script>

<template>
  <div class="page-root">
    <div class="page-header">
      <div>
        <h1 class="page-title">Agent 池</h1>
        <p class="page-desc">全局 Agent 管理，可在任意项目中复用</p>
      </div>
      <t-button theme="primary" @click="showCreateAgent = true; loadModels()">
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
      <t-button theme="primary" variant="outline" @click="showCreateAgent = true; loadModels()">创建 Agent</t-button>
    </div>

    <div v-else class="agent-grid">
      <article v-for="a in agents" :key="a.id" class="agent-card">
        <div class="agent-avatar" :style="{ background: roleColors[a.role] || 'var(--muted-foreground)' }">
          {{ a.name.charAt(0) }}
        </div>
        <div class="agent-body">
          <div class="agent-name">{{ a.name }}</div>
          <div class="agent-meta">
            <span class="role-badge" :style="{ background: (roleColors[a.role] || 'var(--muted-foreground)') + '18', color: roleColors[a.role] }">
              {{ roleLabels[a.role] || a.role }}
            </span>
            <span class="model-tag">{{ a.model }}</span>
            <span class="status-dot" :class="a.status" />
            {{ statusLabels[a.status] || a.status }}
          </div>
        </div>
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
        <label class="field-label">模型</label>
        <t-select v-model="newAgent.model">
          <t-option v-if="availableModels.length === 0" value="" label="加载中..." />
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
.agent-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 10px; }
.agent-card {
  display: flex; align-items: center; gap: 14px;
  padding: 14px 16px; background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg); box-shadow: var(--shadow-surface);
  transition: border-color var(--transition-base), box-shadow var(--transition-base), transform var(--transition-base);
}
.agent-card:hover { border-color: var(--primary); box-shadow: var(--shadow-card-hover); transform: translateY(-1px); }
.agent-avatar {
  width: 40px; height: 40px; border-radius: var(--radius-md); flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 700; font-size: 16px;
}
.agent-body { flex: 1; min-width: 0; }
.agent-name { font-size: 14px; font-weight: 600; color: var(--foreground); }
.agent-meta { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted-foreground); margin-top: 3px; flex-wrap: wrap; }
.role-badge { padding: 1px 7px; border-radius: 99px; font-size: 11px; font-weight: 600; }
.model-tag { padding: 1px 6px; border-radius: 99px; font-size: 10px; color: var(--muted-foreground); background: var(--surface-hover); font-family: var(--font-mono); }
.agent-actions { display: flex; gap: 2px; flex-shrink: 0; }

.task-agent-label { font-size: 13px; color: var(--muted-foreground); margin: 0; }
.task-project-info { font-size: 13px; color: var(--muted-foreground); padding: 8px 12px; background: var(--primary-lighter); border-radius: var(--radius-md); }
.no-project-warning {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; color: var(--warning); padding: 10px 12px;
  background: var(--warning-light); border-radius: var(--radius-md);
}
</style>
