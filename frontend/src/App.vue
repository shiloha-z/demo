<script setup lang="ts">
import ProjectSidebar from './components/ProjectSidebar.vue'
</script>

<template>
  <el-container class="app-container">
    <!-- Top Navigation -->
    <el-header class="app-header">
      <div class="header-left">
        <span class="header-logo">🤖 多 Agent 协作审查平台</span>
      </div>
      <div class="header-right">
        <el-tag size="small" type="info">未登录</el-tag>
      </div>
    </el-header>

    <el-container class="app-body">
      <!-- Left Sidebar -->
      <el-aside class="app-sidebar" width="220px">
        <ProjectSidebar />
      </el-aside>

      <!-- Main Content -->
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.app-container {
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #1a1a2e;
  border-bottom: 1px solid #333;
  padding: 0 20px;
  height: 56px;
}

.header-logo {
  color: #e0e0e0;
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 1px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.app-body {
  flex: 1;
  overflow: hidden;
}

.app-sidebar {
  background: #f5f7fa;
  border-right: 1px solid #e4e7ed;
  overflow-y: auto;
}

.app-main {
  background: #fff;
  overflow-y: auto;
  padding: 24px;
}
</style>
