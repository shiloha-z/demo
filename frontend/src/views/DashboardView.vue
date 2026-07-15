<script setup lang="ts">
import { ref, onMounted, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import { useProjectStore } from '../stores/project'
import api from '../api'

const store = useProjectStore()
const router = useRouter()
const dialogVisible = ref(false)
const newProject = ref({ name: '', description: '' })
const creating = ref(false)

const activeAgentCount = ref(0)
const pendingReviewCount = ref(0)
const approvalRate = ref<string | null>(null)

onMounted(async () => {
  await store.fetchProjects()
  await loadStats()
})

watch(() => store.sortBy, () => { store.fetchProjects(); loadStats() })

async function loadStats() {
  try {
    const [agentRes, reviewRes] = await Promise.all([
      api.get('/agents'),
      api.get('/reviews/pending-count'),
    ])
    activeAgentCount.value = (agentRes.data || []).filter((a: any) => a.status === 'working').length
    pendingReviewCount.value = reviewRes.data?.count ?? 0
    // Approval rate: count approved vs total reviews across all projects
    let approved = 0; let total = 0
    for (const p of store.projects) {
      try {
        const { data } = await api.get(`/projects/${p.id}/reviews`)
        if (Array.isArray(data)) {
          total += data.length
          approved += data.filter((r: any) => r.status === 'approved').length
        }
      } catch { /* skip projects with errors */ }
    }
    approvalRate.value = total > 0 ? `${Math.round((approved / total) * 100)}%` : null
  } catch { /* stats are non-critical */ }
}

async function handleCreate() {
  creating.value = true
  try {
    await store.createProject(newProject.value.name, newProject.value.description)
    dialogVisible.value = false
    newProject.value = { name: '', description: '' }
    await loadStats()
  } catch (e: any) {
    MessagePlugin.error(e?.response?.data?.detail || '创建项目失败，请稍后重试')
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
        await api.delete(`/projects/${p.id}`)
        MessagePlugin.success(`项目「${p.name}」已删除`)
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
  store.setCurrentProject(p)
  router.push('/files')
}
</script>

<template>
  <div class="page-root">
    <!-- Header -->
    <div class="page-header">
      <div>
        <h1 class="page-title">项目看板</h1>
        <p class="page-desc">管理你的项目和 Agent 工作区</p>
      </div>
      <div class="header-actions">
        <t-select
          v-model="store.sortBy"
          size="medium"
          style="width: 140px"
          @change="store.fetchProjects()"
        >
          <t-option value="created_desc" label="最新创建" />
          <t-option value="created_asc" label="最早创建" />
          <t-option value="updated_desc" label="最近修改" />
          <t-option value="name_asc" label="名称 A-Z" />
          <t-option value="name_desc" label="名称 Z-A" />
        </t-select>
        <t-button theme="primary" @click="dialogVisible = true">
          <template #icon>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          </template>
          创建项目
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

    <!-- Project Grid -->
    <div v-if="store.projects.length > 0" class="project-grid">
      <article
        v-for="p in store.projects"
        :key="p.id"
        class="project-card"
        @click="goProject(p)"
      >
        <div class="project-card-icon">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
        </div>
        <div class="project-card-body">
          <h3 class="project-card-title">{{ p.name }}</h3>
          <p class="project-card-desc">{{ p.description || '暂无描述' }}</p>
          <div class="project-card-meta">
            <span>{{ p.owner_name || '—' }}</span>
            <span>·</span>
            <span>{{ formatTime(p.created_at) }}</span>
          </div>
        </div>
        <button class="btn-delete" @click="deleteProject(p, $event)" title="删除项目">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
        </button>
        <svg class="project-card-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="9 18 15 12 9 6"/></svg>
      </article>
    </div>

    <!-- Empty -->
    <div v-else class="empty-card">
      <div class="empty-icon">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
      </div>
      <h3>还没有项目</h3>
      <p>创建你的第一个项目，开始使用 Agent 协作审查</p>
      <t-button theme="primary" variant="outline" @click="dialogVisible = true">创建第一个项目</t-button>
    </div>

    <!-- Dialog -->
    <t-dialog v-model:visible="dialogVisible" header="创建项目" width="460px">
      <div class="dialog-form">
        <label class="field-label">项目名称</label>
        <t-input v-model="newProject.name" placeholder="例如：电商后台" />
        <label class="field-label">描述（选填）</label>
        <textarea v-model="newProject.description" class="field-textarea" rows="3" placeholder="简单描述项目用途" />
      </div>
      <template #footer>
        <t-button theme="default" variant="text" @click="dialogVisible = false">取消</t-button>
        <t-button theme="primary" :disabled="!newProject.name || creating" @click="handleCreate">
          {{ creating ? '创建中...' : '创建' }}
        </t-button>
      </template>
    </t-dialog>
  </div>
</template>

<style scoped>
.page-root { max-width: 1000px; }

/* ── Stat cards ─────────────────────────────────────────────────── */
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 28px; }
.stat-card {
  display: flex;
  align-items: center;
  gap: 14px;
  background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg); padding: 18px 20px;
  box-shadow: var(--shadow-surface);
  transition: border-color var(--transition-base), box-shadow var(--transition-base);
}
.stat-card:hover { border-color: var(--primary); box-shadow: var(--shadow-card-hover); }

.stat-icon {
  width: 42px; height: 42px; border-radius: var(--radius-md);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.stat-icon--brand { background: var(--primary-light); color: var(--primary); }
.stat-icon--success { background: var(--success-light); color: var(--success); }
.stat-icon--warning { background: var(--warning-light); color: var(--warning); }
.stat-icon--info { background: var(--info-light); color: var(--info); }

.stat-value { font-size: 24px; font-weight: 700; color: var(--foreground); letter-spacing: -0.5px; line-height: 1.2; }
.stat-label { font-size: 12.5px; color: var(--muted-foreground); margin-top: 2px; }

/* ── Project grid ───────────────────────────────────────────────── */
.project-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.project-card {
  display: flex; align-items: center; gap: 14px;
  background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg); padding: 16px 18px;
  box-shadow: var(--shadow-surface); cursor: pointer;
  transition: all var(--transition-base);
}
.project-card:hover {
  border-color: var(--primary);
  box-shadow: var(--shadow-card-hover);
  transform: translateY(-1px);
}
.project-card-icon {
  width: 40px; height: 40px; border-radius: var(--radius-md);
  background: var(--primary-light); color: var(--primary);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.project-card-body { flex: 1; min-width: 0; }
.project-card-title { font-size: 14px; font-weight: 600; margin: 0; color: var(--foreground); }
.project-card-desc { font-size: 12px; color: var(--muted-foreground); margin: 2px 0 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.project-card-meta { display: flex; align-items: center; gap: 6px; margin-top: 6px; font-size: 11px; color: var(--muted-foreground); }
.project-card-arrow { color: var(--muted-foreground); opacity: 0; transition: all var(--transition-base); flex-shrink: 0; }
.project-card:hover .project-card-arrow { opacity: 1; color: var(--primary); }

.btn-delete {
  width: 28px; height: 28px; border-radius: var(--radius-sm);
  border: none; background: transparent; color: var(--muted-foreground);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; opacity: 0; transition: all var(--transition-fast);
}
.project-card:hover .btn-delete { opacity: 1; }
.btn-delete:hover { background: var(--danger-light); color: var(--danger); }
</style>
