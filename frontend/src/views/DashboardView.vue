<script setup lang="ts">
import { computed, ref, onMounted, onActivated, watch } from 'vue'
import { useRouter } from 'vue-router'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import { useProjectStore } from '../stores/project'
import MemberManager from '../components/MemberManager.vue'
import MemoryExplorer from '../components/MemoryExplorer.vue'
import api from '../api'

const store = useProjectStore()
const router = useRouter()
const dialogVisible = ref(false)
const newProject = ref({ name: '', description: '', workspace_name: '' })
const creating = ref(false)

const memoryDialogVisible = ref(false)
const memoryDialogProject = ref<{ id: number; name: string } | null>(null)

const memberDialogVisible = ref(false)
const memberDialogProject = ref<{ id: number; name: string; projectCode: string | null } | null>(null)

function openMembers(p: any) {
  memberDialogProject.value = { id: p.id, name: p.name, projectCode: p.project_id }
  memberDialogVisible.value = true
}

const joinDialogVisible = ref(false)
const joinProjectId = ref('')
const joining = ref(false)
const searchKeyword = ref('')

const visibleProjects = computed(() => {
  const keyword = searchKeyword.value.trim().toLocaleLowerCase()
  if (!keyword) return store.projects
  return store.projects.filter((project: any) => [
    project.name,
    project.description,
    project.owner_name,
  ].some((value) => String(value || '').toLocaleLowerCase().includes(keyword)))
})

async function handleJoin() {
  if (!joinProjectId.value.trim()) return
  joining.value = true
  try {
    await api.post('/projects/join', { project_id: joinProjectId.value.trim() })
    MessagePlugin.success('申请已提交，请等待项目负责人审批')
    joinDialogVisible.value = false
    joinProjectId.value = ''
  } catch (e: any) {
    MessagePlugin.error(e?.response?.data?.detail || '申请失败')
  } finally {
    joining.value = false
  }
}

const activeAgentCount = ref(0)
const pendingReviewCount = ref(0)
const approvalRate = ref<string | null>(null)

function openProjectMemory(p: any) {
  memoryDialogProject.value = { id: p.id, name: p.name }
  memoryDialogVisible.value = true
}

let dashboardLoadedAt = 0
let dashboardLoad: Promise<void> | null = null

async function loadDashboard() {
  if (dashboardLoad) return dashboardLoad
  dashboardLoad = (async () => {
    await store.fetchProjects()
    await loadStats()
    dashboardLoadedAt = Date.now()
  })()
  try {
    await dashboardLoad
  } finally {
    dashboardLoad = null
  }
}

onMounted(loadDashboard)

// Returning to a cached dashboard is instant. Reconcile only when its summary
// has been inactive long enough to be meaningfully stale.
onActivated(() => {
  if (dashboardLoadedAt > 0 && Date.now() - dashboardLoadedAt > 60_000) {
    loadDashboard()
  }
})

watch(() => store.sortBy, () => { store.fetchProjects(); loadStats() })

function setFilter(key: string) {
  store.filterBy = key
  store.fetchProjects()
  loadStats()
}

const filterTabs = [
  { key: 'all', label: '全部项目' },
  { key: 'owner', label: '我主管的' },
  { key: 'admin', label: '我管理的' },
  { key: 'member', label: '我参与的' },
  { key: 'other', label: '其他项目' },
]

async function loadStats() {
  try {
    const [agentRes, reviewRes] = await Promise.all([
      api.get('/agents'),
      api.get('/reviews/pending-count'),
    ])
    const agentList = agentRes.data?.items || agentRes.data || []
    activeAgentCount.value = agentList.filter((a: any) => a.status === 'working').length
    pendingReviewCount.value = reviewRes.data?.count ?? 0
    // Approval rate: count approved vs total reviews across all projects
    let approved = 0; let total = 0
    for (const p of store.projects) {
      try {
        const { data } = await api.get(`/projects/${p.id}/reviews`)
        const reviewList = data?.items || data
        if (Array.isArray(reviewList)) {
          total += reviewList.length
          approved += reviewList.filter((r: any) => r.status === 'approved').length
        }
      } catch { /* skip projects with errors */ }
    }
    approvalRate.value = total > 0 ? `${Math.round((approved / total) * 100)}%` : null
  } catch { /* stats are non-critical */ }
}

