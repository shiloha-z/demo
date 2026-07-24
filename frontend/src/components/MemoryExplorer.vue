<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import api from '../api'

type MemoryScope = 'global' | 'project' | 'agent'

interface MemoryEntry {
  id: string
  document: string
  metadata: Record<string, string | number | boolean>
  score?: number
}

const props = withDefaults(defineProps<{
  scope: MemoryScope
  scopeId?: number
  title?: string
  emptyHint?: string
  limit?: number
  maxHeight?: string
}>(), {
  scopeId: 0,
  title: '',
  emptyHint: 'Agent 会在任务执行和审查过程中沉淀可复用的经验。',
  limit: 50,
  maxHeight: '430px',
})

const memories = ref<MemoryEntry[]>([])
const loading = ref(false)
const available = ref(true)
const total = ref(0)
const scopeTotal = ref(0)
const typeCounts = ref<Record<string, number>>({})
const query = ref('')
const memoryType = ref('')
const errorMessage = ref('')
const expanded = ref(new Set<string>())

let debounceTimer: ReturnType<typeof setTimeout> | null = null
let requestVersion = 0

const typeOptions = computed(() => Object.entries(typeCounts.value))

const typeLabels: Record<string, string> = {
  review_result: '执行结果',
  review_decision: '审查反馈',
  error: '失败教训',
  lesson: '经验',
  pattern: '通用模式',
  progress: '执行进度',
  uncategorized: '未分类',
}

function typeLabel(type: string): string {
  return typeLabels[type] || type.replaceAll('_', ' ')
}

function sourceLabel(metadata: MemoryEntry['metadata']): string {
  const source = String(metadata.source || '')
  if (source === 'crewai_tool') return 'CrewAI'
  if (source) return source
  if (metadata.runner_type) return String(metadata.runner_type)
  return ''
}

