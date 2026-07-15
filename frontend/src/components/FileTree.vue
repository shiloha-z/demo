<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import api from '../api'

const props = defineProps<{ projectId: number }>()

const emit = defineEmits<{
  select: [path: string]
  deleteNode: [path: string]
}>()

interface TreeNode {
  name: string
  path: string
  type: 'file' | 'dir'
  children?: TreeNode[]
  expanded?: boolean
  loaded?: boolean
  loading?: boolean
}

const treeData = ref<TreeNode[]>([])
const loading = ref(false)
const selectedPath = ref<string>('')

async function loadFiles() {
  loading.value = true
  try {
    const { data } = await api.get(`/projects/${props.projectId}/files`)
    treeData.value = data.files.map((n: TreeNode) => ({ ...n, expanded: n.type === 'dir' ? false : undefined, loaded: n.type === 'dir' ? false : undefined }))
    // Auto-expand root directories
    for (const node of treeData.value) {
      if (node.type === 'dir') {
        await expandDir(node)
      }
    }
  } finally {
    loading.value = false
  }
}

async function expandDir(node: TreeNode) {
  if (node.loaded) {
    node.expanded = !node.expanded
    return
  }
  node.loading = true
  try {
    const { data } = await api.get(`/projects/${props.projectId}/files`, {
      params: { path: node.path }
    })
    node.children = data.files.map((n: TreeNode) => ({ ...n, expanded: n.type === 'dir' ? false : undefined, loaded: n.type === 'dir' ? false : undefined }))
    node.loaded = true
    node.expanded = true
  } catch {
    node.children = []
  } finally {
    node.loading = false
  }
}

function handleClick(node: TreeNode) {
  if (node.type === 'file') {
    selectedPath.value = node.path
    emit('select', node.path)
  } else {
    selectedPath.value = node.path
    emit('select', node.path)
    expandDir(node)
  }
}

function handleDelete(e: Event, path: string) {
  e.stopPropagation()
  emit('deleteNode', path)
}

onMounted(() => loadFiles())
watch(() => props.projectId, () => loadFiles())

defineExpose({ loadFiles })
</script>

<template>
  <div class="file-tree" v-loading="loading">
    <div class="file-tree-header">
      <span>文件列表</span>
      <t-button size="small" variant="text" @click="loadFiles">刷新</t-button>
    </div>
    <div class="tree-body">
      <template v-for="node in treeData" :key="node.path">
        <!-- Root node -->
        <div
          class="tree-node-item"
          :class="{ active: selectedPath === node.path }"
          :style="{ paddingLeft: '12px' }"
          @click="handleClick(node)"
        >
          <span v-if="node.type === 'dir'" class="tree-caret">
            <svg v-if="node.loading" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="spin"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
            <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" :style="{ transform: node.expanded ? 'rotate(90deg)' : '' }"><polyline points="9 18 15 12 9 6"/></svg>
          </span>
          <span v-else class="tree-caret-spacer"></span>
          <span class="tree-icon" :class="node.type">
            <svg v-if="node.type === 'dir'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
            <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          </span>
          <span class="tree-label">{{ node.name }}</span>
          <button class="tree-delete-btn" title="删除" @click="handleDelete($event, node.path)">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
          </button>
        </div>

        <!-- Root children (depth 1) -->
        <template v-if="node.expanded && node.children">
          <template v-for="child in node.children" :key="child.path">
            <div
              class="tree-node-item"
              :class="{ active: selectedPath === child.path }"
              :style="{ paddingLeft: '28px' }"
              @click="handleClick(child)"
            >
              <span v-if="child.type === 'dir'" class="tree-caret">
                <svg v-if="child.loading" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="spin"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
                <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" :style="{ transform: child.expanded ? 'rotate(90deg)' : '' }"><polyline points="9 18 15 12 9 6"/></svg>
              </span>
              <span v-else class="tree-caret-spacer"></span>
              <span class="tree-icon" :class="child.type">
                <svg v-if="child.type === 'dir'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
              </span>
              <span class="tree-label">{{ child.name }}</span>
              <button class="tree-delete-btn" title="删除" @click="handleDelete($event, child.path)">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
              </button>
            </div>

            <!-- Child's children (depth 2) -->
            <template v-if="child.expanded && child.children">
              <div
                v-for="grandchild in child.children"
                :key="grandchild.path"
                class="tree-node-item"
                :class="{ active: selectedPath === grandchild.path }"
                :style="{ paddingLeft: '44px' }"
                @click="handleClick(grandchild)"
              >
                <span v-if="grandchild.type === 'dir'" class="tree-caret">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="9 18 15 12 9 6"/></svg>
                </span>
                <span v-else class="tree-caret-spacer"></span>
                <span class="tree-icon" :class="grandchild.type" style="width:12px;height:12px">
                  <svg v-if="grandchild.type === 'dir'" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                  <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                </span>
                <span class="tree-label">{{ grandchild.name }}</span>
                <button class="tree-delete-btn" title="删除" @click="handleDelete($event, grandchild.path)">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
                </button>
              </div>
            </template>
          </template>
        </template>
      </template>
      <div v-if="treeData.length === 0 && !loading" class="tree-empty">
        暂无文件
      </div>
    </div>
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
  border-bottom: 1px solid var(--surface-border);
  font-weight: 600;
  font-size: 12.5px;
  color: var(--foreground);
}
.tree-body {
  flex: 1;
  overflow-y: auto;
  padding: 6px 4px;
}

.tree-node-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 13px;
  color: var(--foreground);
  transition: background var(--transition-fast);
  white-space: nowrap;
  user-select: none;
}
.tree-node-item:hover {
  background: var(--surface-hover);
}
.tree-node-item.active {
  background: var(--primary-light);
  color: var(--primary);
  font-weight: 500;
}

.tree-caret {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  color: var(--muted-foreground);
  transition: transform var(--transition-fast);
}
.tree-caret svg {
  transition: transform var(--transition-fast);
}
.tree-caret-spacer {
  width: 14px;
  flex-shrink: 0;
}

.tree-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}
.tree-icon.dir {
  color: var(--primary);
}
.tree-icon.file {
  color: var(--muted-foreground);
}
.tree-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.tree-delete-btn {
  flex-shrink: 0;
  width: 22px; height: 22px;
  border-radius: var(--radius-sm);
  border: none; background: transparent;
  color: var(--muted-foreground);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  opacity: 0;
  transition: opacity var(--transition-fast), background var(--transition-fast), color var(--transition-fast);
}
.tree-node-item:hover .tree-delete-btn {
  opacity: 1;
}
.tree-delete-btn:hover {
  background: var(--danger-light);
  color: var(--danger);
}

.spin {
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.tree-empty {
  padding: 20px;
  text-align: center;
  font-size: 12px;
  color: var(--muted-foreground);
}
</style>
