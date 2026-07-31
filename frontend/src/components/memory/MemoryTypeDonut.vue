<script setup lang="ts">
import { computed } from 'vue'
import { typeColor, typeLabel } from '../../utils/memoryFormat'

const props = withDefaults(defineProps<{
  typeCounts?: Record<string, number> | null
  size?: number
}>(), { typeCounts: null, size: 104 })

const stroke = 11
const radius = computed(() => (props.size - stroke) / 2 - 2)
const center = computed(() => props.size / 2)
const circumference = computed(() => 2 * Math.PI * radius.value)

const total = computed(() => {
  if (!props.typeCounts) return 0
  return Object.values(props.typeCounts).reduce((sum, n) => sum + (Number.isFinite(+n) ? +n : 0), 0)
})
const hasData = computed(() => total.value > 0 && Number.isFinite(total.value))

interface Segment { type: string; count: number; color: string; label: string; dash: number; offset: number }
const segments = computed<Segment[]>(() => {
  if (!props.typeCounts || !hasData.value) return []
  const entries = Object.entries(props.typeCounts)
    .map(([type, count]) => ({ type, count: Number(count) || 0 }))
    .filter(e => e.count > 0)
    .sort((a, b) => b.count - a.count)
  let acc = 0
  return entries.map(e => {
    const dash = (e.count / total.value) * circumference.value
    const seg: Segment = {
      type: e.type, count: e.count, color: typeColor(e.type), label: typeLabel(e.type), dash, offset: -acc,
    }
    acc += dash
    return seg
  })
})
const legend = computed(() => segments.value.map(s => ({ label: s.label, count: s.count, color: s.color })))
</script>

<template>
  <div class="type-donut" :style="{ width: size + 'px' }">
    <svg :width="size" :height="size" :viewBox="`0 0 ${size} ${size}`" role="img" aria-label="记忆类型分布">
      <circle
        :cx="center" :cy="center" :r="radius"
        fill="none" stroke="var(--surface-hover)" :stroke-width="stroke"
        :stroke-dasharray="hasData ? '2 4' : ''"
      />
      <g :transform="`rotate(-90 ${center} ${center})`">
        <circle
          v-for="seg in segments" :key="seg.type"
          :cx="center" :cy="center" :r="radius"
          fill="none" :stroke="seg.color" :stroke-width="stroke"
          :stroke-dasharray="`${seg.dash} ${circumference - seg.dash}`"
          :stroke-dashoffset="seg.offset"
          stroke-linecap="butt"
        >
          <title>{{ seg.label }}：{{ seg.count }} 条</title>
        </circle>
      </g>
      <text :x="center" :y="center - 3" text-anchor="middle" class="donut-total">{{ hasData ? total : '—' }}</text>
      <text :x="center" :y="center + 12" text-anchor="middle" class="donut-label">条</text>
    </svg>
    <ul v-if="hasData" class="donut-legend">
      <li v-for="item in legend" :key="item.label">
        <span class="dot" :style="{ background: item.color }"></span>
        <span class="lg-label">{{ item.label }}</span>
        <span class="lg-count">{{ item.count }}</span>
      </li>
    </ul>
    <p v-else class="donut-empty">暂无类型数据</p>
  </div>
</template>

<style scoped>
.type-donut { display: flex; flex-direction: column; align-items: center; gap: 8px; }
.donut-total { fill: var(--foreground); font: 600 16px var(--font-sans); }
.donut-label { fill: var(--muted-foreground); font: 400 10px var(--font-sans); }
.donut-legend { list-style: none; margin: 0; padding: 0; width: 100%; display: flex; flex-direction: column; gap: 3px; }
.donut-legend li { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--muted-foreground); }
.donut-legend .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.lg-label { flex: 1; }
.lg-count { color: var(--foreground); font-weight: 600; }
.donut-empty { font-size: 11px; color: var(--muted-foreground); margin: 0; }
</style>