async function handleCreate(force = false) {
  creating.value = true
  try {
    const created = await store.createProject(
      newProject.value.name, newProject.value.description,
      newProject.value.workspace_name, force,
    )
    store.setCurrentProject(created)
    dialogVisible.value = false
    newProject.value = { name: '', description: '', workspace_name: '' }
    await loadStats()
  } catch (e: any) {
    if (e?.response?.status === 409) {
      DialogPlugin.confirm({
        header: '同名项目已存在',
        body: e.response.data.detail || '已存在同名项目，确定继续创建？',
        theme: 'warning',
        confirmBtn: { content: '仍然创建' },
        cancelBtn: '取消',
        onConfirm: () => { handleCreate(true) },
      })
    } else {
      MessagePlugin.error(e?.response?.data?.detail || '创建项目失败，请稍后重试')
    }
  } finally {
    creating.value = false
  }
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function deleteProject(p: any, event: Event) {
  event.stopPropagation()
  const confirmDialog = DialogPlugin.confirm({
    header: '确认删除',
    body: `确定要删除项目「${p.name}」吗？此操作将删除项目下的所有任务、审查记录和版本历史，且不可撤销。`,
    confirmBtn: { content: '删除', theme: 'danger' },
    cancelBtn: '取消',
    onConfirm: async () => {
      try {
        const { data } = await api.delete(`/projects/${p.id}`)
        if (data.warning) MessagePlugin.warning(data.warning)
        else MessagePlugin.success(`项目「${p.name}」已删除`)
        await store.fetchProjects()
        await loadStats()
        if (store.currentProject?.id === p.id) store.setCurrentProject(null)
      } catch (e: any) {
        MessagePlugin.error(e?.response?.data?.detail || '删除失败')
      }
      confirmDialog.destroy()
    },
  })
}

function goProject(p: any) {
  if (!store.setCurrentProject(p)) {
    MessagePlugin.warning('请先加入该项目，才能切换到其工作区')
    openMembers(p)
    return
  }
  router.push('/files')
}

async function handleJoinProject(p: any, event: Event) {
  event.stopPropagation()
  if (!p.project_id) {
    MessagePlugin.error('该项目尚未生成项目 ID')
    return
  }
  joining.value = true
  try {
    await api.post('/projects/join', { project_id: p.project_id })
    MessagePlugin.success(`已申请加入「${p.name}」`)
  } catch (e: any) {
    MessagePlugin.error(e?.response?.data?.detail || '申请失败')
  } finally {
    joining.value = false
  }
}
</script>

<template>
  <div class="page-root">
    <!-- Header -->
    <div class="page-header">
      <div>
        <div class="page-eyebrow">
          <span class="eyebrow-dot"></span>
          COLLABORATION WORKSPACE
        </div>
        <h1 class="page-title">项目看板</h1>
        <p class="page-desc">集中管理项目、Agent 工作流与审查进度</p>
      </div>
      <div class="header-actions">
        <t-button theme="primary" @click="dialogVisible = true">
          <template #icon>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          </template>
          创建项目
        </t-button>
        <t-button theme="default" variant="outline" @click="joinDialogVisible = true">
          <template #icon>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>
          </template>
          加入项目
        </t-button>
      </div>
    </div>

    <!-- Stats -->
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-icon stat-icon--brand">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
        </div>
        <div class="stat-body">
          <div class="stat-value">{{ store.projects.length }}</div>
          <div class="stat-label">项目数</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon stat-icon--success">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16.01"/><line x1="16" y1="16" x2="16" y2="16.01"/></svg>
        </div>
        <div class="stat-body">
          <div class="stat-value">{{ activeAgentCount }}</div>
          <div class="stat-label">活跃 Agent</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon stat-icon--warning">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
        </div>
        <div class="stat-body">
          <div class="stat-value">{{ pendingReviewCount }}</div>
          <div class="stat-label">待审查</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon stat-icon--info">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
        </div>
        <div class="stat-body">
          <div class="stat-value">{{ approvalRate ?? '—' }}</div>
          <div class="stat-label">通过率</div>
        </div>
      </div>
    </div>

    <!-- Filter tabs -->
    <div class="project-toolbar">
      <div class="filter-tabs">
        <button
          v-for="tab in filterTabs"
          :key="tab.key"
          class="filter-tab"
          :class="{ active: store.filterBy === tab.key }"
          @click="setFilter(tab.key)"
        >{{ tab.label }}</button>
      </div>
      <div class="project-tools">
        <t-input
          v-model="searchKeyword"
          clearable
          size="medium"
          class="project-search"
          placeholder="搜索项目"
        >
          <template #prefix-icon>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          </template>
        </t-input>
        <t-select
          v-model="store.sortBy"
          size="medium"
          class="project-sort"
        >
          <t-option value="created_desc" label="最新创建" />
          <t-option value="created_asc" label="最早创建" />
          <t-option value="updated_desc" label="最近修改" />
          <t-option value="name_asc" label="名称 A-Z" />
          <t-option value="name_desc" label="名称 Z-A" />
        </t-select>
      </div>
    </div>

    <!-- Project Grid -->
    <div v-if="visibleProjects.length > 0" class="project-grid">
      <TransitionGroup name="list">
        <article
          v-for="p in visibleProjects"
        :key="p.id"
        class="project-card"
        @click="goProject(p)"
      >
        <div class="project-card-icon">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
        </div>
        <div class="project-card-body">
          <div class="project-title-row">
            <h3 class="project-card-title">{{ p.name }}</h3>
            <span class="project-access" :class="{ joined: p.is_member }">{{ p.is_member ? '已加入' : '可申请' }}</span>
          </div>
          <p class="project-card-desc">{{ p.description || '暂无描述' }}</p>
          <div class="project-card-meta">
            <span>{{ p.owner_name || '—' }}</span>
            <span>·</span>
            <span>{{ formatTime(p.created_at) }}</span>
          </div>
        </div>
        <button v-if="!p.is_member" class="btn-join" @click.stop="handleJoinProject(p, $event)" title="申请加入" :disabled="joining">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg>
        </button>
        <button class="btn-members" @click.stop="openMembers(p)" title="成员管理">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
        </button>
        <button class="btn-memory" @click.stop="openProjectMemory(p)" title="项目记忆">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
        </button>
        <button class="btn-delete" @click="deleteProject(p, $event)" title="删除项目">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
        </button>
        <svg class="project-card-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="9 18 15 12 9 6"/></svg>
      </article>
      </TransitionGroup>
    </div>

    <!-- Empty -->
    <div v-else class="empty-card">
      <div class="empty-icon">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
      </div>
      <template v-if="store.filterBy !== 'all'">
        <h3>没有匹配的项目</h3>
        <p>当前筛选条件下没有找到项目</p>
        <t-button theme="primary" variant="outline" @click="store.filterBy = 'all'">查看全部项目</t-button>
      </template>
      <template v-else>
        <h3>还没有项目</h3>
        <p>创建你的第一个项目，开始使用 Agent 协作审查</p>
        <t-button theme="primary" variant="outline" @click="dialogVisible = true">创建第一个项目</t-button>
      </template>
    </div>

    <!-- Dialog -->
    <t-dialog v-model:visible="dialogVisible" header="创建项目" width="460px">
      <div class="dialog-form">
        <label class="field-label">项目名称</label>
        <t-input v-model="newProject.name" placeholder="例如：电商后台" />
        <label class="field-label">描述（选填）</label>
        <textarea v-model="newProject.description" class="field-textarea" rows="2" placeholder="简单描述项目用途" />
        <label class="field-label">工作空间文件夹（选填）</label>
        <t-input v-model="newProject.workspace_name" placeholder="留空则使用项目名，例如：ecommerce" />
        <p class="field-hint">用于本地工作空间目录名，不可包含 \ / : * ? " &lt; &gt; | 和空格</p>
      </div>
      <template #footer>
        <t-button theme="default" variant="text" @click="dialogVisible = false">取消</t-button>
        <t-button theme="primary" :disabled="!newProject.name || creating" @click="handleCreate()">
          {{ creating ? '创建中...' : '创建' }}
        </t-button>
      </template>
    </t-dialog>

    <!-- Member management dialog -->
    <t-dialog v-model:visible="memberDialogVisible" width="560px" :footer="false" @closed="memberDialogProject = null">
      <MemberManager
        v-if="memberDialogProject"
        :key="memberDialogProject.id"
        :project-id="memberDialogProject.id"
        :project-name="memberDialogProject.name"
        :project-code="memberDialogProject.projectCode"
        @close="memberDialogVisible = false"
      />
    </t-dialog>

    <!-- Join project dialog -->
    <t-dialog v-model:visible="joinDialogVisible" header="加入项目" width="440px">
      <div class="dialog-form">
        <label class="field-label">项目 ID</label>
        <t-input v-model="joinProjectId" placeholder="例如：PROJ-20260716-abc123" />
        <p class="field-hint">请输入项目负责人提供的项目 ID，提交后将等待审批</p>
      </div>
      <template #footer>
        <t-button theme="default" variant="text" @click="joinDialogVisible = false">取消</t-button>
        <t-button theme="primary" :disabled="!joinProjectId.trim() || joining" @click="handleJoin">
          {{ joining ? '提交中...' : '申请加入' }}
        </t-button>
      </template>
    </t-dialog>

    <!-- Project memory dialog -->
    <t-dialog v-model:visible="memoryDialogVisible" :header="`项目记忆 — ${memoryDialogProject?.name || ''}`" width="680px" :footer="false">
      <MemoryExplorer
        v-if="memoryDialogProject"
        scope="project"
        :scope-id="memoryDialogProject.id"
        empty-hint="Agent 会将该项目的设计决策、审查反馈和失败教训沉淀在这里。"
      />
    </t-dialog>
  </div>
</template>

<style scoped>
.page-root { max-width: 1240px; }

.page-header {
  align-items: flex-end;
  margin-bottom: 26px;
}

.page-eyebrow {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  color: var(--primary);
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 1.25px;
}

.eyebrow-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--primary);
  box-shadow: 0 0 0 4px var(--primary-light);
}

