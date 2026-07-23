<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { useAuditStore, type AuditEntry } from '../stores/audit'
import { useProjectStore } from '../stores/project'

const audit = useAuditStore()
const projectStore = useProjectStore()

const filters = ref({
  project_id: null as number | null,
  actor_type: '' as string,
  action: '' as string,
  task_id: null as number | null,
})
// `actions` now carries registry metadata (value/label/token) from the backend
// — new audit actions appear automatically, no hard-coded map here.
const actions = ref<{ value: string; label: string; token?: string }[]>([])
const actorTypes = ref<string[]>([])
const showChain = ref(false)
const chainTaskId = ref<number | null>(null)
const chainData = ref<{ task_id: number; project_id: number; timeline: AuditEntry[] } | null>(null)

const actorMeta: Record<string, { label: string; cls: string }> = {
  human: { label: '人', cls: 't-human' },
  agent: { label: 'AI', cls: 't-agent' },
  system: { label: '系统', cls: 't-system' },
}

// Action badge class is derived from the backend registry token.
const actionClass = (action: string) => `a-${audit.metaFor(action).token}`
const actionLabel = (action: string) => audit.metaFor(action).label

function fmtTime(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

async function applyFilters() {
  const p: Record<string, unknown> = {}
  if (filters.value.project_id) p.project_id = filters.value.project_id
  if (filters.value.actor_type) p.actor_type = filters.value.actor_type
  if (filters.value.action) p.action = filters.value.action
  if (filters.value.task_id) p.task_id = filters.value.task_id
  await audit.load(p)
}

async function viewChain(entry: AuditEntry) {
  if (!entry.task_id) {
    MessagePlugin.info('该操作不关联任务，无可追溯责任链')
    return
  }
  chainTaskId.value = entry.task_id
  const data = await audit.fetchChain(entry.task_id)
  chainData.value = data
  showChain.value = true
}

const projectOptions = computed(() =>
  projectStore.switchableProjects.map((p) => ({ value: p.id, label: p.name })),
)

onMounted(async () => {
  try {
    if (projectStore.switchableProjects.length === 0) await projectStore.fetchSwitchableProjects()
    const opts = await audit.fetchActions()
    actions.value = opts.actions
    actorTypes.value = opts.actor_types
  } catch { /* ignore */ }
  await applyFilters()
})
</script>

<template>
  <div class="page-root">
    <div class="page-header">
      <div>
        <h1 class="page-title">审计中心</h1>
        <p class="page-desc">全链路留痕：人为操作、人让 AI 干的事、对项目的影响，均可在责任链中追溯</p>
      </div>
    </div>

    <!-- Filters -->
    <div class="filter-bar">
      <select v-model="filters.project_id" class="f-select" @change="applyFilters">
        <option :value="null">全部项目</option>
        <option v-for="o in projectOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
      <select v-model="filters.actor_type" class="f-select" @change="applyFilters">
        <option value="">全部操作方</option>
        <option v-for="t in actorTypes" :key="t" :value="t">{{ actorMeta[t]?.label || t }}</option>
      </select>
      <select v-model="filters.action" class="f-select" @change="applyFilters">
        <option value="">全部动作</option>
        <option v-for="a in actions" :key="a.value" :value="a.value">{{ a.label }}</option>
      </select>
      <input v-model.number="filters.task_id" type="number" placeholder="按任务 ID" class="f-input" @change="applyFilters" />
      <t-button theme="default" variant="outline" size="small" @click="applyFilters">刷新</t-button>
    </div>

    <!-- List -->
    <div v-if="audit.loading" class="empty-card"><p>加载中…</p></div>
    <div v-else-if="audit.entries.length === 0" class="empty-card"><p>暂无审计记录</p></div>
    <div v-else class="audit-list">
      <div v-for="e in audit.entries" :key="e.id" class="audit-card" @click="viewChain(e)">
        <span class="badge" :class="actorMeta[e.actor_type]?.cls">{{ actorMeta[e.actor_type]?.label || e.actor_type }}</span>
        <span class="act-badge" :class="actionClass(e.action)">{{ actionLabel(e.action) }}</span>
        <span class="audit-actor">{{ e.actor_name || (e.actor_type === 'system' ? '系统' : (e.actor_type === 'agent' ? 'AI' : '未知')) }}</span>
        <span v-if="e.task_id" class="audit-task">#{{ e.task_id }}</span>
        <span class="audit-time">{{ fmtTime(e.created_at) }}</span>
        <p v-if="e.intent" class="audit-intent">{{ e.intent }}</p>
        <p v-if="e.impact" class="audit-impact">{{ e.impact }}</p>
      </div>
    </div>

    <!-- Chain drawer -->
    <Transition name="drawer-slide">
      <div v-if="showChain" class="drawer-mask" @click="showChain = false">
        <div class="drawer" @click.stop>
          <div class="drawer-head">
            <h2>责任链 · 任务 #{{ chainTaskId }}</h2>
            <button class="drawer-close" @click="showChain = false">×</button>
          </div>
          <div v-if="!chainData" class="empty-card"><p>加载中…</p></div>
          <div v-else class="chain">
            <div v-if="chainData.timeline.length === 0" class="empty-card"><p>该任务暂无审计记录</p></div>
            <div v-for="e in chainData.timeline" :key="e.id" class="chain-item">
              <span class="chain-dot" :class="actionClass(e.action)"></span>
              <div class="chain-body">
                <div class="chain-top">
                  <span class="act-badge" :class="actionClass(e.action)">{{ actionLabel(e.action) }}</span>
                  <span class="audit-actor">{{ e.actor_name || e.actor_type }}</span>
                  <span class="audit-time">{{ fmtTime(e.created_at) }}</span>
                </div>
                <p v-if="e.intent" class="audit-intent">{{ e.intent }}</p>
                <p v-if="e.impact" class="audit-impact">{{ e.impact }}</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.page-root { max-width: 960px; }
.page-header { margin-bottom: 16px; }
.page-title { margin: 0; font-size: 20px; font-weight: 700; color: var(--foreground); }
.page-desc { margin: 4px 0 0; font-size: 13px; color: var(--muted-foreground); }

/* ── Filters ─────────────────────────────────────────────────────── */
.filter-bar { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
.f-select, .f-input {
  padding: 7px 10px; font-size: 13px; color: var(--foreground);
  background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-md); outline: none; font-family: var(--font-sans);
}
.f-input { width: 130px; }
.f-select:focus, .f-input:focus { border-color: var(--ring); }

/* ── List ────────────────────────────────────────────────────────── */
.audit-list { display: flex; flex-direction: column; gap: 8px; }
.audit-card {
  background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg); padding: 12px 14px; cursor: pointer;
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}
.audit-card:hover { border-color: var(--ring); box-shadow: var(--shadow-surface); }
.audit-actor { font-size: 13px; font-weight: 600; color: var(--foreground); }
.audit-task { font-size: 12px; color: var(--primary); font-weight: 600; }
.audit-time { margin-left: auto; font-size: 12px; color: var(--muted-foreground); }
.audit-intent { flex-basis: 100%; margin: 4px 0 0; font-size: 12.5px; color: var(--muted-foreground); line-height: 1.5; }
.audit-impact { flex-basis: 100%; margin: 2px 0 0; font-size: 12.5px; color: #14b8a6; line-height: 1.5; }

/* ── Badges ──────────────────────────────────────────────────────── */
.badge, .act-badge {
  font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 8px;
}
.t-human { color: var(--primary); background: var(--primary-light); }
.t-agent { color: #a855f7; background: rgba(168,85,247,0.12); }
.t-system { color: var(--muted-foreground); background: var(--surface-hover); }
.a-task { color: #3b82f6; background: rgba(59,130,246,0.12); }
.a-agent { color: #a855f7; background: rgba(168,85,247,0.12); }
.a-review { color: #ec4899; background: rgba(236,72,153,0.12); }
.a-member { color: #f59e0b; background: rgba(245,158,11,0.12); }
.a-config { color: #64748b; background: rgba(100,116,139,0.12); }
.a-merge { color: #14b8a6; background: rgba(20,184,166,0.12); }
.a-system { color: var(--muted-foreground); background: var(--surface-hover); }

/* ── Drawer ──────────────────────────────────────────────────────── */
.drawer-mask {
  position: fixed; inset: 0; background: rgba(15,23,42,0.45);
  display: flex; justify-content: flex-end; z-index: 50;
}
.drawer {
  width: 460px; max-width: 92vw; height: 100%; background: var(--app-shell);
  border-left: 1px solid var(--surface-border); display: flex; flex-direction: column;
}
.drawer-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 18px; border-bottom: 1px solid var(--surface-border);
}
.drawer-head h2 { margin: 0; font-size: 15px; font-weight: 600; color: var(--foreground); }
.drawer-close {
  border: none; background: transparent; font-size: 22px; color: var(--muted-foreground);
  cursor: pointer; line-height: 1;
}
.drawer-close:hover { color: var(--foreground); }

.chain { padding: 16px 18px; overflow-y: auto; }
.chain-node { margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--surface-border); }
.chain-node-label { font-size: 12px; font-weight: 600; color: var(--muted-foreground); margin-bottom: 8px; }
.chain-item { display: flex; gap: 10px; padding: 8px 0; }
.chain-dot { width: 10px; height: 10px; border-radius: 50%; margin-top: 4px; flex-shrink: 0; background: var(--muted-foreground); }
.chain-body { flex: 1; }
.chain-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.empty-card {
  padding: 48px; text-align: center; color: var(--muted-foreground);
  background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg);
}
</style>