function formatTime(raw: unknown): string {
  if (!raw) return ''
  const date = new Date(String(raw))
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function relevanceLabel(score?: number): string {
  if (score === undefined) return ''
  if (score >= 0.78) return '高度相关'
  if (score >= 0.62) return '较相关'
  return '相关'
}

function highlightedSegments(document: string): { text: string; match: boolean }[] {
  const keyword = query.value.trim()
  if (!keyword) return [{ text: document, match: false }]
  const tokens = [...new Set(keyword.split(/\s+/).filter(Boolean))]
  if (!tokens.length) return [{ text: document, match: false }]
  const escaped = tokens.map(token => token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const loweredTokens = new Set(tokens.map(token => token.toLocaleLowerCase()))
  const matcher = new RegExp(`(${escaped.join('|')})`, 'gi')
  return document
    .split(matcher)
    .filter(Boolean)
    .map(text => ({ text, match: loweredTokens.has(text.toLocaleLowerCase()) }))
}

function toggleExpanded(id: string) {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

async function loadMemories() {
  if (props.scope !== 'global' && props.scopeId <= 0) {
    memories.value = []
    total.value = 0
    scopeTotal.value = 0
    return
  }

  const version = ++requestVersion
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await api.get('/settings/memories', {
      params: {
        scope: props.scope,
        scope_id: props.scopeId,
        query: query.value.trim(),
        memory_type: memoryType.value,
        limit: props.limit,
        // Memory is live operational data. A cached 404/empty response from an
        // older backend must never hide records after a rolling restart.
        _request_time: Date.now(),
      },
      headers: {
        'Cache-Control': 'no-cache',
        Pragma: 'no-cache',
      },
      // A rolling deployment may briefly have the new frontend talking to
      // the previous backend. Handle that 404 locally without a warning toast.
      validateStatus: status => (status >= 200 && status < 300) || status === 404,
    })
    let data = response.data
    if (response.status === 404) {
      const legacyPath = {
        global: '/settings/global-memories',
        project: '/settings/project-memories',
        agent: '/settings/agent-memories',
      }[props.scope]
      const legacyParams: Record<string, string | number> = {
        limit: props.limit,
        _request_time: Date.now(),
      }
      if (props.scope === 'project') legacyParams.project_id = props.scopeId
      if (props.scope === 'agent') legacyParams.agent_id = props.scopeId
      const legacyResponse = await api.get(legacyPath, {
        params: legacyParams,
        headers: {
          'Cache-Control': 'no-cache',
          Pragma: 'no-cache',
        },
      })
      const legacyMemories: MemoryEntry[] = legacyResponse.data.memories || []
      const counts: Record<string, number> = {}
      for (const memory of legacyMemories) {
        const type = String(memory.metadata?.type || 'uncategorized')
        counts[type] = (counts[type] || 0) + 1
      }
      data = {
        available: true,
        memories: legacyMemories,
        total: legacyMemories.length,
        scope_total: legacyMemories.length,
        type_counts: counts,
      }
    }
    if (version !== requestVersion) return
    memories.value = data.memories || []
    total.value = data.total || 0
    scopeTotal.value = data.scope_total || 0
    typeCounts.value = data.type_counts || {}
    available.value = data.available !== false
  } catch (error: any) {
    if (version !== requestVersion) return
    errorMessage.value = error?.response?.data?.detail || '记忆加载失败，请稍后重试'
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

function scheduleLoad() {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(loadMemories, 260)
}

watch(
  [() => props.scope, () => props.scopeId],
  () => {
    query.value = ''
    memoryType.value = ''
    expanded.value = new Set()
    loadMemories()
  },
  { immediate: true },
)
watch([query, memoryType], scheduleLoad)

onUnmounted(() => {
  if (debounceTimer) clearTimeout(debounceTimer)
  requestVersion += 1
})

defineExpose({ refresh: loadMemories })
</script>

<template>
  <section class="memory-explorer">
    <header v-if="title" class="memory-header">
      <div>
        <h3>{{ title }}</h3>
        <p>{{ scopeTotal }} 条有效记忆<span v-if="memoryType || query"> · 当前显示 {{ total }} 条</span></p>
      </div>
      <button class="memory-refresh" :class="{ spinning: loading }" title="刷新记忆" @click="loadMemories">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
      </button>
    </header>

    <div class="memory-toolbar">
      <label class="memory-search">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        <input v-model="query" type="search" placeholder="搜索经验、错误或决策…" />
        <button v-if="query" aria-label="清除搜索" @click="query = ''">×</button>
      </label>
      <select v-model="memoryType" class="memory-type-filter" aria-label="按记忆类型筛选">
        <option value="">全部类型</option>
        <option v-for="[type, count] in typeOptions" :key="type" :value="type">
          {{ typeLabel(type) }} ({{ count }})
        </option>
      </select>
      <button v-if="!title" class="memory-refresh" :class="{ spinning: loading }" title="刷新记忆" @click="loadMemories">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
      </button>
    </div>

    <div v-if="!available" class="memory-state memory-state--warning">
      记忆后端当前不可用。任务仍可继续执行，恢复后会自动重新启用。
    </div>
    <div v-else-if="errorMessage && memories.length === 0" class="memory-state memory-state--error">
      <span>{{ errorMessage }}</span>
      <button @click="loadMemories">重试</button>
    </div>
    <div v-else-if="loading && memories.length === 0" class="memory-skeleton" aria-label="正在加载记忆">
      <div v-for="index in 3" :key="index" class="memory-skeleton-item">
        <span></span><span></span><span></span>
      </div>
    </div>
    <div v-else-if="memories.length === 0" class="memory-state">
      <strong>{{ query || memoryType ? '没有匹配的记忆' : '暂无记忆' }}</strong>
      <span>{{ query || memoryType ? '尝试更换关键词或清除筛选条件。' : emptyHint }}</span>
    </div>
    <div v-else class="memory-list" :style="{ maxHeight }" :aria-busy="loading">
      <div v-if="errorMessage" class="memory-inline-error">
        <span>刷新失败，正在保留上次结果</span>
        <button @click="loadMemories">重试</button>
      </div>
      <article v-for="memory in memories" :key="memory.id" class="memory-item">
        <div
          class="memory-document"
          :class="{ collapsed: memory.document.length > 220 && !expanded.has(memory.id) }"
        >
          <template v-for="(segment, index) in highlightedSegments(memory.document)" :key="index">
            <mark v-if="segment.match">{{ segment.text }}</mark>
            <template v-else>{{ segment.text }}</template>
          </template>
        </div>
        <button
          v-if="memory.document.length > 220"
          class="memory-expand"
          @click="toggleExpanded(memory.id)"
        >
          {{ expanded.has(memory.id) ? '收起' : '展开全文' }}
        </button>
        <footer class="memory-meta">
          <span class="memory-type">{{ typeLabel(String(memory.metadata.type || 'uncategorized')) }}</span>
          <span v-if="memory.score !== undefined" class="memory-relevance">{{ relevanceLabel(memory.score) }}</span>
          <span v-if="sourceLabel(memory.metadata)">{{ sourceLabel(memory.metadata) }}</span>
          <span v-if="memory.metadata.task_id">任务 #{{ memory.metadata.task_id }}</span>
          <span v-if="Number(memory.metadata.occurrences || 1) > 1">
            重复命中 {{ memory.metadata.occurrences }} 次
          </span>
          <time v-if="memory.metadata.timestamp">{{ formatTime(memory.metadata.timestamp) }}</time>
        </footer>
      </article>
      <div v-if="loading" class="memory-updating">正在更新结果…</div>
    </div>
  </section>
</template>

<style scoped>
.memory-explorer {
  min-width: 0;
}
.memory-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--surface-border);
  background: var(--surface-hover);
}
.memory-header h3 {
  margin: 0;
  color: var(--foreground);
  font-size: 14px;
  font-weight: 650;
}
.memory-header p {
  margin: 2px 0 0;
  color: var(--muted-foreground);
  font-size: 11px;
}
.memory-toolbar {
  display: flex;
  gap: 8px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--surface-border);
}
.memory-search {
  min-width: 0;
  flex: 1;
  height: 34px;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 0 10px;
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-md);
  background: var(--page-canvas);
  color: var(--muted-foreground);
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}
.memory-search:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px var(--primary-light);
}
.memory-search input {
  min-width: 0;
  flex: 1;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--foreground);
  font: inherit;
  font-size: 12.5px;
}
.memory-search input::-webkit-search-cancel-button { display: none; }
.memory-search button {
  border: 0;
  background: transparent;
  color: var(--muted-foreground);
  cursor: pointer;
  font-size: 17px;
}
.memory-type-filter {
  width: 132px;
  height: 34px;
  padding: 0 9px;
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-md);
  outline: 0;
  background: var(--page-canvas);
  color: var(--foreground);
  font: inherit;
  font-size: 12px;
}
.memory-refresh {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-md);
  background: var(--surface);
  color: var(--muted-foreground);
  cursor: pointer;
}
.memory-refresh:hover { color: var(--primary); border-color: var(--primary); }
.memory-refresh.spinning svg { animation: memory-spin 0.8s linear infinite; }
.memory-state {
  min-height: 130px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 24px;
  text-align: center;
  color: var(--muted-foreground);
  font-size: 12px;
}
.memory-state strong { color: var(--foreground); font-size: 13px; }
.memory-state--warning { color: var(--warning); background: var(--warning-light); }
.memory-state--error { color: var(--danger); }
.memory-state button {
  border: 0;
  background: transparent;
  color: var(--primary);
  cursor: pointer;
}
.memory-list {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
  padding: 12px 14px 14px;
}
.memory-item {
  padding: 11px 12px;
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-md);
  background: var(--page-canvas);
  transition: border-color var(--transition-fast), background-color var(--transition-fast);
}
.memory-item:hover {
  border-color: color-mix(in oklch, var(--primary) 28%, var(--surface-border));
  background: var(--surface);
}
.memory-document {
  color: var(--foreground);
  font-size: 12.5px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.memory-document.collapsed {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 4;
}
.memory-document mark {
  padding: 0 2px;
  border-radius: 3px;
  background: var(--warning-light);
  color: inherit;
}
.memory-expand {
  margin-top: 4px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--primary);
  cursor: pointer;
  font-size: 11px;
}
.memory-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px 9px;
  margin-top: 7px;
  color: var(--muted-foreground);
  font-size: 10.5px;
}
.memory-meta time { margin-left: auto; }
.memory-type,
.memory-relevance {
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--primary-light);
  color: var(--primary);
  font-size: 10px;
  font-weight: 600;
}
.memory-relevance {
  background: var(--success-light);
  color: var(--success);
}
.memory-updating {
  position: sticky;
  bottom: 0;
  align-self: center;
  padding: 3px 9px;
  border-radius: 999px;
  background: var(--foreground);
  color: var(--surface);
  font-size: 10px;
}
.memory-inline-error {
  position: sticky;
  top: 0;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 7px 10px;
  border: 1px solid color-mix(in oklch, var(--danger) 24%, var(--surface-border));
  border-radius: var(--radius-md);
  background: var(--danger-light);
  color: var(--danger);
  font-size: 11px;
}
.memory-inline-error button {
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font-weight: 600;
}
.memory-skeleton {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px 14px;
}
.memory-skeleton-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-md);
}
.memory-skeleton-item span {
  height: 9px;
  border-radius: 5px;
  background: linear-gradient(100deg, var(--surface-hover) 30%, var(--surface-selected) 50%, var(--surface-hover) 70%);
  background-size: 200% 100%;
  animation: memory-shimmer 1.2s ease-in-out infinite;
}
.memory-skeleton-item span:nth-child(2) { width: 86%; }
.memory-skeleton-item span:nth-child(3) { width: 42%; }
@keyframes memory-spin { to { transform: rotate(360deg); } }
@keyframes memory-shimmer {
  from { background-position: 100% 0; }
  to { background-position: -100% 0; }
}
@media (max-width: 560px) {
  .memory-toolbar { flex-wrap: wrap; }
  .memory-search { flex-basis: calc(100% - 42px); }
  .memory-type-filter { flex: 1; }
}
</style>
