<script setup lang="ts">
// Placeholder — will be fully implemented in Step 5
</script>

<template>
  <div class="page-root">
    <div class="page-header">
      <div>
        <h1 class="page-title">版本历史</h1>
        <p class="page-desc">查看代码提交历史和版本回退</p>
      </div>
    </div>

    <div class="empty-card">
      <div class="empty-icon">🕐</div>
      <h3>版本管理即将上线</h3>
      <p>在第5步中将实现 Git 版本历史和回退功能</p>
    </div>
  </div>
</template>

<style scoped>
.page-root { max-width: 1000px; }
.page-header { margin-bottom: 24px; }
.page-title { font-size: 22px; font-weight: 700; margin: 0; letter-spacing: -0.4px; }
.page-desc { font-size: 13.5px; color: var(--muted-foreground); margin: 4px 0 0; }
.empty-card { text-align: center; padding: 64px 32px; background: var(--surface); border: 1px solid var(--surface-border); border-radius: var(--radius-lg); box-shadow: var(--shadow-surface); }
.empty-icon { font-size: 40px; margin-bottom: 12px; }
.empty-card h3 { font-size: 16px; font-weight: 600; margin: 0 0 6px; }
.empty-card p { font-size: 13px; color: var(--muted-foreground); margin: 0; }
</style>
