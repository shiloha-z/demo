<script setup lang="ts">
import { computed } from 'vue'

interface BarItem {
  label: string
  value: number
  color?: string
}

const props = withDefaults(defineProps<{
  items?: BarItem[]
  height?: number
  valueSuffix?: string
  barColor?: string
  dense?: boolean
}>(), {
  items: () => [],
  height: 120,
  valueSuffix: '',
  barColor: 'var(--primary)',
  dense: false,
})

const max = computed(() => Math.max(1, ...props.items.map((i) => i.value)))
// When dense (many bars), only show ~8 evenly spaced labels to avoid clutter.
const labelStep = computed(() => Math.max(1, Math.ceil(props.items.length / 8)))
const labelVisible = (i: number) => !props.dense || i % labelStep.value === 0
const pct = (v: number) => (max.value > 0 ? (v / max.value) * 100 : 0)
</script>

<template>
  <div class="bar-chart" :style="{ height: height + 'px' }">
    <div v-for="(it, i) in items" :key="i" class="bar-col">
      <span class="bar-value" :class="{ hidden: dense }">{{ it.value }}{{ valueSuffix }}</span>
      <div class="bar-track">
        <div
          class="bar-fill"
          :style="{ height: pct(it.value) + '%', background: it.color || barColor }"
        />
      </div>
      <span class="bar-label" :class="{ hidden: !labelVisible(i) }">{{ it.label }}</span>
    </div>
  </div>
</template>

<style scoped>
.bar-chart {
  display: flex;
  align-items: stretch;
  gap: 4px;
  width: 100%;
  padding-top: 2px;
  box-sizing: border-box;
}
.bar-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.bar-value {
  font-size: 10px;
  color: var(--muted-foreground);
  margin-bottom: 2px;
  white-space: nowrap;
}
.bar-track {
  flex: 1;
  width: 60%;
  min-width: 6px;
  display: flex;
  align-items: flex-end;
  background: var(--surface-hover);
  border-radius: 3px;
  overflow: hidden;
}
.bar-fill {
  width: 100%;
  border-radius: 3px 3px 0 0;
  min-height: 2px;
  transition: height var(--transition-base);
}
.bar-label {
  font-size: 10px;
  color: var(--muted-foreground);
  margin-top: 3px;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.bar-label.hidden { visibility: hidden; }
.bar-value.hidden { display: none; }
</style>
