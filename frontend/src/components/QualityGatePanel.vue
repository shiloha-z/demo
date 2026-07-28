<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  gate: any | null
  canReject?: boolean
  canRetry?: boolean
  rejecting?: boolean
  retrying?: boolean
}>()

defineEmits<{
  reject: []
  retry: []
}>()

const expectedChecks = [
  { key: 'unit_tests', label: '单元测试' },
  { key: 'style', label: '代码格式与规范' },
  { key: 'static_analysis', label: '静态安全扫描' },
  { key: 'secret_scan', label: '硬编码密钥扫描' },
  { key: 'dependency_audit', label: '依赖漏洞检查' },
  { key: 'coverage', label: '测试覆盖率' },
  { key: 'bank_policy', label: '银行内部禁止项' },
]

interface GateCheck {
  key: string
  label: string
  status: string
  output: string
  duration_ms: number
  command?: string
  findings?: number
  failure_scope?: string
  agent_actionable?: boolean
}

const failedChecks = computed<GateCheck[]>(() =>
  (props.gate?.checks || []).filter((check: GateCheck) => check.status === 'failed'),
)
const platformFailures = computed(() =>
  failedChecks.value.filter(check => check.agent_actionable === false),
)
const canReturnToAgent = computed(() =>
  Boolean(props.canReject) && failedChecks.value.length > 0 && platformFailures.value.length === 0,
)

function checksFor(gate: any): GateCheck[] {
  const actual = new Map<string, GateCheck>(
    (gate?.checks || []).map((check: GateCheck) => [check.key, check]),
  )
  return expectedChecks.map((expected) => actual.get(expected.key) || {
    ...expected,
    status: gate?.status === 'running' ? 'running' : 'waiting',
    output: '',
    duration_ms: 0,
  })
}

function statusLabel(status: string) {
  return {
    waiting: '等待',
    running: '执行中',
    passed: '通过',
    failed: '未通过',
  }[status] || status
}
</script>

<template>
  <section class="quality-gate-panel">
    <div class="gate-header">
      <div>
        <h4>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          确定性合并门禁
        </h4>
        <p v-if="gate">{{ gate.summary || '正在执行合并前检查' }}</p>
        <p v-else>AI 审查完成后自动执行，七项检查全部通过才开放人工审批。</p>
      </div>
      <span v-if="gate" class="gate-badge" :class="gate.status">
        <span class="gate-badge-dot" />
        {{ gate.status === 'passed' ? '全部通过' : gate.status === 'failed' ? '已拦截' : '检查中' }}
      </span>
    </div>

    <div class="gate-checks">
      <details
        v-for="check in checksFor(gate)"
        :key="check.key"
        class="gate-check"
        :class="check.status"
      >
        <summary>
          <span class="check-icon">
            <!-- Passed -->
            <svg v-if="check.status === 'passed'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>
            <!-- Failed -->
            <svg v-else-if="check.status === 'failed'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            <!-- Running spinner -->
            <span v-else-if="check.status === 'running'" class="mini-spin" />
            <!-- Waiting dot -->
            <span v-else class="waiting-dot" />
          </span>
          <span class="check-label">{{ check.label }}</span>
          <span v-if="check.duration_ms" class="check-duration">{{ check.duration_ms }} ms</span>
          <span class="check-status">{{ statusLabel(check.status) }}</span>
        </summary>
        <pre v-if="check.output">{{ check.output }}</pre>
        <p v-else>尚未执行。</p>
      </details>
    </div>

    <div v-if="gate?.status === 'failed'" class="gate-footer">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      <span v-if="platformFailures.length" class="footer-msg">
        {{ platformFailures.map(check => check.label).join('、') }}属于平台环境问题，Agent 修改代码无法解决。
      </span>
      <span v-else class="footer-msg">确定性检查未通过，不能投通过票。请将失败项打回 Agent 修改。</span>
      <t-button
        v-if="canReturnToAgent"
        size="small"
        theme="warning"
        variant="outline"
        :loading="rejecting"
        @click="$emit('reject')"
      >
        按失败项打回 Agent
      </t-button>
      <t-button
        v-else-if="platformFailures.length && canRetry"
        size="small"
        theme="danger"
        variant="outline"
        :loading="retrying"
        @click="$emit('retry')"
      >
        环境修复后重新检查
      </t-button>
    </div>
  </section>
</template>

