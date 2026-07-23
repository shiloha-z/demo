<script setup lang="ts">
import { ref, watch } from 'vue'
import { useAuditStore } from '../stores/audit'

const props = defineProps<{ visible: boolean; taskId: number | null }>()
const emit = defineEmits<{ (e: 'update:visible', v: boolean): void }>()

const audit = useAuditStore()
const chain = ref<{ task_id: number; project_id: number; timeline: any[] } | null>(null)

// Action badge class is derived from the backend registry token, so new
// actions render automatically without hard-coding here.
const actionClass = (action: string) => `a-${audit.metaFor(action).token}`
const actionLabel = (action: string) => audit.metaFor(action).label

function fmt(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

watch(() => [props.visible, props.taskId], async ([vis]) => {
  if (vis && props.taskId) {
    chain.value = await audit.fetchChain(props.taskId)
  }
}, { immediate: true })

function close() { emit('update:visible', false) }
</script>

<template>
  <Transition name="drawer-slide">
    <div v-if="visible" class="chain-mask" @click="close">
      <div class="chain-drawer" @click.stop>
        <div class="chain-head">
          <h2>责任链 · 任务 #{{ taskId }}</h2>
          <button class="chain-close" @click="close">×</button>
        </div>
        <div v-if="!chain" class="empty-card"><p>加载中…</p></div>
        <div v-else class="chain-scroll">
          <div v-if="(chain.timeline?.length || 0) === 0" class="empty-card"><p>该任务暂无审计记录</p></div>
          <div v-for="e in (chain.timeline || [])" :key="e.id" class="chain-item">
            <span class="chain-dot" :class="actionClass(e.action)"></span>
            <div class="chain-body">
              <div class="chain-top">
                <span class="act-badge" :class="actionClass(e.action)">{{ actionLabel(e.action) }}</span>
                <span class="audit-actor">{{ e.actor_name || e.actor_type }}</span>
                <span class="audit-time">{{ fmt(e.created_at) }}</span>
              </div>
              <p v-if="e.intent" class="audit-intent">{{ e.intent }}</p>
              <p v-if="e.impact" class="audit-impact">{{ e.impact }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.chain-mask {
  position: fixed; inset: 0; background: rgba(15,23,42,0.45);
  display: flex; justify-content: flex-end; z-index: 60;
}
.chain-drawer {
  width: 480px; max-width: 92vw; height: 100%; background: var(--app-shell);
  border-left: 1px solid var(--surface-border); display: flex; flex-direction: column;
}
.chain-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 18px; border-bottom: 1px solid var(--surface-border);
}
.chain-head h2 { margin: 0; font-size: 15px; font-weight: 600; color: var(--foreground); }
.chain-close { border: none; background: transparent; font-size: 22px; color: var(--muted-foreground); cursor: pointer; line-height: 1; }
.chain-close:hover { color: var(--foreground); }
.chain-scroll { padding: 16px 18px; overflow-y: auto; }

.chain-item { display: flex; gap: 10px; padding: 8px 0; }
.chain-dot { width: 10px; height: 10px; border-radius: 50%; margin-top: 4px; flex-shrink: 0; background: var(--muted-foreground); }
.chain-body { flex: 1; }
.chain-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.act-badge { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 8px; }
.a-task { color: #3b82f6; background: rgba(59,130,246,0.12); }
.a-agent { color: #a855f7; background: rgba(168,85,247,0.12); }
.a-review { color: #ec4899; background: rgba(236,72,153,0.12); }
.a-member { color: #f59e0b; background: rgba(245,158,11,0.12); }
.a-config { color: #64748b; background: rgba(100,116,139,0.12); }
.a-merge { color: #14b8a6; background: rgba(20,184,166,0.12); }
.a-system { color: var(--muted-foreground); background: var(--surface-hover); }
.audit-actor { font-size: 13px; font-weight: 600; color: var(--foreground); }
.audit-time { margin-left: auto; font-size: 12px; color: var(--muted-foreground); }
.audit-intent { flex-basis: 100%; margin: 4px 0 0; font-size: 12.5px; color: var(--muted-foreground); line-height: 1.5; }
.audit-impact { flex-basis: 100%; margin: 2px 0 0; font-size: 12.5px; color: #14b8a6; line-height: 1.5; }

.empty-card {
  padding: 48px; text-align: center; color: var(--muted-foreground);
  background: var(--surface); border: 1px solid var(--surface-border); border-radius: var(--radius-lg);
}
</style>
