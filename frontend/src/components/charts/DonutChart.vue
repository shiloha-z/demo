<script setup lang="ts">
import { computed } from 'vue'

interface Segment {
  label: string
  value: number
  color: string
}

const props = withDefaults(defineProps<{
  segments?: Segment[]
  centerTop?: string
  centerBottom?: string
  size?: number
  thickness?: number
}>(), {
  segments: () => [],
  centerTop: '',
  centerBottom: '',
  size: 120,
  thickness: 14,
})

const radius = computed(() => 50 - props.thickness / 2)
const circumference = computed(() => 2 * Math.PI * radius.value)
const total = computed(() => props.segments.reduce((s, x) => s + Math.max(0, x.value), 0))

// Each visible arc starts where the previous one ended (offset = -accumulated).
const arcs = computed(() => {
  if (total.value === 0) return []
  let acc = 0
  return props.segments
    .filter((s) => s.value > 0)
    .map((s) => {
      const len = (s.value / total.value) * circumference.value
      const arc = { len, offset: -acc, color: s.color }
      acc += len
      return arc
    })
})
</script>

<template>
  <div class="donut" :style="{ width: size + 'px', height: size + 'px' }">
    <svg viewBox="0 0 100 100" class="donut-svg">
      <circle
        class="donut-track"
        cx="50" cy="50" :r="radius"
        :stroke-width="thickness" fill="none"
      />
      <circle
        v-for="(a, i) in arcs" :key="i"
        class="donut-seg"
        cx="50" cy="50" :r="radius"
        :stroke="a.color" :stroke-width="thickness" fill="none"
        :stroke-dasharray="`${a.len} ${circumference}`"
        :stroke-dashoffset="a.offset"
        transform="rotate(-90 50 50)"
      />
    </svg>
    <div class="donut-center">
      <span v-if="centerTop" class="donut-top">{{ centerTop }}</span>
      <span v-if="centerBottom" class="donut-bottom">{{ centerBottom }}</span>
      <span v-if="!centerTop && !centerBottom" class="donut-empty">—</span>
    </div>
  </div>
</template>

<style scoped>
.donut {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.donut-svg { width: 100%; height: 100%; }
.donut-track { stroke: var(--surface-hover); }
.donut-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.donut-top { font-size: 18px; font-weight: 700; color: var(--foreground); line-height: 1.1; }
.donut-bottom { font-size: 11px; color: var(--muted-foreground); margin-top: 2px; }
.donut-empty { font-size: 16px; color: var(--muted-foreground); }
</style>
