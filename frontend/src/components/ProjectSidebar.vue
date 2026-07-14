<script setup lang="ts">
import { useRoute } from 'vue-router'
import { computed } from 'vue'

const route = useRoute()

const menuItems = [
  { path: '/dashboard', icon: 'Odometer', label: '项目看板' },
  { path: '/files',     icon: 'FolderOpened', label: '文件管理' },
  { path: '/agents',    icon: 'UserFilled',   label: 'Agent 池' },
  { path: '/reviews',   icon: 'DocumentChecked', label: '审查记录' },
  { path: '/versions',  icon: 'Clock',        label: '版本历史' },
]

const activeMenu = computed(() => route.path)
</script>

<template>
  <el-menu
    :default-active="activeMenu"
    router
    class="sidebar-menu"
  >
    <div class="sidebar-title">导航菜单</div>
    <el-menu-item
      v-for="item in menuItems"
      :key="item.path"
      :index="item.path"
    >
      <el-icon><component :is="item.icon" /></el-icon>
      <span>{{ item.label }}</span>
    </el-menu-item>
  </el-menu>
</template>

<style scoped>
.sidebar-menu {
  border-right: none;
  background: transparent;
}

.sidebar-title {
  padding: 16px 20px 8px;
  font-size: 12px;
  color: #909399;
  text-transform: uppercase;
  letter-spacing: 2px;
}
</style>
