<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { useProjectStore } from '../stores/project'
import api, { getErrorMessage } from '../api'

interface RiskMetric {
  value: number | string | null
  label: string
  unit: string
  status: string
  detail: Record<string, number> | null
}

interface DashboardData {
  project_id: number | null
  tasks_this_week: RiskMetric
  ai_code_ratio: RiskMetric
  avg_task_time: RiskMetric
  avg_review_time: RiskMetric
  risk_severity_breakdown: RiskMetric
  gate_blocks: RiskMetric
  first_pass_rate: RiskMetric
  repeat_issue_reduction: RiskMetric
  rollback_count: RiskMetric
  model_cost: RiskMetric
}

const store = useProjectStore()
const dashboard = ref<DashboardData | null>(null)
const loading = ref(false)
const selectedProjectId = ref<number | null>(store.currentProject?.id ?? null)

const projectOptions = computed(() => [
  { label: '全局统计', value: null as unknown as number },
  ...store.switchableProjects.map((p: any) => ({ label: p.name, value: p.id as number })),
])

async function fetchDashboard() {
  loading.value = true
  try {
    const params: Record<string, any> = {}
    if (selectedProjectId.value) params.project_id = selectedProjectId.value
    const { data } = await api.get('/risk-dashboard', { params })
    dashboard.value = data
  } catch (e: any) {
    MessagePlugin.error(getErrorMessage(e, '加载仪表盘数据失败'))
  } finally {
    loading.value = false
  }
}

watch(selectedProjectId, () => fetchDashboard())
watch(() => store.currentProject?.id, (newId) => {
  if (newId !== selectedProjectId.value) selectedProjectId.value = newId ?? null
})

onMounted(async () => {
  if (store.switchableProjects.length === 0) await store.fetchSwitchableProjects()
  await fetchDashboard()
})

// ── Card configs derived from API response ───────────────────────────

interface KpiCard {
  key: string
  data: RiskMetric
  icon: string
  iconBg: string
}

const iconColors: Record<string, string> = {
  brand: 'stat-icon--brand',
  success: 'stat-icon--success',
  warning: 'stat-icon--warning',
  danger: 'stat-icon--danger',
  info: 'stat-icon--info',
  muted: 'stat-icon--muted',
}

function fmtValue(m: RiskMetric): string {
  if (m.value === null || m.value === undefined) return '—'
  return String(m.value)
}

const kpiCards = computed<KpiCard[]>(() => {
  if (!dashboard.value) return []
  const d = dashboard.value
  return [
    { key: 'tasks_this_week',        data: d.tasks_this_week,        icon: 'tasks',   iconBg: iconColors.brand },
    { key: 'ai_code_ratio',          data: d.ai_code_ratio,          icon: 'robot',   iconBg: iconColors.muted },
    { key: 'avg_task_time',          data: d.avg_task_time,          icon: 'clock',   iconBg: iconColors.info },
    { key: 'avg_review_time',        data: d.avg_review_time,        icon: 'review',  iconBg: iconColors.info },
    { key: 'risk_severity_breakdown',data: d.risk_severity_breakdown,icon: 'shield',  iconBg: iconColors.danger },
    { key: 'gate_blocks',            data: d.gate_blocks,            icon: 'gate',    iconBg: iconColors.warning },
    { key: 'first_pass_rate',        data: d.first_pass_rate,        icon: 'check',   iconBg: iconColors.success },
    { key: 'repeat_issue_reduction', data: d.repeat_issue_reduction, icon: 'trend',   iconBg: iconColors.muted },
    { key: 'rollback_count',         data: d.rollback_count,         icon: 'undo',    iconBg: iconColors.muted },
    { key: 'model_cost',             data: d.model_cost,             icon: 'cost',    iconBg: iconColors.muted },
  ]
})
</script>

