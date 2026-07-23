<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { useLoadingStore } from '../stores/loading'

const loadingStore = useLoadingStore()
const { visible, progress } = storeToRefs(loadingStore)
</script>

<template>
  <Transition name="global-loading">
    <div
      v-if="visible"
      class="global-loading-bar"
      role="progressbar"
      aria-label="正在加载"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-valuenow="Math.round(progress)"
    >
      <span
        class="global-loading-bar__value"
        :style="{ transform: `scaleX(${progress / 100})` }"
      />
      <span class="global-loading-bar__glow" />
    </div>
  </Transition>
</template>

<style scoped>
.global-loading-bar {
  position: fixed;
  z-index: 10000;
  top: 0;
  right: 0;
  left: 0;
  height: 3px;
  overflow: hidden;
  pointer-events: none;
}

.global-loading-bar__value {
  position: absolute;
  inset: 0;
  transform-origin: left center;
  background: var(--primary-gradient, linear-gradient(90deg, #6575ff, #8b6cff));
  box-shadow: 0 1px 8px var(--primary-glow, rgba(84, 102, 255, 0.3));
  transition: transform 0.22s ease-out;
  will-change: transform;
}

.global-loading-bar__glow {
  position: absolute;
  top: 0;
  right: 0;
  width: 90px;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.9));
  filter: blur(1px);
  animation: loading-shimmer 1.1s ease-in-out infinite;
}

.global-loading-enter-active,
.global-loading-leave-active {
  transition: opacity 0.16s ease;
}

.global-loading-enter-from,
.global-loading-leave-to {
  opacity: 0;
}

@keyframes loading-shimmer {
  from { transform: translateX(-45vw); opacity: 0.35; }
  to { transform: translateX(90px); opacity: 0.9; }
}

@media (prefers-reduced-motion: reduce) {
  .global-loading-bar__value { transition-duration: 0.01ms; }
  .global-loading-bar__glow { animation: none; }
}
</style>
