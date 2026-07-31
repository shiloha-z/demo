<script setup lang="ts">
import { computed } from 'vue'
import MemoryTypeDonut from './MemoryTypeDonut.vue'
import { typeLabel, sourceLabel, formatTime, highlightSegments, type MemoryEntry } from '../../utils/memoryFormat'

export interface CardLayer {
  key: string
  label: string
  description: string
  count: number
  isEphemeral: boolean
  available: boolean
  colorVar: string
  typeCounts: Record<string, number> | null
  recent: MemoryEntry[]
}

const props = withDefaults(defineProps<{ layer: CardLayer; query?: string }>(), { query: '' })

const allMemories = computed(() => props.layer.recent || [])
const typeSummary = computed(() => {
  const counts = props.layer.typeCounts || {}
  return Object.entries(counts)
    .map(([k, v]) => ({ key: k, label: typeLabel(k), value: v }))
    .sort((a, b) => b.value - a.value)
})
const maxReuse = computed(() => {
  let m = 1
  for (const x of allMemories.value) m = Math.max(m, Number(x.metadata?.occurrences || 1))
  return m
})
</script>

<template>
  <article class="layer-panel" :style="{ '--accent': layer.colorVar }">
    <header class="panel-head">
      <span class="accent-bar"></span>
      <div class="head-text">
        <h3>
          {{ layer.label }}
          <span v-if="layer.isEphemeral" class="ephemeral-tag">临时层</span>
        </h3>
        <p v-if="!layer.isEphemeral">{{ Number.isFinite(layer.count) ? layer.count + ' 条记忆' : '—' }}</p>
      </div>
    </header>

    <div v-if="!layer.available" class="panel-warning">
      记忆后端（ChromaDB）当前不可用，恢复后自动启用。
    </div>

    <template v-else>
      <div v-if="layer.isEphemeral" class="ephemeral-note">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="9" /><path d="M12 8v4" /><path d="M12 16h.01" />
        </svg>
        <div>
          <p class="note-title">任务层不长期留存</p>
          <p class="note-body">{{ layer.description }}</p>
        </div>
      </div>

      <div v-else class="panel-body">
        <div class="stats">
          <MemoryTypeDonut :type-counts="layer.typeCounts" :size="128" />
          <ul v-if="typeSummary.length" class="type-legend">
            <li v-for="t in typeSummary" :key="t.key">
              <span class="dot" :style="{ background: 'var(--accent)' }"></span>
              <span class="t-name">{{ t.label }}</span>
              <span class="t-val">{{ t.value }}</span>
            </li>
          </ul>
        </div>

        <div class="mem-column">
          <div class="mem-head">
            <h4>记忆流</h4>
            <span v-if="query" class="filter-chip">筛选「{{ query }}」</span>
          </div>
          <ul v-if="allMemories.length" class="mem-list">
            <li v-for="m in allMemories" :key="m.id" class="mem-item">
              <div class="mem-top">
                <span class="chip">{{ typeLabel(String(m.metadata?.type || 'uncategorized')) }}</span>
                <span v-if="sourceLabel(m.metadata)" class="src">{{ sourceLabel(m.metadata) }}</span>
                <span class="reuse" :class="{ strong: Number(m.metadata?.occurrences || 1) >= maxReuse && maxReuse > 1 }">
                  复用 {{ m.metadata?.occurrences || 1 }} 次
                </span>
                <time v-if="m.metadata?.timestamp">{{ formatTime(m.metadata.timestamp) }}</time>
              </div>
              <p class="doc">
                <template v-for="(seg, si) in highlightSegments(m.document, query)" :key="si">
                  <mark v-if="seg.match">{{ seg.text }}</mark><template v-else>{{ seg.text }}</template>
                </template>
              </p>
            </li>
          </ul>
          <p v-else class="no-mem">
            {{ query ? '没有匹配该关键词的记忆。' : '该层暂无沉淀记忆。' }}
          </p>
        </div>
      </div>
    </template>

    <p v-if="!layer.isEphemeral" class="panel-desc">{{ layer.description }}</p>
  </article>
