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
  height: 130,
  valueSuffix: '',
  barColor: 'var(--primary)',
  dense: false,
})

const max = computed(() => Math.max(1, ...props.items.map((i) => i.value)))
const labelStep = computed(() => Math.max(1, Math.ceil(props.items.length / 8)))
const labelVisible = (i: number) => !props.dense || i % labelStep.value === 0
const pct = (v: number) => (max.value > 0 ? (v / max.value) * 100 : 0)
</script>

<template>
  <div class="bar-chart" :style="{ height: height + 'px' }">
    <!-- Grid lines -->
    <div class="bar-grid">
      <div class="bar-grid-line" v-for="n in 3" :key="n"
        :style="{ bottom: (n / 4) * 100 + '%' }" />
    </div>
    <div v-for="(it, i) in items" :key="i" class="bar-col">
      <span class="bar-value" :class="{ hidden: dense }">{{ it.value }}{{ valueSuffix }}</span>
      <div class="bar-track">
        <div
          class="bar-fill"
          :style="{
            height: pct(it.value) + '%',
            background: it.color
              ? `linear-gradient(180deg, ${it.color}, color-mix(in oklch, ${it.color} 70%, transparent))`
              : `linear-gradient(180deg, var(--primary), var(--primary-hover))`,
          }"
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
  gap: 5px;
  width: 100%;
  padding-top: 4px;
  box-sizing: border-box;
  position: relative;
}
.bar-grid {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 0;
}
.bar-grid-line {
  position: absolute;
  left: 0; right: 0;
  height: 1px;
  background: var(--surface-border);
  opacity: 0.5;
}
.bar-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  z-index: 1;
}
.bar-value {
  font-size: 10px;
  font-weight: 600;
  color: var(--muted-foreground);
  margin-bottom: 3px;
  white-space: nowrap;
}
.bar-track {
  flex: 1;
  width: 64%;
  min-width: 8px;
  display: flex;
  align-items: flex-end;
  background: var(--surface-hover);
  border-radius: 4px;
  overflow: hidden;
}
.bar-fill {
  width: 100%;
  border-radius: 4px 4px 0 0;
  min-height: 2px;
  transition: height 0.5s cubic-bezier(0.16, 1, 0.3, 1);
}
.bar-label {
  font-size: 9.5px;
  color: var(--muted-foreground);
  margin-top: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
.bar-label.hidden { visibility: hidden; }
.bar-value.hidden { display: none; }
</style>
