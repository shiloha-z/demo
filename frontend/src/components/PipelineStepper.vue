<script setup lang="ts">

export interface StageState {
  key: string
  label: string
  icon: string
  status: 'waiting' | 'running' | 'done' | 'error'
  startedAt: string | null
  doneAt: string | null
}

const props = defineProps<{
  stages: StageState[]
}>()

const stageIcons: Record<string, string> = {
  code: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
  eye: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>',
  shield: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
  file: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>',
  circle: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/></svg>',
}

function statusColor(status: string): string {
  switch (status) {
    case 'running': return 'var(--primary)'
    case 'done': return 'var(--success)'
    case 'error': return 'var(--danger)'
    default: return 'var(--surface-border)'
  }
}

function statusBg(status: string): string {
  switch (status) {
    case 'running': return 'var(--primary-light)'
    case 'done': return 'var(--success-light)'
    case 'error': return 'var(--danger-light)'
    default: return 'var(--surface-hover)'
  }
}

function iconHtml(icon: string): string {
  return stageIcons[icon] || stageIcons.circle
}
</script>

<template>
  <div class="pipeline-stepper">
    <div
      v-for="(s, i) in stages"
      :key="s.key"
      class="pipeline-stage"
      :class="s.status"
    >
      <!-- Connector line -->
      <div
        v-if="i > 0"
        class="pipeline-connector"
        :class="{
          done: stages[i - 1].status === 'done',
          active: stages[i - 1].status === 'running',
        }"
      >
        <div class="connector-fill" />
      </div>

      <!-- Stage node -->
      <div
        class="pipeline-node"
        :style="{
          '--node-color': statusColor(s.status),
          '--node-bg': statusBg(s.status),
        }"
      >
        <!-- Icon area -->
        <div class="node-icon">
          <!-- Spinner when running -->
          <span v-if="s.status === 'running'" class="stage-spinner" />
          <!-- Check when done -->
          <svg v-else-if="s.status === 'done'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
          <!-- X when error -->
          <svg v-else-if="s.status === 'error'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          <!-- Role icon -->
          <span v-else class="stage-icon" v-html="iconHtml(s.icon)" />
        </div>

        <div class="pipeline-label">
          <span class="pipeline-name">{{ s.label }}</span>
          <span class="pipeline-status-text">
            <template v-if="s.status === 'waiting'">等待中</template>
            <template v-else-if="s.status === 'running'">执行中…</template>
            <template v-else-if="s.status === 'done'">完成</template>
            <template v-else-if="s.status === 'error'">出错</template>
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pipeline-stepper {
  display: flex;
  align-items: flex-start;
  gap: 0;
  padding: 14px 18px;
  background: var(--glass-surface-soft);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-surface), var(--glass-highlight);
  backdrop-filter: blur(var(--glass-blur-sm)) saturate(var(--glass-saturate));
  overflow-x: auto;
}

.pipeline-stage {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

/* ── Connector ──────────────────────────────────────────────────── */
.pipeline-connector {
  width: 36px;
  height: 3px;
  background: var(--surface-border);
  border-radius: 2px;
  margin: 0 2px;
  flex-shrink: 0;
  align-self: center;
  position: relative;
  overflow: hidden;
}
.connector-fill {
  position: absolute; inset: 0;
  border-radius: 2px;
  background: var(--surface-border);
  transition: background 0.4s ease, transform 0.6s var(--motion-ease-enter);
  transform: scaleX(0);
  transform-origin: left;
}
.pipeline-connector.done .connector-fill {
  background: linear-gradient(90deg, var(--success), var(--primary));
  transform: scaleX(1);
}
.pipeline-connector.active .connector-fill {
  background: var(--primary);
  transform: scaleX(0.5);
  animation: connectorPulse 1.2s ease-in-out infinite;
}
@keyframes connectorPulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}

/* ── Node ───────────────────────────────────────────────────────── */
.pipeline-node {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 14px;
  border-radius: var(--radius-md);
  border: 2px solid var(--node-color, var(--surface-border));
  background: var(--node-bg, var(--surface-hover));
  color: var(--node-color, var(--muted-foreground));
  transition: all var(--transition-base), box-shadow 0.3s ease;
  white-space: nowrap;
  min-width: 0;
}

.pipeline-node.running {
  box-shadow: 0 0 0 4px oklch(0.55 0.2 260 / 0.08);
  animation: nodePulse 2s ease-in-out infinite;
}
@keyframes nodePulse {
  0%, 100% { box-shadow: 0 0 0 4px oklch(0.55 0.2 260 / 0.08); }
  50% { box-shadow: 0 0 0 7px oklch(0.55 0.2 260 / 0.04); }
}

.pipeline-node.done {
  border-color: var(--success);
  background: var(--success-light);
  color: var(--success);
}

.pipeline-node.error {
  border-color: var(--danger);
  background: var(--danger-light);
  color: var(--danger);
  animation: errorShake 0.4s ease;
}
@keyframes errorShake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-3px); }
  75% { transform: translateX(3px); }
}

.node-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px; height: 30px;
  border-radius: var(--radius-sm);
  background: color-mix(in oklch, currentColor 12%, transparent);
  flex-shrink: 0;
}

.stage-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  opacity: 0.8;
}

.pipeline-label {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.pipeline-name {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--foreground);
  line-height: 1.3;
}

.pipeline-status-text {
  font-size: 10.5px;
  color: var(--muted-foreground);
  line-height: 1.3;
}

/* ── Spinner ────────────────────────────────────────────────────── */
.stage-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid color-mix(in oklch, currentColor 20%, transparent);
  border-top-color: currentColor;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  flex-shrink: 0;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
