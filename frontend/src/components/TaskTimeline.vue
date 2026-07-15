<script setup lang="ts">
import { computed } from 'vue'

export interface TimelineTask {
  id: number
  title: string
  status: string
  startedAt: string | null
  completedAt: string | null
  createdAt: string
  agentName: string
  agentRole: string
}

const props = defineProps<{
  tasks: TimelineTask[]
}>()

const roleLabels: Record<string, string> = {
  code_gen: '代码生成', reviewer: '审查', security: '安全',
}
const roleColors: Record<string, string> = {
  code_gen: 'var(--primary)', reviewer: 'var(--warning)', security: 'var(--danger)',
}
const statusLabels: Record<string, string> = {
  pending: '等待中', running: '执行中', reviewing: '待审核',
  approved: '已通过', rejected: '已驳回', completed: '已完成', failed: '失败',
}
const statusColors: Record<string, string> = {
  approved: 'var(--success)', rejected: 'var(--danger)',
  completed: 'var(--success)', failed: 'var(--danger)',
  reviewing: '#f59e0b', running: 'var(--primary)', pending: 'var(--warning)',
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function formatDuration(start: string | null, end: string | null): string {
  if (!start || !end) return '—'
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (ms < 1000) return '<1s'
  if (ms < 60000) return `${Math.round(ms / 1000)}s`
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`
}

function barWidth(task: TimelineTask): string {
  if (!task.startedAt || !task.completedAt) return '60px'
  const dur = new Date(task.completedAt).getTime() - new Date(task.startedAt).getTime()
  // Scale: 1s = 2px, min 40px, max 200px
  const w = Math.max(40, Math.min(200, dur / 500))
  return `${w}px`
}

function barColor(status: string): string {
  if (status === 'approved' || status === 'completed') return 'var(--success)'
  if (status === 'rejected') return 'var(--danger)'
  if (status === 'failed') return 'var(--danger)'
  if (status === 'reviewing') return '#f59e0b'
  return 'var(--primary)'
}
</script>

<template>
  <div class="task-timeline" v-if="tasks.length > 0">
    <div class="timeline-title">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
      任务执行时间线
    </div>
    <div class="timeline-list">
      <div v-for="t in tasks" :key="t.id" class="timeline-row">
        <div class="timeline-left">
          <span class="timeline-id">#{{ t.id }}</span>
          <span class="timeline-title-text">{{ t.title }}</span>
        </div>
        <div class="timeline-bar-area">
          <div
            class="timeline-bar"
            :style="{ width: barWidth(t), background: barColor(t.status) }"
            :title="`${t.title} — ${formatDuration(t.startedAt, t.completedAt)}`"
          />
          <span class="timeline-duration">{{ formatDuration(t.startedAt, t.completedAt) }}</span>
        </div>
        <div class="timeline-right">
          <span class="timeline-agent">
            <span class="role-dot" :style="{ background: roleColors[t.agentRole] || 'var(--muted-foreground)' }" />
            {{ t.agentName }}
          </span>
          <span class="timeline-status" :style="{ color: statusColors[t.status] || 'var(--muted-foreground)' }">
            {{ statusLabels[t.status] || t.status }}
          </span>
          <span class="timeline-time">{{ formatTime(t.startedAt) }} → {{ formatTime(t.completedAt) }}</span>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="timeline-empty">
    <p>暂无任务数据</p>
  </div>
</template>

<style scoped>
.task-timeline {
  margin-top: 20px;
  background: var(--surface);
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.timeline-title {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  font-size: 12px;
  font-weight: 700;
  color: var(--muted-foreground);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  background: var(--surface-hover);
  border-bottom: 1px solid var(--surface-border);
}

.timeline-list {
  display: flex;
  flex-direction: column;
}

.timeline-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--surface-border);
  transition: background var(--transition-fast);
}
.timeline-row:last-child { border-bottom: none; }
.timeline-row:hover { background: var(--surface-hover); }

.timeline-left {
  width: 180px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.timeline-id {
  font-size: 11px;
  font-weight: 700;
  color: var(--muted-foreground);
  font-family: var(--font-mono);
  flex-shrink: 0;
}
.timeline-title-text {
  font-size: 13px;
  font-weight: 600;
  color: var(--foreground);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.timeline-bar-area {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.timeline-bar {
  height: 8px;
  border-radius: 4px;
  flex-shrink: 0;
  opacity: 0.85;
  transition: width var(--transition-base);
  min-width: 4px;
}
.timeline-duration {
  font-size: 11px;
  color: var(--muted-foreground);
  font-family: var(--font-mono);
  white-space: nowrap;
}

.timeline-right {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--muted-foreground);
  flex-shrink: 0;
  white-space: nowrap;
}

.role-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}

.timeline-agent {
  display: flex;
  align-items: center;
  gap: 4px;
  font-weight: 500;
}

.timeline-status {
  font-weight: 600;
}

.timeline-time {
  font-family: var(--font-mono);
}

.timeline-empty {
  padding: 32px;
  text-align: center;
  color: var(--muted-foreground);
}
</style>