.page-title {
  font-size: clamp(25px, 2.2vw, 32px);
  font-weight: 750;
  letter-spacing: -0.8px;
}

/* ── Stat cards ─────────────────────────────────────────────────── */
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 30px; }
.stat-card {
  display: flex;
  align-items: center;
  gap: 14px;
  background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg); padding: 19px 20px;
  box-shadow: var(--shadow-surface);
  position: relative;
  overflow: hidden;
  transition: border-color var(--transition-base), box-shadow var(--transition-base), transform var(--transition-base);
}
.stat-card::after {
  content: '';
  position: absolute;
  width: 70px;
  height: 70px;
  right: -32px;
  top: -35px;
  border-radius: 50%;
  background: var(--primary-light);
}
.stat-card:hover { border-color: color-mix(in oklch, var(--primary) 35%, var(--surface-border)); box-shadow: var(--shadow-card-hover); transform: translateY(-2px); }

.stat-icon {
  width: 42px; height: 42px; border-radius: var(--radius-md);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.stat-icon--brand { background: var(--primary-light); color: var(--primary); }
.stat-icon--success { background: var(--success-light); color: var(--success); }
.stat-icon--warning { background: var(--warning-light); color: var(--warning); }
.stat-icon--info { background: var(--info-light); color: var(--info); }

.stat-value { font-size: 26px; font-weight: 750; color: var(--foreground); letter-spacing: -0.7px; line-height: 1.2; font-variant-numeric: tabular-nums; }
.stat-label { font-size: 12.5px; color: var(--muted-foreground); margin-top: 2px; }

/* ── Filter tabs ────────────────────────────────────────────────── */
.project-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.filter-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  background: var(--surface);
  box-shadow: var(--shadow-surface);
}

