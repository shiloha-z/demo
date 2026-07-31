<script setup lang="ts">
import { computed } from 'vue'

export interface DiagramLayer {
  key: string
  label: string
  description: string
  count: number
  isEphemeral: boolean
  colorVar: string
}

export interface OptionItem {
  value: number
  label: string
}

const props = withDefaults(defineProps<{
  layers: DiagramLayer[]
  selectedKey: string
  showSelectors?: boolean
  projectOptions?: OptionItem[]
  agentOptions?: OptionItem[]
  projectId?: number
  agentId?: number
  projectLoading?: boolean
}>(), {
  showSelectors: false,
  projectOptions: () => [],
  agentOptions: () => [],
  projectId: 0,
  agentId: 0,
  projectLoading: false,
})

const emit = defineEmits<{
  (e: 'select', key: string): void
  (e: 'project-change', id: number): void
  (e: 'agent-change', id: number): void
}>()

function onSelect(key: string) {
  emit('select', key)
}
function onProjectChange(val: any) {
  emit('project-change', Number(val))
}
function onAgentChange(val: any) {
  emit('agent-change', val == null ? 0 : Number(val))
}
const hasOptions = computed(() => props.showSelectors)
</script>

<template>
  <div class="layer-list">
    <template v-for="(layer, i) in layers" :key="layer.key">
      <div
        class="band"
        :class="{ selected: selectedKey === layer.key, ephemeral: layer.isEphemeral }"
        :style="{ '--accent': layer.colorVar }"
        @click="onSelect(layer.key)"
      >
        <span class="badge">{{ i + 1 }}</span>
        <div class="band-text">
          <span class="band-label">{{ layer.label }}</span>
          <span class="band-sub">
            {{ layer.isEphemeral
              ? '临时 · 合并即清理'
              : (Number.isFinite(layer.count) ? layer.count + ' 条记忆 · 点击查看' : '—') }}
          </span>
        </div>

        <div class="band-action" @click.stop>
          <t-select
            v-if="layer.key === 'project' && hasOptions"
            :value="projectId"
            :options="projectOptions"
            placeholder="选择项目"
            size="small"
            @change="onProjectChange"
          />
          <t-select
            v-else-if="layer.key === 'agent' && hasOptions"
            :value="agentId"
            :options="agentOptions"
            placeholder="全部 Agent"
            size="small"
            clearable
            :loading="projectLoading"
            @change="onAgentChange"
          />
          <span v-else-if="!layer.isEphemeral" class="count-pill">{{ layer.count }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.layer-list { display: flex; flex-direction: column; gap: 10px; }
.band {
  display: flex; align-items: center; gap: 12px;
  padding: 13px 15px; border-radius: var(--radius-lg);
  border: 1px solid var(--surface-border);
  background: var(--card-bg);
  cursor: pointer; box-shadow: var(--card-shadow);
  transition: border-color var(--transition-fast), background var(--transition-fast), transform var(--motion-base) var(--motion-ease-spring), box-shadow var(--transition-fast);
}
.band:hover {
  transform: translateY(-1px);
  border-color: color-mix(in oklch, var(--accent) 45%, transparent);
  background: color-mix(in oklch, var(--accent) 4%, var(--card-bg));
}
.band.selected {
  border-color: var(--accent);
  background: color-mix(in oklch, var(--accent) 7%, var(--card-bg));
  box-shadow: 0 6px 16px color-mix(in oklch, var(--accent) 16%, transparent);
}
.band.ephemeral { border-style: dashed; border-color: color-mix(in oklch, var(--accent) 32%, var(--surface-border)); }
.badge {
  width: 30px; height: 30px; border-radius: 50%; flex-shrink: 0;
  background: var(--accent); color: #fff;
  display: grid; place-items: center; font-weight: 700; font-size: 14px;
}
.band-text { display: flex; flex-direction: column; min-width: 0; margin-right: auto; }
.band-label { font-weight: 600; font-size: 14px; color: var(--foreground); }
.band-sub { font-size: 11px; color: var(--muted-foreground); margin-top: 2px; }
.band-action { flex-shrink: 0; width: 168px; }
.count-pill {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 52px; height: 30px; padding: 0 12px; border-radius: 9px;
  background: var(--card-bg);
  border: 1px solid color-mix(in oklch, var(--accent) 38%, transparent);
  color: var(--accent); font-weight: 700; font-size: 14px; font-variant-numeric: tabular-nums;
  float: right;
}

@media (max-width: 480px) {
  .band-action { width: 132px; }
}
</style>
