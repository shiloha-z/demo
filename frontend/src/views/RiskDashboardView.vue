<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { useProjectStore } from '../stores/project'
import DonutChart from '../components/charts/DonutChart.vue'
import BarChart from '../components/charts/BarChart.vue'
import VizCard from '../components/charts/VizCard.vue'
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

// ── Chart data ──────────────────────────────────────────────────────
const riskSeveritySegments = computed(() => {
  const d = dashboard.value?.risk_severity_breakdown?.detail
  if (!d) return []
  return [
    { label: '高风险', value: d.high || 0, color: 'var(--danger)' },
    { label: '中风险', value: d.medium || 0, color: 'var(--warning)' },
    { label: '低风险', value: d.low || 0, color: 'var(--info)' },
  ]
})

const passRatePct = computed(() => {
  const r = dashboard.value?.first_pass_rate
  if (!r || r.value === null) return null
  return String(r.value)
})

const passRateSegments = computed(() => {
  const d = dashboard.value?.first_pass_rate?.detail
  if (!d) return []
  const passed = d.first_pass || 0
  const total = d.total || 0
  const failed = Math.max(0, total - passed)
  return [
    { label: '首次通过', value: passed, color: 'var(--success)' },
    { label: '需返工', value: failed, color: 'var(--warning)' },
  ]
})

