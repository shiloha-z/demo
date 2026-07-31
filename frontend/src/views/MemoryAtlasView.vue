<script setup lang="ts">
import MemoryAtlas from '../components/memory/MemoryAtlas.vue'
</script>

<template>
  <div class="page-root">
    <div class="page-header">
      <div>
        <h1 class="page-title">记忆图谱</h1>
        <p class="page-desc">可视化平台「任务 → Agent → 项目 → 全局」四层记忆的层级结构与沉淀流向，呈现经验如何由任务级逐步蒸馏为可全局复用的高质量模式。</p>
      </div>
    </div>

    <div class="atlas-hint">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="9" /><path d="M12 8v4" /><path d="M12 16h.01" />
      </svg>
      <span>点击左侧图谱中的任意一层，即可在右侧查看该层的类型分布与记忆流。<b>项目层</b>与 <b>Agent 层</b>旁的下拉菜单可直接切换查看对象。</span>
    </div>

    <MemoryAtlas />
  </div>
</template>

<style scoped>
.atlas-hint {
  display: flex; align-items: center; gap: 8px;
  font-size: 12.5px; color: var(--info); background: var(--info-light);
  border-radius: var(--radius-md); padding: 10px 14px; line-height: 1.6;
  margin-bottom: 18px;
}
.atlas-hint svg { flex-shrink: 0; }
.atlas-hint b { color: var(--foreground); font-weight: 600; }
</style>