</template>

<style scoped>
.layer-panel {
  background: var(--glass-surface-strong);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-glass), var(--glass-highlight);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.panel-head { display: flex; align-items: stretch; gap: 12px; }
.accent-bar { width: 4px; border-radius: 4px; background: var(--accent); flex-shrink: 0; }
.head-text h3 { margin: 0; font-size: 16px; font-weight: 600; color: var(--foreground); display: flex; align-items: center; gap: 8px; }
.head-text p { margin: 3px 0 0; font-size: 12.5px; color: var(--muted-foreground); }
.ephemeral-tag {
  font-size: 10px; font-weight: 600; color: var(--info);
  background: var(--info-light); padding: 2px 8px; border-radius: 999px;
}
.panel-warning {
  font-size: 12.5px; color: var(--warning); background: var(--warning-light);
  border-radius: var(--radius-md); padding: 12px 14px;
}
.ephemeral-note { display: flex; gap: 12px; align-items: flex-start; color: var(--info); background: var(--info-light); border-radius: var(--radius-md); padding: 14px 16px; }
.note-title { margin: 0; font-size: 13px; font-weight: 600; color: var(--foreground); }
.note-body { margin: 4px 0 0; font-size: 12px; color: var(--muted-foreground); line-height: 1.6; }
.panel-body { display: grid; grid-template-columns: 230px 1fr; gap: 22px; align-items: start; }
.stats { display: flex; flex-direction: column; align-items: center; gap: 12px; }
.type-legend { list-style: none; margin: 0; padding: 0; width: 100%; display: flex; flex-direction: column; gap: 6px; }
.type-legend li { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.type-legend .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.type-legend .t-name { color: var(--foreground); }
.type-legend .t-val { margin-left: auto; color: var(--muted-foreground); font-variant-numeric: tabular-nums; }
.mem-column { min-width: 0; }
.mem-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.mem-head h4 { margin: 0; font-size: 12px; font-weight: 600; color: var(--muted-foreground); text-transform: uppercase; letter-spacing: 0.04em; }
.filter-chip { font-size: 10.5px; color: var(--primary); background: var(--primary-light); padding: 2px 8px; border-radius: 999px; }
.mem-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; max-height: 380px; overflow-y: auto; padding-right: 4px; }
.mem-item {
  background: var(--glass-surface-soft);
  border: 1px solid var(--glass-border);
  border-left: 2px solid var(--accent);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  transition: border-color var(--transition-fast), background var(--transition-fast);
}
.mem-item:hover { background: var(--glass-surface); border-color: color-mix(in oklch, var(--accent) 40%, var(--glass-border)); }
.mem-top { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 9px; }
.chip {
  padding: 1px 7px; border-radius: 999px; font-size: 10.5px; font-weight: 600;
  background: color-mix(in oklch, var(--accent) 14%, transparent); color: var(--accent);
}
.src { font-size: 11px; color: var(--muted-foreground); }
.reuse { font-size: 11px; color: var(--success); }
.reuse.strong { font-weight: 700; }
.mem-top time { margin-left: auto; font-size: 11px; color: var(--muted-foreground); }
.doc {
  margin: 6px 0 0; font-size: 12.5px; line-height: 1.55; color: var(--foreground);
  display: -webkit-box; -webkit-line-clamp: 3; line-clamp: 3; -webkit-box-orient: vertical;
  overflow: hidden; word-break: break-word;
}
.doc mark { background: var(--warning-light); color: inherit; border-radius: 3px; padding: 0 2px; }
.no-mem { font-size: 12.5px; color: var(--muted-foreground); margin: 0; }
.panel-desc { margin: 0; font-size: 11.5px; line-height: 1.6; color: var(--muted-foreground); border-top: 1px solid var(--glass-border); padding-top: 14px; }
@media (max-width: 720px) {
  .panel-body { grid-template-columns: 1fr; }
  .stats { flex-direction: row; justify-content: center; }
}
</style>
