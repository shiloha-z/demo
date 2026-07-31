<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import api from '../../api'
import { useProjectStore } from '../../stores/project'
import MemoryLayerDiagram, { type DiagramLayer } from './MemoryLayerDiagram.vue'
import MemoryLayerCard, { type CardLayer } from './MemoryLayerCard.vue'
import type { MemoryEntry, MemoryScope } from '../../utils/memoryFormat'

const projectStore = useProjectStore()

interface LayerData {
  available: boolean
  memories: MemoryEntry[]
  total: number
  scopeTotal: number
  typeCounts: Record<string, number>
}

const query = ref('')
const loading = ref(false)
const errorMessage = ref('')
const anyDegraded = ref(false)
const globalData = ref<LayerData | null>(null)
const projectData = ref<LayerData | null>(null)
const agentData = ref<LayerData | null>(null)

const selectedProjectId = ref<number>(0)
const selectedAgentId = ref<number>(0)
const agents = ref<{ id: number; name: string }[]>([])
const agentsLoading = ref(false)

let debounceTimer: ReturnType<typeof setTimeout> | null = null
let requestVersion = 0

async function loadLayer(scope: MemoryScope, scopeId: number): Promise<LayerData> {
  const response = await api.get('/settings/memories', {
    params: { scope, scope_id: scopeId, query: query.value.trim(), limit: 60, _request_time: Date.now() },
    headers: { 'Cache-Control': 'no-cache', Pragma: 'no-cache' },
    validateStatus: (s: number) => (s >= 200 && s < 300) || s === 404,
  })

  let data = response.data
  if (response.status === 404) {
    const legacyPath: Record<MemoryScope, string> = {
      global: '/settings/global-memories',
      project: '/settings/project-memories',
      agent: '/settings/agent-memories',
    }
    const legacyUrl = legacyPath[scope]
    const legacyParams: Record<string, string | number> = { limit: 60, _request_time: Date.now() }
    if (scope === 'project') legacyParams.project_id = scopeId
    if (scope === 'agent') legacyParams.agent_id = scopeId
    const legacy = await api.get(legacyUrl, {
      params: legacyParams,
      headers: { 'Cache-Control': 'no-cache', Pragma: 'no-cache' },
    })
    const mems: MemoryEntry[] = legacy.data.memories || []
    const counts: Record<string, number> = {}
    for (const m of mems) {
      const t = String(m.metadata?.type || 'uncategorized')
      counts[t] = (counts[t] || 0) + 1
    }
    data = { available: true, memories: mems, total: mems.length, scope_total: mems.length, type_counts: counts }
  }

  return {
    available: data.available !== false,
    memories: data.memories || [],
    total: data.total || 0,
    scopeTotal: data.scope_total || 0,
    typeCounts: data.type_counts || {},
  }
}

const projectActive = computed(() => Number(selectedProjectId.value) > 0)
const agentActive = computed(() => Number(selectedAgentId.value) > 0)

async function loadAgents() {
  agentsLoading.value = true
  try {
    const { data } = await api.get('/agents', { params: { page: 1, page_size: 100 } })
    agents.value = (data.items || []).map((a: { id: number; name: string }) => ({ id: Number(a.id), name: a.name }))
  } catch {
    agents.value = []
  } finally {
    agentsLoading.value = false
  }
}

