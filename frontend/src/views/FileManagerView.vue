<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { useProjectStore } from '../stores/project'
import FileTree from '../components/FileTree.vue'
import MonacoEditor from '../components/MonacoEditor.vue'
import api from '../api'
import { ElMessage } from 'element-plus'

const store = useProjectStore()
const fileTreeRef = ref<InstanceType<typeof FileTree>>()

const selectedProjectId = computed(() => store.currentProject?.id ?? null)
const selectedFile = ref('')
const fileContent = ref('')
const loadingFile = ref(false)

// Create dialogs
const showNewFile = ref(false)
const showNewFolder = ref(false)
const newFileName = ref('')
const newFolderName = ref('')
const creating = ref(false)

// Reset file view when project changes
watch(() => store.currentProject?.id, () => {
  selectedFile.value = ''
  fileContent.value = ''
}, { immediate: true })

async function handleSelect(path: string) {
  if (!selectedProjectId.value) return
  selectedFile.value = path
  loadingFile.value = true
  try {
    const { data } = await api.get(`/projects/${selectedProjectId.value}/file`, { params: { path } })
    fileContent.value = data.content
  } finally {
    loadingFile.value = false
  }
}

function getLanguage() { return selectedFile.value || 'plaintext' }

async function createFile() {
  if (!selectedProjectId.value || !newFileName.value) return
  creating.value = true
  try {
    await api.post(`/projects/${selectedProjectId.value}/file`, null, { params: { path: newFileName.value, content: '' } })
    ElMessage.success(`文件 ${newFileName.value} 已创建`)
    showNewFile.value = false; newFileName.value = ''
    fileTreeRef.value?.loadFiles()
  } catch { ElMessage.error('创建失败') }
  finally { creating.value = false }
}

async function createFolder() {
  if (!selectedProjectId.value || !newFolderName.value) return
  creating.value = true
  try {
    await api.post(`/projects/${selectedProjectId.value}/folder`, null, { params: { path: newFolderName.value } })
    ElMessage.success(`文件夹 ${newFolderName.value} 已创建`)
    showNewFolder.value = false; newFolderName.value = ''
    fileTreeRef.value?.loadFiles()
  } catch { ElMessage.error('创建失败') }
  finally { creating.value = false }
}
</script>

<template>
  <div class="page-root">
    <div class="page-header">
      <div>
        <h1 class="page-title">文件管理器</h1>
        <p class="page-desc">{{ store.currentProject ? `当前项目：${store.currentProject.name}` : '请在侧边栏选择项目' }}</p>
      </div>
    </div>

    <div v-if="!selectedProjectId" class="empty-card">
      <div class="empty-icon">📁</div>
      <h3>请先选择一个项目</h3>
      <p>在上方下拉菜单中选择项目，或前往项目看板创建</p>
    </div>

    <div v-else class="file-panels">
      <div class="file-tree-panel">
        <div class="tree-toolbar">
          <span class="tree-title">文件列表</span>
          <div class="tree-actions">
            <button class="btn-icon" title="新建文件" @click="showNewFile = true">📄</button>
            <button class="btn-icon" title="新建文件夹" @click="showNewFolder = true">📁</button>
          </div>
        </div>
        <FileTree ref="fileTreeRef" :project-id="selectedProjectId" @select="handleSelect" />
      </div>
      <div class="file-view-panel" v-loading="loadingFile">
        <template v-if="selectedFile">
          <div class="file-path-bar">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            {{ selectedFile }}
          </div>
          <MonacoEditor :content="fileContent" :language="getLanguage()" />
        </template>
        <div v-else class="empty-view">
          <span class="empty-view-icon">👈</span>
          <p>点击左侧文件查看内容</p>
        </div>
      </div>
    </div>

    <!-- Dialogs -->
    <el-dialog v-model="showNewFile" title="新建文件" width="400px">
      <input v-model="newFileName" class="field-input" placeholder="例如：src/login.py 或 README.md" @keyup.enter="createFile" />
      <template #footer>
        <button class="btn-ghost" @click="showNewFile = false">取消</button>
        <button class="btn-primary" :disabled="!newFileName || creating" @click="createFile">创建</button>
      </template>
    </el-dialog>

    <el-dialog v-model="showNewFolder" title="新建文件夹" width="400px">
      <input v-model="newFolderName" class="field-input" placeholder="例如：src 或 components" @keyup.enter="createFolder" />
      <template #footer>
        <button class="btn-ghost" @click="showNewFolder = false">取消</button>
        <button class="btn-primary" :disabled="!newFolderName || creating" @click="createFolder">创建</button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-root { height: 100%; display: flex; flex-direction: column; max-width: 1400px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-shrink: 0; }