<template>
  <div class="page-root">
    <!-- Header -->
    <div class="page-header">
      <div>
        <h1 class="page-title">风险驾驶舱</h1>
        <p class="page-desc">AI 协作风险监控与质量度量</p>
      </div>
      <t-select
        v-model="selectedProjectId"
        size="medium"
        style="width: 200px"
        :options="projectOptions"
        placeholder="选择项目"
      />
    </div>

    <!-- Loading -->
    <div v-if="loading" class="empty-card">
      <div class="loading-spinner"></div>
      <p>加载中...</p>
    </div>

    <!-- KPI Grid -->
    <div v-else-if="dashboard" class="stat-grid">
      <article
        v-for="card in kpiCards"
        :key="card.key"
        class="stat-card"
        :class="{ 'stat-card--planned': card.data.status === 'planned' }"
      >
        <div class="stat-icon" :class="card.iconBg">
          <!-- tasks -->
          <svg v-if="card.icon === 'tasks'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
          <!-- robot / AI -->
          <svg v-else-if="card.icon === 'robot'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16.01"/><line x1="16" y1="16" x2="16" y2="16.01"/></svg>
          <!-- clock -->
          <svg v-else-if="card.icon === 'clock'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          <!-- review / document-check -->
          <svg v-else-if="card.icon === 'review'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
          <!-- shield / security -->
          <svg v-else-if="card.icon === 'shield'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          <!-- gate / barrier -->
          <svg v-else-if="card.icon === 'gate'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
          <!-- check / approve -->
          <svg v-else-if="card.icon === 'check'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
          <!-- trend down -->
          <svg v-else-if="card.icon === 'trend'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/></svg>
          <!-- undo / rollback -->
          <svg v-else-if="card.icon === 'undo'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>
          <!-- cost / dollar -->
          <svg v-else-if="card.icon === 'cost'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
        </div>

        <div class="stat-body">
          <div class="stat-value">
            <template v-if="card.data.status === 'planned'">规划中</template>
            <template v-else>{{ fmtValue(card.data) }}<span v-if="card.data.value !== null" class="stat-unit"> {{ card.data.unit }}</span></template>
          </div>
          <div class="stat-label">{{ card.data.label }}</div>

          <!-- Risk severity chips (KPI 5 only) -->
          <div v-if="card.key === 'risk_severity_breakdown' && card.data.detail" class="risk-chips">
            <span class="risk-chip risk-high">高 {{ card.data.detail.high }}</span>
            <span class="risk-chip risk-med">中 {{ card.data.detail.medium }}</span>
            <span class="risk-chip risk-low">低 {{ card.data.detail.low }}</span>
          </div>

          <!-- First-pass detail (KPI 7 only) -->
          <div v-else-if="card.key === 'first_pass_rate' && card.data.detail" class="first-pass-detail">
            {{ card.data.detail.first_pass }} / {{ card.data.detail.total }} 次审查首次通过
          </div>
        </div>
      </article>
    </div>

    <!-- Empty (shouldn't normally happen — API always returns data) -->
    <div v-else class="empty-card">
      <div class="empty-icon">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
      </div>
      <h3>暂无数据</h3>
      <p>尚未有任务、审查或门禁记录</p>
    </div>
  </div>
</template>

<style scoped>
.page-root { max-width: 1200px; }

/* ── Stat grid — 5 columns for 10 cards ──────────────────────────── */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.stat-card { padding: 22px 24px; }

@media (max-width: 900px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 560px) {
  .stat-grid { grid-template-columns: 1fr; }
}

.stat-card {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  background: var(--surface);
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg);
  padding: 18px 20px;
  box-shadow: var(--shadow-surface);
  transition: border-color var(--transition-base), box-shadow var(--transition-base);
}
.stat-card:hover {
  border-color: var(--primary);
  box-shadow: var(--shadow-card-hover);
}

/* ── Planned / muted ─────────────────────────────────────────────── */
.stat-card--planned {
  opacity: 0.55;
  pointer-events: none;
}
.stat-card--planned .stat-value {
  font-size: 16px;
  font-weight: 500;
  color: var(--muted-foreground);
}

/* ── Icon ────────────────────────────────────────────────────────── */
.stat-icon {
  width: 42px; height: 42px;
  border-radius: var(--radius-md);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.stat-icon--brand   { background: var(--primary-light);  color: var(--primary); }
.stat-icon--success { background: var(--success-light);  color: var(--success); }
.stat-icon--warning { background: var(--warning-light);  color: var(--warning); }
.stat-icon--danger  { background: var(--danger-light);   color: var(--danger); }
.stat-icon--info    { background: var(--info-light);     color: var(--info); }
.stat-icon--muted   { background: oklch(0.94 0.003 280); color: oklch(0.48 0.012 280); }

/* ── Body ────────────────────────────────────────────────────────── */
.stat-body { flex: 1; min-width: 0; }

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--foreground);
  letter-spacing: -0.5px;
  line-height: 1.2;
}
.stat-unit {
  font-size: 13px;
  font-weight: 500;
  color: var(--muted-foreground);
  letter-spacing: 0;
}
.stat-label {
  font-size: 12.5px;
  color: var(--muted-foreground);
  margin-top: 2px;
}

/* ── Risk severity chips ─────────────────────────────────────────── */
.risk-chips {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}
.risk-chip {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.6;
}
.risk-high { background: var(--danger-light);  color: var(--danger); }
.risk-med  { background: var(--warning-light); color: var(--warning); }
.risk-low  { background: var(--info-light);    color: var(--info); }

/* ── First-pass detail ───────────────────────────────────────────── */
.first-pass-detail {
  margin-top: 6px;
  font-size: 11px;
  color: var(--muted-foreground);
}

/* ── Dark mode — muted icon ──────────────────────────────────────── */
:root.dark .stat-icon--muted {
  background: oklch(0.26 0.004 280);
  color: oklch(0.55 0.012 280);
}
</style>
