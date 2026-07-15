<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, computed } from 'vue'
import { useProjectStore } from '../stores/project'
import { useWebSocketStore } from '../stores/websocket'
import FileTree from '../components/FileTree.vue'
import MonacoEditor from '../components/MonacoEditor.vue'
import api, { getErrorMessage } from '../api'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'

const store = useProjectStore()
const wsStore = useWebSocketStore()
const fileTreeRef = ref<InstanceType<typeof FileTree>>()

const selectedProjectId = computed(() => store.currentProject?.id ?? null)
const selectedFile = ref('')
const fileContent = ref('')
const loadingFile = ref(false)

const showNewFile = ref(false)
const showNewFolder = ref(false)
const newFileName = ref('')
const newFolderName = ref('')
const creating = ref(false)
const uploading = ref(false)
const folderUploading = ref(false)
const uploadInput = ref<HTMLInputElement>()
const folderInput = ref<HTMLInputElement>()

function triggerUpload() { uploadInput.value?.click() }
function triggerFolderUpload() { folderInput.value?.click() }

async function handleUpload(e: Event) {
  const input = e.target as HTMLInputElement
  const fileList = input.files
  if (!fileList || fileList.length === 0 || !selectedProjectId.value) return
  uploading.value = true
  try {
    const form = new FormData()
    for (const f of fileList) form.append('files', f)
    form.append('path', '')
    await api.post(`/projects/${selectedProjectId.value}/upload`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    MessagePlugin.success(`${fileList.length} 个文件已上传`)
    fileTreeRef.value?.loadFiles()
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '上传失败')) }
  finally { uploading.value = false; input.value = '' }
}

async function handleFolderUpload(e: Event) {
  const input = e.target as HTMLInputElement
  const fileList = input.files
  if (!fileList || fileList.length === 0 || !selectedProjectId.value) return
  folderUploading.value = true
  try {
    const form = new FormData()
    const paths: string[] = []
    let rootFolder = ''
    for (const f of fileList) {
      form.append('files', f)
      const relativePath = (f as any).webkitRelativePath || f.name
      paths.push(relativePath)
      if (!rootFolder) {
        rootFolder = relativePath.split('/')[0] || ''
      }
      form.append('file_paths', relativePath)
    }
    form.append('path', rootFolder)
    await api.post(`/projects/${selectedProjectId.value}/upload`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    MessagePlugin.success(`${fileList.length} 个文件已上传`)
    fileTreeRef.value?.loadFiles()
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '上传失败')) }
  finally { folderUploading.value = false; input.value = '' }
}

watch(() => store.currentProject?.id, () => {
  selectedFile.value = ''
  fileContent.value = ''
}, { immediate: true })

// Refresh the file tree when the backend reports a change to this project
// (e.g. after a version rollback or an approved review merge).
let unsubFileChange: (() => void) | null = null
onMounted(() => {
  unsubFileChange = wsStore.on('file_change', (data: any) => {
    if (data?.project_id && data.project_id === selectedProjectId.value) {
      fileTreeRef.value?.loadFiles()
    }
  })
})
onUnmounted(() => {
  unsubFileChange?.()
})

async function handleSelect(path: string) {
  if (!selectedProjectId.value) return
  selectedFile.value = path
  loadingFile.value = true
  try {
    const { data } = await api.get(`/projects/${selectedProjectId.value}/file`, { params: { path } })
    fileContent.value = data.content
  } finally { loadingFile.value = false }
}

function getLanguage() { return selectedFile.value || 'plaintext' }

async function createFile() {
  if (!selectedProjectId.value || !newFileName.value) return
  creating.value = true
  try {
    await api.post(`/projects/${selectedProjectId.value}/file`, null, { params: { path: newFileName.value, content: '' } })
    MessagePlugin.success(`文件 ${newFileName.value} 已创建`)
    showNewFile.value = false; newFileName.value = ''
    fileTreeRef.value?.loadFiles()
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '创建失败')) }
  finally { creating.value = false }
}

async function createFolder() {
  if (!selectedProjectId.value || !newFolderName.value) return
  creating.value = true
  try {
    await api.post(`/projects/${selectedProjectId.value}/folder`, null, { params: { path: newFolderName.value } })
    MessagePlugin.success(`文件夹 ${newFolderName.value} 已创建`)
    showNewFolder.value = false; newFolderName.value = ''
    fileTreeRef.value?.loadFiles()
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '创建失败')) }
  finally { creating.value = false }
}

async function handleTreeDelete(path: string) {
  if (!selectedProjectId.value) return
  const name = path.split('/').pop() || path
  const confirmDialog = DialogPlugin.confirm({
    header: '确认删除',
    body: `确定要删除「${name}」吗？此操作不可撤销。`,
    confirmBtn: { content: '删除', theme: 'danger' },
    cancelBtn: '取消',
    onConfirm: async () => {
      try {
        await api.delete(`/projects/${selectedProjectId.value}/file`, { params: { path } })
        MessagePlugin.success(`已删除 ${name}`)
        if (selectedFile.value === path) {
          selectedFile.value = ''
          fileContent.value = ''
        }
        fileTreeRef.value?.loadFiles()
      } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '删除失败')) }
      confirmDialog.destroy()
    },
  })
}

