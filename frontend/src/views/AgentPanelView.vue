<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useProjectStore } from '../stores/project'
import api from '../api'

const store = useProjectStore()

const agents = ref<any[]>([])
const tasks = ref<any[]>([])
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
  code_gen: 'var(--brand)',
  reviewer: 'var(--success)',
  security: 'var(--danger)',
}

const statusLabels: Record<string, string> = {
  idle: '空闲', working: '工作中', done: '完成', error: '错误',
}

onMounted(async () => {
  if (store.projects.length === 0) await store.fetchProjects()
  await loadAgents()
})

async function loadAgents() {
  const { data } = await api.get('/agents')
  agents.value = data
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
    ElMessage.success('Agent 已创建')
    showCreateAgent.value = false
    newAgent.value = { name: '', role: 'code_gen', model: availableModels.value[0]?.id || '', system_prompt: '' }
    await loadAgents()
  } finally { loading.value = false }
}

async function deleteAgent(id: number) {
  try {
    await api.delete(`/agents/${id}`)
    ElMessage.success('Agent 已删除')
    await loadAgents()
  } catch { ElMessage.error('删除失败') }
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
    ElMessage.success('任务已创建，Agent 开始执行...')
    showCreateTask.value = false
    newTask.value = { title: '', description: '', project_id: null }
  } finally { loading.value = false }
}

function openTaskDialog(agent: any) {
  selectedAgent.value = agent
  newTask.value = { title: '', description: '', project_id: store.currentProject?.id || store.projects[0]?.id || null }
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
      <button class="btn-primary" @click="showCreateAgent = true; loadModels()">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        创建 Agent
      </button>
    </div>

    <!-- Agents -->
    <div v-if="agents.length === 0" class="empty-card">
      <div class="empty-icon">🤖</div>
      <h3>暂无 Agent</h3>
      <p>创建你的第一个 AI Agent，可在任意项目中指派任务</p>
      <button class="btn-secondary" @click="showCreateAgent = true; loadModels()">创建 Agent</button>
    </div>

    <div v-else class="agent-grid">
      <article v-for="a in agents" :key="a.id" class="agent-card">
        <div class="agent-avatar" :style="{ background: roleColors[a.role] || 'var(--muted)' }">
          {{ a.name.charAt(0) }}
        </div>
        <div class="agent-body">
          <div class="agent-name">{{ a.name }}</div>
          <div class="agent-meta">
            <span class="role-badge" :style="{ background: (roleColors[a.role] || 'var(--muted)') + '22', color: roleColors[a.role] }">
              {{ roleLabels[a.role] || a.role }}
            </span>
            <span class="model-tag">{{ a.model }}</span>
            <span class="status-dot" :class="a.status" />
            {{ statusLabels[a.status] || a.status }}
          </div>
        </div>
        <div class="agent-actions">
          <button class="btn-ghost-sm" @click="openTaskDialog(a)">指派任务</button>
          <button class="btn-icon-sm" @click="deleteAgent(a.id)" title="删除">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
          </button>
        </div>
      </article>
    </div>

    <!-- Create Agent Dialog -->
    <el-dialog v-model="showCreateAgent" title="创建 Agent" width="480px">
      <div class="dialog-form">
        <label class="field-label">名称</label>
        <input v-model="newAgent.name" class="field-input" placeholder="例如：小码" />
        <label class="field-label">角色</label>
        <select v-model="newAgent.role" class="field-input">
          <option value="code_gen">代码工程师</option>
          <option value="reviewer">代码审查员</option>
          <option value="security">安全审查员</option>
        </select>
        <label class="field-label">模型</label>
        <select v-model="newAgent.model" class="field-input">
          <option v-if="availableModels.length === 0" value="">加载中...</option>
          <option v-for="m in availableModels" :key="m.id" :value="m.id">{{ m.name || m.id }}</option>
        </select>
        <label class="field-label">系统提示词（选填）</label>
        <textarea v-model="newAgent.system_prompt" class="field-textarea" rows="3" placeholder="自定义 Agent 行为..." />
      </div>
      <template #footer>
        <button class="btn-ghost" @click="showCreateAgent = false">取消</button>
        <button class="btn-primary" :disabled="!newAgent.name" @click="createAgent">创建</button>
      </template>
    </el-dialog>

    <!-- Create Task Dialog -->
    <el-dialog v-model="showCreateTask" title="指派任务" width="500px">
      <div class="dialog-form">
        <p class="task-agent-label">Agent：<strong>{{ selectedAgent?.name }}</strong></p>
        <label class="field-label">目标项目</label>
        <select v-model="newTask.project_id" class="field-input">
          <option :value="null" disabled>选择项目</option>
          <option v-for="p in store.projects" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
        <label class="field-label">任务标题</label>
        <input v-model="newTask.title" class="field-input" placeholder="例如：写一个用户登录接口" />
        <label class="field-label">详细描述</label>
        <textarea v-model="newTask.description" class="field-textarea" rows="4" placeholder="描述清楚你要 Agent 做什么..." />
      </div>
      <template #footer>
        <button class="btn-ghost" @click="showCreateTask = false">取消</button>
        <button class="btn-primary" :disabled="!newTask.title || !newTask.project_id" @click="createTask">开始执行</button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-root { max-width: 1000px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-title { font-size: 22px; font-weight: 700; margin: 0; }
.page-desc { font-size: 13.5px; color: var(--muted-foreground); margin: 4px 0 0; }

/* ── Agent cards ─────────────────────────────────── */
.agent-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; }
.agent-card {
  display: flex; align-items: center; gap: 14px;
  padding: 14px 16px; background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg); box-shadow: var(--shadow-surface); transition: border-color 0.15s;
}
.agent-card:hover { border-color: var(--ring); }
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
.status-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--muted-foreground); }
.status-dot.working { background: var(--brand); animation: pulse 1.5s infinite; }
.status-dot.done { background: var(--success); }
.status-dot.error { background: var(--danger); }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
.agent-actions { display: flex; gap: 4px; flex-shrink: 0; }