const qualityBars = computed(() => {
  const d = dashboard.value
  if (!d) return []
  return [
    { label: 'AI代码占比', value: parseFloat(String(d.ai_code_ratio?.value ?? 0)) || 0, color: 'var(--primary)' },
    { label: '门禁拦截', value: parseInt(String(d.gate_blocks?.value ?? 0)) || 0, color: 'var(--warning)' },
    { label: '重复问题降幅', value: parseInt(String(d.repeat_issue_reduction?.value ?? 0)) || 0, color: 'var(--success)' },
    { label: '回退次数', value: parseInt(String(d.rollback_count?.value ?? 0)) || 0, color: 'var(--danger)' },
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

    <template v-else-if="dashboard">
    <!-- ── Top KPI row ──────────────────────────────────────────────── -->
    <div class="stat-grid">
      <article
        v-for="card in kpiCards.slice(0, 4)"
        :key="card.key"
        class="stat-card"
        :class="{ 'stat-card--planned': card.data.status === 'planned' }"
      >
        <div class="stat-icon" :class="card.iconBg">
          <svg v-if="card.icon === 'tasks'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
          <svg v-else-if="card.icon === 'robot'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16.01"/><line x1="16" y1="16" x2="16" y2="16.01"/></svg>
          <svg v-else-if="card.icon === 'clock'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        </div>
        <div class="stat-body">
          <div class="stat-value">
            <template v-if="card.data.status === 'planned'">—</template>
            <template v-else>{{ fmtValue(card.data) }}<span v-if="card.data.value !== null" class="stat-unit"> {{ card.data.unit }}</span></template>
          </div>
          <div class="stat-label">{{ card.data.label }}</div>
        </div>
      </article>
    </div>

    <!-- ── Charts row ───────────────────────────────────────────────── -->
    <div class="viz-band">
      <VizCard title="风险严重度分布" hint="按严重度统计高风险 / 中风险 / 低风险任务数量。">
        <div class="donut-wrap">
          <DonutChart :segments="riskSeveritySegments" :center-top="String(dashboard.risk_severity_breakdown.value || '0')" center-bottom="总风险" />
          <div class="legend">
            <span v-for="s in riskSeveritySegments" :key="s.label" class="legend-item">
              <i class="legend-dot" :style="{ background: s.color }"></i>{{ s.label }} · {{ s.value }}
            </span>
          </div>
        </div>
      </VizCard>
      <VizCard title="审查一次通过率" hint="首次审查即通过 vs 需要返工修改的审查占比。">
        <DonutChart :segments="passRateSegments" :center-top="passRatePct || '—'" center-bottom="通过率" />
      </VizCard>
      <VizCard title="质量指标" hint="AI 代码占比 / 门禁拦截 / 重复问题降幅 / 回退次数。">
        <BarChart :items="qualityBars" :height="130" />
      </VizCard>
    </div>

    <!-- ── Bottom metrics ──────────────────────────────────────────── -->
    <div class="stat-grid stat-grid--compact">
      <article
        v-for="card in kpiCards.slice(4)"
        :key="card.key"
        class="stat-card stat-card--sm"
      >
        <div class="stat-icon stat-icon--sm" :class="card.iconBg">
          <svg v-if="card.icon === 'shield'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          <svg v-else-if="card.icon === 'gate'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
          <svg v-else-if="card.icon === 'check'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
          <svg v-else-if="card.icon === 'trend'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/></svg>
          <svg v-else-if="card.icon === 'undo'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>
          <svg v-else-if="card.icon === 'cost'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
        </div>
        <div class="stat-body">
          <div class="stat-value stat-value--sm">{{ fmtValue(card.data) }}<span v-if="card.data.value !== null" class="stat-unit"> {{ card.data.unit }}</span></div>
          <div class="stat-label">{{ card.data.label }}</div>
        </div>
      </article>
    </div>
    </template>

    <!-- Empty -->
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

/* ── Stat grid ──────────────────────────────────────────────────── */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 16px;
}
.stat-grid--compact {
  grid-template-columns: repeat(3, 1fr);
  margin-top: 0;
}
.stat-card {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 18px 20px;
  background: var(--card-bg) !important;
  border: var(--card-border) !important;
  border-radius: var(--radius-xl) !important;
  box-shadow: var(--card-shadow) !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}
.stat-card--sm { padding: 14px 16px; }

.stat-card--planned {
  opacity: 0.55;
  pointer-events: none;
}
.stat-card--planned .stat-value {
  font-size: 16px; font-weight: 500;
  color: var(--muted-foreground);
}

.stat-icon {
  width: 42px; height: 42px;
  border-radius: var(--radius-md);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.stat-icon--sm { width: 34px; height: 34px; }
.stat-icon--brand   { background: var(--primary-light);  color: var(--primary); }
.stat-icon--success { background: var(--success-light);  color: var(--success); }
.stat-icon--warning { background: var(--warning-light);  color: var(--warning); }
.stat-icon--danger  { background: var(--danger-light);   color: var(--danger); }
.stat-icon--info    { background: var(--info-light);     color: var(--info); }
.stat-icon--muted   { background: oklch(0.94 0.003 280); color: oklch(0.48 0.012 280); }

.stat-body { flex: 1; min-width: 0; }
.stat-value {
  font-size: 24px; font-weight: 700;
  color: var(--foreground);
  letter-spacing: -0.5px; line-height: 1.2;
}
.stat-value--sm { font-size: 18px; }
.stat-unit {
  font-size: 13px; font-weight: 500;
  color: var(--muted-foreground);
}
.stat-label {
  font-size: 12.5px; color: var(--muted-foreground); margin-top: 2px;
}

/* ── Charts ─────────────────────────────────────────────────────── */
.viz-band {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}
.donut-wrap { display: flex; align-items: center; gap: 18px; width: 100%; }
.legend { display: flex; flex-direction: column; gap: 7px; flex: 1; min-width: 0; }
.legend-item {
  font-size: 12px; color: var(--muted-foreground);
  display: flex; align-items: center; gap: 8px;
}
.legend-dot {
  width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0;
  box-shadow: 0 0 0 2px color-mix(in oklch, currentColor 18%, transparent);
}

.dark .stat-icon--muted {
  background: oklch(0.26 0.004 280);
  color: oklch(0.55 0.012 280);
}

@media (max-width: 960px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
  .viz-band { grid-template-columns: 1fr; }
}
@media (max-width: 560px) {
  .stat-grid, .stat-grid--compact { grid-template-columns: 1fr; }
}
</style>