async function deleteSelected() {
  if (!selectedProjectId.value || !selectedFile.value) return
  const path = selectedFile.value
  const name = path.split('/').pop() || path
  const confirmDialog = DialogPlugin.confirm({
    header: '确认删除',
    body: `确定要删除「${name}」吗？此操作不可撤销。`,
    confirmBtn: { content: '删除', theme: 'danger' },
    cancelBtn: '取消',
    onConfirm: async () => {
      try {
        await api.delete(`/projects/${selectedProjectId.value}/file`, { params: { path } })
        MessagePlugin.success(`已删除 ${name}`)
        selectedFile.value = ''
        fileContent.value = ''
        fileTreeRef.value?.loadFiles()
      } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '删除失败')) }
      confirmDialog.destroy()
    },
  })
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
      <div class="empty-icon">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
      </div>
      <h3>请先选择一个项目</h3>
      <p>在上方下拉菜单中选择项目，或前往项目看板创建</p>
    </div>

    <div v-else class="file-panels">
      <div class="file-tree-panel">
        <div class="tree-toolbar">
          <span class="tree-title">文件列表</span>
          <div class="tree-actions">
            <t-button shape="square" variant="text" size="small" title="新建文件" @click="showNewFile = true">
              <template #icon>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/></svg>
              </template>
            </t-button>
            <t-button shape="square" variant="text" size="small" title="新建文件夹" @click="showNewFolder = true">
              <template #icon>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/></svg>
              </template>
            </t-button>
            <t-button shape="square" variant="text" size="small" :disabled="uploading" title="上传文件" @click="triggerUpload">
              <template #icon>
                <svg v-if="!uploading" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                <span v-else class="mini-spinner"></span>
              </template>
            </t-button>
            <t-button shape="square" variant="text" size="small" :disabled="folderUploading" title="上传文件夹" @click="triggerFolderUpload">
              <template #icon>
                <svg v-if="!folderUploading" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><polyline points="12 8 12 16"/><polyline points="9 11 12 8 15 11"/></svg>
                <span v-else class="mini-spinner"></span>
              </template>
            </t-button>
            <input ref="uploadInput" type="file" multiple style="display:none" @change="handleUpload" />
            <input ref="folderInput" type="file" webkitdirectory style="display:none" @change="handleFolderUpload" />
          </div>
        </div>
        <FileTree ref="fileTreeRef" :project-id="selectedProjectId" @select="handleSelect" @delete-node="handleTreeDelete" />
      </div>
      <div class="file-view-panel" v-loading="loadingFile">
        <template v-if="selectedFile">
          <div class="file-path-bar">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            {{ selectedFile }}
            <button class="file-delete-btn" title="删除" @click="deleteSelected">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
            </button>
          </div>
          <MonacoEditor :content="fileContent" :language="getLanguage()" />
        </template>
        <div v-else class="empty-view">
          <div class="empty-view-icon">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M9 11l3 3 8-8"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
          </div>
          <p>点击左侧文件查看内容</p>
        </div>
      </div>
    </div>

    <t-dialog v-model:visible="showNewFile" header="新建文件" width="400px">
      <t-input v-model="newFileName" placeholder="例如：src/login.py 或 README.md" @enter="createFile" />
      <template #footer>
        <t-button theme="default" variant="text" @click="showNewFile = false">取消</t-button>
        <t-button theme="primary" :disabled="!newFileName || creating" @click="createFile">创建</t-button>
      </template>
    </t-dialog>

    <t-dialog v-model:visible="showNewFolder" header="新建文件夹" width="400px">
      <t-input v-model="newFolderName" placeholder="例如：src 或 components" @enter="createFolder" />
      <template #footer>
        <t-button theme="default" variant="text" @click="showNewFolder = false">取消</t-button>
        <t-button theme="primary" :disabled="!newFolderName || creating" @click="createFolder">创建</t-button>
      </template>
    </t-dialog>
  </div>
</template>

<style scoped>
.page-root { height: 100%; display: flex; flex-direction: column; max-width: 1400px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-shrink: 0; }

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
  padding: 8px 12px; border-bottom: 1px solid var(--surface-border);
  flex-shrink: 0;
}

.tree-title { font-size: 12.5px; font-weight: 700; color: var(--foreground); }
.tree-actions { display: flex; gap: 2px; }

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
.file-delete-btn {
  margin-left: auto; width: 26px; height: 26px; border-radius: var(--radius-sm);
  border: none; background: transparent; color: var(--muted-foreground);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: all var(--transition-fast);
}
.file-delete-btn:hover { background: var(--danger-light); color: var(--danger); }
.file-view-panel :deep(.monaco-container) { flex: 1; }

.empty-view { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; }
.empty-view-icon { color: var(--muted-foreground); opacity: 0.5; }
.empty-view p { font-size: 13px; color: var(--muted-foreground); margin: 0; }
</style>