/* ── Shared ─────────────────────────────────────── */
.empty-card { text-align: center; padding: 64px 32px; background: var(--surface); border: 1px solid var(--surface-border); border-radius: var(--radius-lg); }
.empty-icon { font-size: 40px; margin-bottom: 12px; }
.empty-card h3 { font-size: 16px; font-weight: 600; margin: 0 0 6px; }
.empty-card p { font-size: 13px; color: var(--muted-foreground); margin: 0 0 20px; }

.btn-primary { display: inline-flex; align-items: center; gap: 6px; padding: 7px 14px; border-radius: var(--radius-md); background: var(--primary); color: var(--primary-foreground); border: none; font-size: 13px; font-weight: 600; cursor: pointer; }
.btn-primary:disabled { opacity: 0.5; cursor: default; }
.btn-secondary { padding: 8px 16px; border-radius: var(--radius-md); background: var(--surface); color: var(--foreground); border: 1px solid var(--surface-border); font-size: 13.5px; font-weight: 600; cursor: pointer; }
.btn-secondary:hover { background: var(--surface-hover); }
.btn-ghost { padding: 7px 14px; border-radius: var(--radius-md); background: transparent; color: var(--muted-foreground); border: none; font-size: 13px; cursor: pointer; }
.btn-ghost:hover { background: var(--surface-hover); color: var(--foreground); }
.btn-ghost-sm { padding: 5px 10px; border-radius: var(--radius-sm); background: transparent; color: var(--muted-foreground); border: none; font-size: 12px; cursor: pointer; }
.btn-ghost-sm:hover { background: var(--surface-hover); color: var(--foreground); }
.btn-icon-sm { width: 28px; height: 28px; border-radius: var(--radius-sm); border: none; background: transparent; color: var(--muted-foreground); cursor: pointer; display: flex; align-items: center; justify-content: center; }
.btn-icon-sm:hover { background: var(--surface-hover); color: var(--danger); }

.dialog-form { display: flex; flex-direction: column; gap: 8px; }
.field-label { font-size: 13px; font-weight: 600; }
.field-input, .field-textarea { width: 100%; padding: 8px 12px; border: 1px solid var(--input); border-radius: var(--radius-md); font-size: 14px; color: var(--foreground); background: var(--surface); outline: none; box-sizing: border-box; }
.field-input:focus, .field-textarea:focus { border-color: var(--ring); }
.field-textarea { resize: vertical; min-height: 60px; }
.task-agent-label { font-size: 13px; color: var(--muted-foreground); margin: 0; }
</style>