async function loadAll() {
  const version = ++requestVersion
  loading.value = true
  errorMessage.value = ''
  anyDegraded.value = false
  if (!projectActive.value) projectData.value = null
  if (!agentActive.value) agentData.value = null

  const tasks: Promise<{ scope: MemoryScope; data: LayerData }>[] = []
  tasks.push(loadLayer('global', 0).then(d => ({ scope: 'global' as MemoryScope, data: d })))
  if (projectActive.value) {
    tasks.push(loadLayer('project', Number(selectedProjectId.value)).then(d => ({ scope: 'project' as MemoryScope, data: d })))
  }
  if (agentActive.value) {
    tasks.push(loadLayer('agent', Number(selectedAgentId.value)).then(d => ({ scope: 'agent' as MemoryScope, data: d })))
  }

  try {
    const results = await Promise.allSettled(tasks)
    if (version !== requestVersion) return
    for (const r of results) {
      if (r.status === 'fulfilled') {
        if (r.value.scope === 'global') globalData.value = r.value.data
        else if (r.value.scope === 'project') projectData.value = r.value.data
        else agentData.value = r.value.data
        if (!r.value.data.available) anyDegraded.value = true
      } else {
        anyDegraded.value = true
        errorMessage.value = '部分记忆层加载失败，已保留可用数据。'
      }
    }
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

function scheduleLoad() {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(loadAll, 260)
}

function onProjectSelected(id: number) {
  selectedProjectId.value = id
  selectedAgentId.value = 0
  if (id > 0) loadAgents()
}
function onAgentSelected(id: number) {
  selectedAgentId.value = id
}

const projectOptions = computed(() =>
  projectStore.switchableProjects.map(p => ({ value: Number(p.id), label: p.name })),
)
const agentOptions = computed(() => agents.value.map(a => ({ value: a.id, label: a.name })))

const globalLayer = computed<CardLayer>(() => ({
  key: 'global', label: '全局层', description: '跨项目可复用的通用模式与经验，是沉淀价值最高的记忆。',
  count: globalData.value?.scopeTotal ?? 0, isEphemeral: false, available: globalData.value?.available ?? true,
  colorVar: 'var(--success)', typeCounts: globalData.value?.typeCounts ?? null, recent: globalData.value?.memories ?? [],
}))
const projectLayer = computed<CardLayer>(() => ({
  key: 'project', label: '项目层', description: '当前项目的设计决策、审查反馈与上下文积累。',
  count: projectData.value?.scopeTotal ?? 0, isEphemeral: false, available: projectData.value?.available ?? true,
  colorVar: 'var(--warning)', typeCounts: projectData.value?.typeCounts ?? null, recent: projectData.value?.memories ?? [],
}))
const agentLayer = computed<CardLayer>(() => ({
  key: 'agent', label: 'Agent 层', description: '单个 Agent 在长期任务中积累的稳定习惯与偏好。',
  count: agentData.value?.scopeTotal ?? 0, isEphemeral: false, available: agentData.value?.available ?? true,
  colorVar: 'var(--primary)', typeCounts: agentData.value?.typeCounts ?? null, recent: agentData.value?.memories ?? [],
}))
const taskLayer = computed<CardLayer>(() => ({
  key: 'task', label: '任务层', description: '任务运行期间由执行与审查临时沉淀，任务合并后自动清理，不长期留存。',
  count: 0, isEphemeral: true, available: true, colorVar: 'var(--info)', typeCounts: null, recent: [],
}))

const diagramLayers = computed<DiagramLayer[]>(() => [
  globalLayer.value, projectLayer.value, agentLayer.value, taskLayer.value,
].map(l => ({
  key: l.key, label: l.label, description: l.description, count: l.count, isEphemeral: l.isEphemeral, colorVar: l.colorVar,
})))

const totalMemories = computed(
  () => (globalData.value?.scopeTotal ?? 0) + (projectData.value?.scopeTotal ?? 0) + (agentData.value?.scopeTotal ?? 0),
)
const selectedKey = ref<string>('global')
const allLayers = computed(() => [globalLayer.value, projectLayer.value, agentLayer.value, taskLayer.value])
const selectedLayer = computed(() => allLayers.value.find((l) => l.key === selectedKey.value) || globalLayer.value)

watch([selectedProjectId, selectedAgentId], () => { query.value = ''; loadAll() })
watch(query, scheduleLoad)

onMounted(async () => {
  try {
    if (projectStore.switchableProjects.length === 0) await projectStore.fetchSwitchableProjects()
  } catch {
    /* 忽略：由选择器兜底 */
  }
  const cur = projectStore.currentProject
  if (cur && Number(cur.id) > 0) {
    selectedProjectId.value = cur.id
    await loadAgents()
  }
  loadAll()
})

onUnmounted(() => {
  if (debounceTimer) clearTimeout(debounceTimer)
  requestVersion += 1
})
</script>

<template>
  <div class="memory-atlas">
    <div class="atlas-toolbar">
      <label class="search">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <input v-model="query" type="search" placeholder="跨四层搜索经验、错误或决策…" />
        <button v-if="query" type="button" class="clear" aria-label="清空" @click="query = ''">×</button>
      </label>

      <div class="summary">
        <span class="sum-num">{{ totalMemories }}</span>
        <span class="sum-label">条有效记忆（全局 + 项目 + Agent）</span>
      </div>

      <button type="button" class="refresh" :class="{ spinning: loading }" aria-label="刷新" @click="loadAll">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 3v6h-6" />
        </svg>
      </button>
    </div>

    <p v-if="anyDegraded" class="atlas-degraded">
      记忆后端（ChromaDB）部分不可用，以下为其余层级的有效数据。
    </p>
    <p v-else-if="errorMessage" class="atlas-degraded">{{ errorMessage }}</p>

    <section class="atlas-grid">
      <div class="glass-card diagram-col">
        <MemoryLayerDiagram
          :layers="diagramLayers"
          :selected-key="selectedKey"
          :show-selectors="true"
          :project-options="projectOptions"
          :agent-options="agentOptions"
          :project-id="selectedProjectId"
          :agent-id="selectedAgentId"
          :project-loading="agentsLoading"
          @select="selectedKey = $event"
          @project-change="onProjectSelected"
          @agent-change="onAgentSelected"
        />
        <p class="diagram-caption">
          四层沉淀流向（自下而上）：任务原始经验 → Agent 习惯 → 项目决策 → 全局通用模式。点击任一层查看详情。
        </p>
      </div>
      <div class="glass-card panel-col">
        <MemoryLayerCard :layer="selectedLayer" :query="query" />
      </div>
    </section>
  </div>
</template>

<style scoped>
.memory-atlas { display: flex; flex-direction: column; gap: 18px; }
.atlas-toolbar { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.search {
  flex: 1; min-width: 240px; height: 34px; display: flex; align-items: center; gap: 8px;
  padding: 0 12px; border: 1px solid var(--surface-border); border-radius: var(--radius-md);
  background: var(--glass-surface-soft); color: var(--muted-foreground);
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast), background var(--transition-fast);
}
.search:focus-within { border-color: var(--primary); background: var(--glass-surface-strong); box-shadow: 0 0 0 3px var(--ring); }
.search input { flex: 1; border: 0; outline: 0; background: transparent; color: var(--foreground); font: inherit; font-size: 13px; }
.search input::-webkit-search-cancel-button { display: none; }
.search .clear { border: 0; background: transparent; color: var(--muted-foreground); cursor: pointer; font-size: 18px; line-height: 1; }
.summary { display: flex; align-items: baseline; gap: 6px; }
.sum-num { font-size: 22px; font-weight: 700; color: var(--primary); font-variant-numeric: tabular-nums; }
.sum-label { font-size: 11.5px; color: var(--muted-foreground); }
.refresh {
  width: 34px; height: 34px; display: inline-flex; align-items: center; justify-content: center;
  border: 1px solid var(--glass-border); border-radius: var(--radius-md);
  background: var(--glass-surface-soft); color: var(--muted-foreground); cursor: pointer; flex-shrink: 0;
  transition: color var(--transition-fast), border-color var(--transition-fast), background var(--transition-fast);
}
.refresh:hover { color: var(--primary); border-color: var(--primary); }
.refresh.spinning svg { animation: mem-spin 0.8s linear infinite; }
.atlas-degraded { margin: 0; font-size: 12px; color: var(--warning); background: var(--warning-light); border-radius: var(--radius-md); padding: 10px 14px; }
.glass-card {
  background: var(--glass-surface-strong);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-glass), var(--glass-highlight);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  padding: 20px;
}
.atlas-grid { display: grid; grid-template-columns: 340px 1fr; gap: 16px; align-items: start; }
.diagram-col { display: flex; flex-direction: column; gap: 14px; }
.diagram-caption { text-align: center; margin: 0; font-size: 12px; color: var(--muted-foreground); line-height: 1.6; }
.panel-col { min-width: 0; }
@media (max-width: 920px) {
  .atlas-grid { grid-template-columns: 1fr; }
  .diagram-col { max-width: 460px; margin: 0 auto; width: 100%; }
}
@keyframes mem-spin { to { transform: rotate(360deg); } }
</style>
