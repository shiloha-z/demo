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
        <h4>确定性合并门禁</h4>
        <p v-if="gate">{{ gate.summary || '正在执行合并前检查' }}</p>
        <p v-else>AI 审查完成后自动执行，七项检查全部通过才开放人工审批。</p>
      </div>
      <span v-if="gate" class="gate-status" :class="gate.status">
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
            {{ check.status === 'passed' ? '✓' : check.status === 'failed' ? '!' : check.status === 'running' ? '…' : '○' }}
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
      <span v-if="platformFailures.length">
        {{ platformFailures.map(check => check.label).join('、') }}属于平台环境问题，
        Agent 修改代码无法解决，请管理员安装检查工具或修正门禁命令。
      </span>
      <span v-else>确定性检查未通过，不能投通过票。请将失败项打回 Agent 修改。</span>
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
      <t-tag v-else-if="platformFailures.length" theme="danger" variant="light">需平台管理员处理</t-tag>
    </div>
  </section>
</template>

<style scoped>
.quality-gate-panel {
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg);
  background: var(--surface);
  overflow: hidden;
}
.gate-header {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 16px;
  padding: 14px 16px; border-bottom: 1px solid var(--surface-border);
}
.gate-header h4 { margin: 0; font-size: 14px; color: var(--foreground); }
.gate-header p { margin: 4px 0 0; font-size: 12px; color: var(--muted-foreground); }
.gate-status {
  flex-shrink: 0; padding: 3px 9px; border-radius: 999px;
  font-size: 11px; font-weight: 700;
  color: var(--primary); background: var(--primary-light);
}
.gate-status.passed { color: var(--success); background: var(--success-light); }
.gate-status.failed { color: var(--danger); background: var(--danger-light); }
.gate-checks { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.gate-check { border-bottom: 1px solid var(--surface-border); }
.gate-check:nth-child(odd) { border-right: 1px solid var(--surface-border); }
.gate-check:last-child { border-bottom: 0; }
.gate-check summary {
  list-style: none; display: flex; align-items: center; gap: 8px;
  min-height: 42px; padding: 0 12px; cursor: pointer; font-size: 12px;
}
.gate-check summary::-webkit-details-marker { display: none; }
.check-icon {
  width: 20px; height: 20px; display: inline-flex; align-items: center; justify-content: center;
  border-radius: 50%; color: var(--muted-foreground); background: var(--surface-hover);
  font-size: 12px; font-weight: 800;
}
.gate-check.passed .check-icon { color: var(--success); background: var(--success-light); }
.gate-check.failed .check-icon { color: var(--danger); background: var(--danger-light); }
.gate-check.running .check-icon { color: var(--primary); background: var(--primary-light); }
.check-label { font-weight: 600; color: var(--foreground); }
.check-duration { margin-left: auto; color: var(--muted-foreground); font-size: 10px; }
.check-status { min-width: 38px; text-align: right; color: var(--muted-foreground); }
.gate-check.passed .check-status { color: var(--success); }
.gate-check.failed .check-status { color: var(--danger); }
.gate-check pre, .gate-check p {
  margin: 0 12px 12px 40px; padding: 9px 10px; max-height: 180px; overflow: auto;
  border-radius: var(--radius-sm); background: var(--page-canvas);
  color: var(--muted-foreground); font: 11px/1.55 var(--font-mono); white-space: pre-wrap;
}
.gate-footer {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 10px 14px; color: var(--danger); background: var(--danger-light); font-size: 12px;
}
@media (max-width: 760px) {
  .gate-checks { grid-template-columns: 1fr; }
  .gate-check:nth-child(odd) { border-right: 0; }
}
</style>
