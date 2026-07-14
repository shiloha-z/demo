<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import api from '../api'

const props = defineProps<{ projectId: number }>()

const emit = defineEmits<{
  select: [path: string]
}>()

interface TreeNode {
  name: string
  path: string
  type: 'file' | 'dir'
  children?: TreeNode[]
}

const treeData = ref<TreeNode[]>([])
const loading = ref(false)

async function loadFiles() {
  loading.value = true
  try {
    const { data } = await api.get(`/projects/${props.projectId}/files`)
    treeData.value = data.files
  } finally {
    loading.value = false
  }
}

async function loadChildren(node: any, resolve: (data: TreeNode[]) => void) {
  // node.data contains { path, type }
  if (node.data.type === 'dir') {
    try {
      const { data } = await api.get(`/projects/${props.projectId}/files`, {
        params: { path: node.data.path }
      })
      resolve(data.files)
    } catch {
      resolve([])
    }
  } else {
    resolve([])
  }
}

function handleClick(data: TreeNode) {
  if (data.type === 'file') {
    emit('select', data.path)
  }
}

// Auto-load on mount & project change
onMounted(() => loadFiles())
watch(() => props.projectId, () => loadFiles())

// Expose reload
defineExpose({ loadFiles })
</script>

<template>
  <div class="file-tree" v-loading="loading">
    <div class="file-tree-header">
      <span>📁 文件列表</span>
      <el-button size="small" text @click="loadFiles">刷新</el-button>
    </div>
    <el-tree
      :data="treeData"
      :props="{ label: 'name', children: 'children', isLeaf: (d: TreeNode) => d.type === 'file' }"
      node-key="path"
      lazy
      :load="loadChildren"
      :default-expanded-keys="treeData.filter(n => n.type === 'dir').map(n => n.path)"
      @node-click="handleClick"
      highlight-current
    >
      <template #default="{ data }">
        <span class="tree-node">
          <span>{{ data.type === 'dir' ? '📁' : '📄' }}</span>
          <span style="margin-left: 6px">{{ data.name }}</span>
        </span>
      </template>
    </el-tree>
  </div>
</template>

<style scoped>
.file-tree {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.file-tree-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid #ebeef5;
  font-weight: 600;
}
:deep(.el-tree) {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}
.tree-node {
  font-size: 13px;
}
</style>
