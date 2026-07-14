<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import { useProjectStore } from '../stores/project'
import api from '../api'

const store = useProjectStore()

const selectedProjectId = computed(() => store.currentProject?.id ?? null)
const versions = ref<any[]>([])
const loading = ref(false)
const rollingBack = ref<string | null>(null)

watch(() => store.currentProject?.id, async (pid) => {
  if (!pid) return
  await loadVersions()
}, { immediate: true })

async function loadVersions() {
  if (!selectedProjectId.value) return
  loading.value = true
  try {
    const { data } = await api.get(`/projects/${selectedProjectId.value}/versions`)
    versions.value = data
  } catch { versions.value = [] }
  finally { loading.value = false }
}

function rollback(v: any) {
  const confirmDialog = DialogPlugin.confirm({
    header: '确认回退',
    body: `确定要回退到版本 ${v.short_hash} 吗？\n\n提交信息: ${v.commit_message}\n\n此操作将丢弃之后的所有更改。`,
    confirmBtn: { content: '回退', theme: 'danger' },
    cancelBtn: '取消',
    onConfirm: async () => {
      rollingBack.value = v.id
      try {
        const { data } = await api.post(`/projects/${selectedProjectId.value}/versions/${v.id}/rollback`)
        MessagePlugin.success(data.message || '回退成功')
        await loadVersions()
      } catch {
        MessagePlugin.error('回退失败')
      } finally {
        rollingBack.value = null
      }
      confirmDialog.destroy()
    },
  })
}

function formatDate(d: string) {
  if (!d) return ''
  return new Date(d).toLocaleString('zh-CN')
}
</script>

<template>
  <div class="page-root">
    <div class="page-header">
      <div>
        <h1 class="page-title">版本历史</h1>
        <p class="page-desc">查看 Git 提交记录，回退到历史版本</p>
      </div>
      <div class="header-right">
        <t-button shape="square" variant="text" @click="loadVersions" title="刷新">
          <template #icon>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
          </template>
        </t-button>
      </div>
    </div>

    <div v-if="!selectedProjectId" class="empty-card">
      <div class="empty-icon">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
      </div>
      <h3>请先选择一个项目</h3>
    </div>

    <div v-else-if="loading" class="empty-card">
      <div class="loading-spinner"></div>
      <p>加载中...</p>
    </div>

    <div v-else-if="versions.length === 0" class="empty-card">
      <div class="empty-icon">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>
      </div>
      <h3>暂无版本记录</h3>
      <p>审查通过后自动生成 Git commit，版本记录会出现在这里</p>
    </div>

    <!-- Timeline -->
    <div v-else class="timeline">
      <div v-for="(v, i) in versions" :key="v.id" class="timeline-item">
        <div class="timeline-track">
          <div class="timeline-dot" :class="{ latest: i === 0 }"></div>
          <div v-if="i < versions.length - 1" class="timeline-line"></div>
        </div>

        <div class="timeline-card">
          <div class="card-left">
            <code class="commit-hash" :title="v.commit_hash">{{ v.short_hash }}</code>
            <span class="commit-message">{{ v.commit_message }}</span>
          </div>
          <div class="card-right">
            <span class="commit-time">{{ formatDate(v.created_at) }}</span>
            <span v-if="v.review_id" class="review-link">审查 #{{ v.review_id }}</span>
            <t-button
              size="small"
              variant="outline"
              theme="danger"
              :disabled="rollingBack === v.id"
              @click="rollback(v)"
              title="回退到此版本"
            >
              <template #icon>
                <svg v-if="rollingBack !== v.id" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>
                <span v-else class="mini-spinner"></span>
              </template>
              回退
            </t-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-root { max-width: 900px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.header-right { display: flex; align-items: center; gap: 8px; }

/* ── Timeline ───────────────────────────────────────────────────── */
.timeline { padding-left: 8px; }
.timeline-item { display: flex; gap: 16px; }

.timeline-track {
  display: flex; flex-direction: column; align-items: center; width: 20px; flex-shrink: 0;
}
.timeline-dot {
  width: 10px; height: 10px; border-radius: 50%;
  background: var(--surface-border); border: 2px solid var(--surface-border);
  margin-top: 14px; flex-shrink: 0;
  transition: all var(--transition-base);
}
.timeline-dot.latest {
  background: var(--primary); border-color: var(--primary);
  box-shadow: 0 0 0 4px var(--primary-light);
}
.timeline-line {
  width: 2px; flex: 1; min-height: 24px; background: var(--surface-border);
}

.timeline-card {
  flex: 1; display: flex; justify-content: space-between; align-items: center; gap: 12px;
  padding: 12px 16px; margin-bottom: 4px;
  background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-md); box-shadow: var(--shadow-surface);
  transition: border-color var(--transition-base), box-shadow var(--transition-base);
}
.timeline-card:hover { border-color: var(--primary); box-shadow: var(--shadow-card-hover); }

.card-left { display: flex; align-items: center; gap: 10px; min-width: 0; }
.commit-hash {
  font-size: 12px; font-weight: 700; color: var(--primary); background: var(--primary-light);
  padding: 2px 6px; border-radius: 4px; font-family: var(--font-mono); flex-shrink: 0;
}
.commit-message {
  font-size: 13.5px; font-weight: 500; color: var(--foreground);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

.card-right { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.commit-time { font-size: 12px; color: var(--muted-foreground); }
.review-link {
  font-size: 11px; color: var(--muted-foreground); background: var(--surface-hover);
  padding: 2px 7px; border-radius: 99px;
}
</style>
