<script setup lang="ts">
import { computed, ref, watch } from 'vue'

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
  size: 130,
  thickness: 13,
})

// Unique filter id per instance to avoid conflicts with multiple donuts on one page
let _donutUid = 0
const filterId = `donut-shadow-${++_donutUid}`

const radius = computed(() => 50 - props.thickness / 2)
const circumference = computed(() => 2 * Math.PI * radius.value)
const total = computed(() => props.segments.reduce((s, x) => s + Math.max(0, x.value), 0))

// Animate in — start with 0 then grow
const animated = ref(false)
watch(() => props.segments, () => {
  animated.value = false
  requestAnimationFrame(() => { animated.value = true })
}, { immediate: true, deep: true })

const arcs = computed(() => {
  if (total.value === 0) return []
  let acc = 0
  const gap = 1.2 // small gap between segments (degrees worth of circumference)
  const visibleSegments = props.segments.filter((s) => s.value > 0)
  return visibleSegments
    .map((s) => {
      const rawLen = (s.value / total.value) * circumference.value
      // Only apply gap when there are 2+ segments
      const len = visibleSegments.length > 1 ? Math.max(2, rawLen - gap) : rawLen
      const arc = { len: animated.value ? len : 0, offset: -acc, color: s.color }
      acc += rawLen
      return arc
    })
})
</script>

<template>
  <div class="donut" :style="{ width: size + 'px', height: size + 'px' }">
    <!-- Glow ring behind the donut -->
    <svg viewBox="0 0 100 100" class="donut-glow" aria-hidden="true">
      <circle cx="50" cy="50" :r="radius" :stroke-width="thickness + 2" fill="none"
        stroke="var(--primary-light)" opacity="0.3" />
    </svg>
    <!-- Main donut -->
    <svg viewBox="0 0 100 100" class="donut-svg">
      <defs>
        <filter :id="filterId">
          <feDropShadow dx="0" dy="1" stdDeviation="2" flood-color="var(--primary)" flood-opacity="0.12" />
        </filter>
      </defs>
      <!-- Track ring -->
      <circle
        class="donut-track"
        cx="50" cy="50" :r="radius"
        :stroke-width="thickness" fill="none"
      />
      <!-- Segments -->
      <circle
        v-for="(a, i) in arcs" :key="i"
        class="donut-seg"
        cx="50" cy="50" :r="radius"
        :stroke="a.color" :stroke-width="thickness" fill="none"
        stroke-linecap="round"
        :stroke-dasharray="`${a.len} ${circumference}`"
        :stroke-dashoffset="a.offset"
        transform="rotate(-90 50 50)"
        :style="{ transition: 'stroke-dasharray 0.65s cubic-bezier(0.16, 1, 0.3, 1)' }"
        :filter="`url(#${filterId})`"
      />
      <!-- Center overlay circle for depth -->
      <circle cx="50" cy="50" :r="radius - thickness / 2 - 2" fill="var(--surface)" opacity="0" />
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
  flex-shrink: 0;
}
.donut-svg,
.donut-glow {
  width: 100%; height: 100%;
  position: absolute; inset: 0;
}
.donut-glow { z-index: 0; }
.donut-svg { z-index: 1; }
.donut-track { stroke: var(--surface-hover); }
.donut-center {
  position: relative; z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  line-height: 1.1;
}
.donut-top { font-size: 20px; font-weight: 750; color: var(--foreground); letter-spacing: -0.3px; }
.donut-bottom { font-size: 11px; color: var(--muted-foreground); margin-top: 3px; font-weight: 500; }
.donut-empty { font-size: 16px; color: var(--muted-foreground); }
</style>
