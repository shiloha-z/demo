<script setup lang="ts">
withDefaults(defineProps<{
  title?: string
  hint?: string
}>(), {
  title: '',
  hint: '',
})
</script>

<template>
  <div class="viz-card">
    <div class="viz-card-head">
      <h4 class="viz-card-title">{{ title }}</h4>
      <span v-if="hint" class="viz-hint" tabindex="0">?
        <span class="viz-hint-pop">{{ hint }}</span>
      </span>
    </div>
    <div class="viz-card-body">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.viz-card {
  background: var(--glass-surface-strong);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  padding: 14px 16px;
  box-shadow: var(--shadow-glass), var(--glass-highlight);
  backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  display: flex;
  flex-direction: column;
  min-height: 0;
  transition: border-color var(--transition-base), box-shadow var(--transition-base);
}
.viz-card:hover { border-color: color-mix(in oklch, var(--primary) 35%, var(--glass-border)); }
.viz-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.viz-card-title { margin: 0; font-size: 13px; font-weight: 600; color: var(--foreground); letter-spacing: -0.2px; }
.viz-hint {
  position: relative;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--surface-hover);
  color: var(--muted-foreground);
  font-size: 11px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: help;
  user-select: none;
  flex-shrink: 0;
  border: 1px solid var(--surface-border);
  transition: background var(--transition-fast), color var(--transition-fast);
}
.viz-hint:hover { background: var(--primary-light); color: var(--primary); }
.viz-hint-pop {
  position: absolute;
  bottom: calc(100% + 6px);
  right: 0;
  width: 210px;
  background: var(--foreground);
  color: var(--surface);
  font-size: 11px;
  line-height: 1.5;
  font-weight: 400;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-floating);
  opacity: 0;
  visibility: hidden;
  transform: translateY(4px);
  transition: opacity var(--transition-fast), transform var(--transition-fast), visibility var(--transition-fast);
  z-index: 20;
  text-align: left;
  white-space: normal;
}
.viz-hint:hover .viz-hint-pop,
.viz-hint:focus .viz-hint-pop {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
}
.viz-card-body {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