.page-title { font-size: 22px; font-weight: 700; margin: 0; }
.page-desc { font-size: 13.5px; color: var(--muted-foreground); margin: 4px 0 0; }

.project-select {
  padding: 7px 12px; border: 1px solid var(--input); border-radius: var(--radius-md);
  font-size: 13.5px; font-family: var(--font-sans); background: var(--surface);
  color: var(--foreground); outline: none; cursor: pointer; min-width: 200px;
}

/* ── Panels ─────────────────────────────────────────────────────── */
.file-panels {
  flex: 1; display: flex; border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg); overflow: hidden; background: var(--surface);
  box-shadow: var(--shadow-surface);
}

.file-tree-panel {
  width: 260px; border-right: 1px solid var(--surface-border);
  background: var(--app-shell); display: flex; flex-direction: column;
}

.tree-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 14px; border-bottom: 1px solid var(--surface-border);
  flex-shrink: 0;
}

.tree-title { font-size: 12.5px; font-weight: 700; color: var(--foreground); }
.tree-actions { display: flex; gap: 2px; }

.btn-icon {
  width: 28px; height: 28px; border-radius: var(--radius-sm);
  border: none; background: transparent; font-size: 15px; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: background 0.12s;
}
.btn-icon:hover { background: var(--surface-hover); }

.file-tree-panel :deep(.file-tree) { flex: 1; overflow-y: auto; }

.file-view-panel {
  flex: 1; display: flex; flex-direction: column; background: var(--page-canvas);
}
.file-path-bar {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 14px; background: var(--surface); border-bottom: 1px solid var(--surface-border);
  font-size: 12px; font-family: var(--font-mono); color: var(--muted-foreground);
  flex-shrink: 0;
}
.file-view-panel :deep(.monaco-container) { flex: 1; }

/* ── Empty ──────────────────────────────────────────────────────── */
.empty-card { text-align: center; padding: 64px 32px; background: var(--surface); border: 1px solid var(--surface-border); border-radius: var(--radius-lg); }
.empty-icon { font-size: 40px; margin-bottom: 12px; }
.empty-card h3 { font-size: 16px; font-weight: 600; margin: 0 0 6px; }
.empty-card p { font-size: 13px; color: var(--muted-foreground); margin: 0; }

.empty-view { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; }
.empty-view-icon { font-size: 28px; }
.empty-view p { font-size: 13px; color: var(--muted-foreground); margin: 0; }

/* ── Shared buttons ─────────────────────────────────────────────── */
.btn-primary {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 16px; border-radius: var(--radius-md);
  background: var(--primary); color: var(--primary-foreground);
  border: none; font-size: 13.5px; font-weight: 600; cursor: pointer;
}
.btn-primary:hover { opacity: 0.85; }
.btn-primary:disabled { opacity: 0.5; cursor: default; }
.btn-ghost {
  padding: 8px 16px; border-radius: var(--radius-md);
  background: transparent; color: var(--muted-foreground);
  border: none; font-size: 13.5px; font-weight: 500; cursor: pointer;
}
.btn-ghost:hover { background: var(--surface-hover); color: var(--foreground); }
.field-input {
  width: 100%; padding: 9px 12px; border: 1px solid var(--input); border-radius: var(--radius-md);
  font-size: 14px; font-family: var(--font-sans); color: var(--foreground);
  background: var(--surface); outline: none; box-sizing: border-box;
}
.field-input:focus { border-color: var(--ring); }
</style>