<style scoped>
.quality-gate-panel {
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  background: var(--glass-surface-strong);
  box-shadow: var(--shadow-surface), var(--glass-highlight);
  backdrop-filter: blur(var(--glass-blur-sm)) saturate(var(--glass-saturate));
  overflow: hidden;
}

/* ── Header ────────────────────────────────────────────────────────── */
.gate-header {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 16px;
  padding: 14px 16px; border-bottom: 1px solid var(--surface-border);
}
.gate-header h4 {
  margin: 0; font-size: 14px; color: var(--foreground);
  display: flex; align-items: center; gap: 7px;
}
.gate-header h4 svg { color: var(--primary); opacity: 0.8; }
.gate-header p { margin: 4px 0 0; font-size: 12px; color: var(--muted-foreground); }

.gate-badge {
  flex-shrink: 0; padding: 4px 10px; border-radius: 999px;
  font-size: 11px; font-weight: 700;
  color: var(--primary); background: var(--primary-light);
  display: flex; align-items: center; gap: 5px;
  border: 1px solid color-mix(in oklch, var(--primary) 20%, transparent);
}
.gate-badge-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--primary); }
.gate-badge.passed { color: var(--success); background: var(--success-light); border-color: color-mix(in oklch, var(--success) 20%, transparent); }
.gate-badge.passed .gate-badge-dot { background: var(--success); }
.gate-badge.failed { color: var(--danger); background: var(--danger-light); border-color: color-mix(in oklch, var(--danger) 20%, transparent); }
.gate-badge.failed .gate-badge-dot { background: var(--danger); }

/* ── Checks grid ────────────────────────────────────────────────────── */
.gate-checks { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.gate-check { border-bottom: 1px solid var(--surface-border); transition: background var(--transition-fast); }
.gate-check:nth-child(odd) { border-right: 1px solid var(--surface-border); }
.gate-check:last-child { border-bottom: 0; }
.gate-check:nth-child(6):nth-last-child(1) { border-bottom: 0; border-right: 0; }
.gate-check:hover { background: var(--surface-hover); }

.gate-check summary {
  list-style: none; display: flex; align-items: center; gap: 8px;
  min-height: 42px; padding: 0 12px; cursor: pointer; font-size: 12px;
  user-select: none;
}
.gate-check summary::-webkit-details-marker { display: none; }

.check-icon {
  width: 22px; height: 22px; display: inline-flex; align-items: center; justify-content: center;
  border-radius: var(--radius-sm); flex-shrink: 0;
  color: var(--muted-foreground); background: var(--surface-hover);
}
.gate-check.passed .check-icon { color: var(--success); background: var(--success-light); }
.gate-check.failed .check-icon { color: var(--danger); background: var(--danger-light); }
.gate-check.running .check-icon { color: var(--primary); background: var(--primary-light); }

.waiting-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--surface-border);
}

.mini-spin {
  width: 12px; height: 12px;
  border: 2px solid color-mix(in oklch, currentColor 20%, transparent);
  border-top-color: currentColor;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

.check-label { font-weight: 600; color: var(--foreground); flex: 1; }
.check-duration { color: var(--muted-foreground); font-size: 10px; font-family: var(--font-mono); }
.check-status { min-width: 36px; text-align: right; font-size: 11px; font-weight: 600; color: var(--muted-foreground); }
.gate-check.passed .check-status { color: var(--success); }
.gate-check.failed .check-status { color: var(--danger); }
.gate-check.running .check-status { color: var(--primary); }

.gate-check pre, .gate-check p {
  margin: 0 12px 12px 42px; padding: 9px 10px; max-height: 180px; overflow: auto;
  border-radius: var(--radius-sm); background: var(--page-canvas);
  color: var(--muted-foreground); font: 11px/1.55 var(--font-mono); white-space: pre-wrap;
  border: 1px solid var(--surface-border);
}

/* ── Footer ─────────────────────────────────────────────────────────── */
.gate-footer {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 10px 14px; color: var(--danger);
  background: var(--danger-light);
  border-top: 1px solid color-mix(in oklch, var(--danger) 18%, transparent);
  font-size: 12px;
}
.gate-footer svg { flex-shrink: 0; }
.footer-msg { flex: 1; min-width: 0; }

@media (max-width: 760px) {
  .gate-checks { grid-template-columns: 1fr; }
  .gate-check:nth-child(odd) { border-right: 0; }
}

@keyframes spin { to { transform: rotate(360deg); } }
</style>
