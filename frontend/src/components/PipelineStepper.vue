<script setup lang="ts">
import { ref, computed } from 'vue'

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
    default: return 'transparent'
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
        :class="stages[i - 1].status === 'done' ? 'done' : ''"
      />

      <!-- Stage node -->
      <div class="pipeline-node" :style="{ background: statusBg(s.status), borderColor: statusColor(s.status), color: statusColor(s.status) }">
        <!-- Spinner when running -->
        <span v-if="s.status === 'running'" class="stage-spinner" :style="{ borderTopColor: statusColor(s.status) }" />
        <!-- Check when done -->
        <svg v-else-if="s.status === 'done'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>
        <!-- X when error -->
        <svg v-else-if="s.status === 'error'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        <!-- Icon otherwise -->
        <span v-else class="stage-icon" v-html="iconHtml(s.icon)" />

        <div class="pipeline-label">
          <span class="pipeline-name">{{ s.label }}</span>
          <span class="pipeline-status-text">
            <template v-if="s.status === 'waiting'">等待中</template>
            <template v-else-if="s.status === 'running'">执行中...</template>
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
  padding: 16px 20px;
  background: var(--surface);
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg);
  overflow-x: auto;
}

.pipeline-stage {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.pipeline-connector {
  width: 32px;
  height: 2px;
  background: var(--surface-border);
  margin: 0 4px;
  transition: background var(--transition-base);
  flex-shrink: 0;
  align-self: center;
}
.pipeline-connector.done {
  background: var(--success);
}

.pipeline-node {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: var(--radius-md);
  border: 2px solid var(--surface-border);
  transition: all var(--transition-base);
  white-space: nowrap;
  min-width: 0;
}

.pipeline-node.running {
  box-shadow: 0 0 0 3px oklch(0.55 0.2 260 / 0.12);
}

.stage-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
}

.pipeline-label {
  display: flex;
  flex-direction: column;
  gap: 0;
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

/* Spinner */
.stage-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--surface-border);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  flex-shrink: 0;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