.filter-tab {
  padding: 6px 13px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--muted-foreground);
  font-size: 13px;
  font-weight: 500;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.filter-tab:hover {
  background: var(--surface-hover);
  color: var(--foreground);
}

.filter-tab.active {
  background: var(--primary-light);
  color: var(--primary);
  box-shadow: inset 0 0 0 1px color-mix(in oklch, var(--primary) 14%, transparent);
}

.project-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}

.project-search { width: 200px; }
.project-sort { width: 132px; }

.project-search :deep(.t-input),
.project-sort :deep(.t-input) {
  background: var(--surface);
}

/* ── Project grid ───────────────────────────────────────────────── */
.project-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(390px, 1fr)); gap: 14px; }
.project-card {
  display: flex; align-items: center; gap: 14px;
  background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg); padding: 17px 18px;
  box-shadow: var(--shadow-surface); cursor: pointer;
  transition: all var(--transition-base);
}
.project-card:hover {
  border-color: color-mix(in oklch, var(--primary) 40%, var(--surface-border));
  box-shadow: var(--shadow-card-hover);
  transform: translateY(-1px);
}
.project-card-icon {
  width: 42px; height: 42px; border-radius: 11px;
  background: linear-gradient(145deg, var(--primary-light), var(--primary-lighter)); color: var(--primary);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.project-card-body { flex: 1; min-width: 0; }
.project-title-row { display: flex; align-items: center; gap: 8px; min-width: 0; }
.project-card-title { font-size: 14px; font-weight: 600; margin: 0; color: var(--foreground); }
.project-access {
  flex-shrink: 0;
  padding: 2px 6px;
  border-radius: 999px;
  background: var(--warning-light);
  color: var(--warning);
  font-size: 9px;
  font-weight: 700;
}
.project-access.joined { background: var(--success-light); color: var(--success); }
.project-card-desc { font-size: 12px; color: var(--muted-foreground); margin: 2px 0 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.project-card-meta { display: flex; align-items: center; gap: 6px; margin-top: 6px; font-size: 11px; color: var(--muted-foreground); }
.project-card-arrow { color: var(--muted-foreground); flex-shrink: 0; }
.project-card:hover .project-card-arrow { color: var(--primary); }

.btn-delete {
  width: 28px; height: 28px; border-radius: var(--radius-sm);
  border: none; background: transparent; color: var(--muted-foreground);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.btn-delete:hover { background: var(--danger-light); color: var(--danger); }

.btn-members {
  width: 28px; height: 28px; border-radius: var(--radius-sm);
  border: none; background: transparent; color: var(--muted-foreground);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.btn-members:hover { background: var(--primary-light); color: var(--primary); }

.btn-memory {
  width: 28px; height: 28px; border-radius: var(--radius-sm);
  border: none; background: transparent; color: var(--muted-foreground);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.btn-memory:hover { background: var(--info-light); color: var(--info); }

.btn-join {
  width: 28px; height: 28px; border-radius: var(--radius-sm);
  border: none; background: transparent; color: var(--muted-foreground);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.btn-join:hover { background: var(--success-light); color: var(--success); }
.btn-join:disabled { opacity: 0.4; cursor: not-allowed; }

.field-hint {
  font-size: 11px; color: var(--muted-foreground);
  margin: 2px 0 0; line-height: 1.4;
}

@media (max-width: 980px) {
  .project-toolbar {
    align-items: stretch;
    flex-direction: column;
  }
  .filter-tabs {
    overflow-x: auto;
  }
  .filter-tab {
    flex: 0 0 auto;
  }
  .project-tools {
    width: 100%;
  }
  .project-search {
    flex: 1;
    width: auto;
  }
}

@media (max-width: 640px) {
  .page-header {
    align-items: flex-start;
  }
  .header-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
  .header-actions :deep(.t-button) {
    width: 100%;
  }
  .stat-grid {
    gap: 10px;
  }
  .stat-card {
    align-items: flex-start;
    flex-direction: column;
    gap: 10px;
    padding: 15px;
  }
  .stat-icon {
    width: 36px;
    height: 36px;
  }
  .stat-value {
    font-size: 22px;
  }
  .project-tools {
    align-items: stretch;
    flex-direction: column;
  }
  .project-search,
  .project-sort {
    width: 100%;
  }
  .project-grid {
    grid-template-columns: 1fr;
  }
  .project-card {
    align-items: flex-start;
  }
  .project-card-arrow {
    display: none;
  }
  .btn-members,
  .btn-memory,
  .btn-delete {
    opacity: 1;
  }
}
</style>
