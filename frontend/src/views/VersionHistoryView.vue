<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
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

async function rollback(v: any) {
  try {
    await ElMessageBox.confirm(
      `确定要回退到版本 ${v.short_hash} 吗？\n\n提交信息: ${v.commit_message}\n\n此操作将丢弃之后的所有更改。`,
      '确认回退',
      { confirmButtonText: '回退', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return // user cancelled
  }

  rollingBack.value = v.id
  try {
    const { data } = await api.post(`/projects/${selectedProjectId.value}/versions/${v.id}/rollback`)
    ElMessage.success(data.message || '回退成功')
    await loadVersions()
  } catch {
    ElMessage.error('回退失败')
  } finally {
    rollingBack.value = null
  }
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
        <button class="btn-ghost-sm" @click="loadVersions" title="刷新">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        </button>
      </div>
    </div>

    <div v-if="!selectedProjectId" class="empty-card">
      <div class="empty-icon">🕐</div>
      <h3>请先选择一个项目</h3>
    </div>

    <div v-else-if="loading" class="empty-card">
      <div class="loading-spinner"></div>
      <p>加载中...</p>
    </div>

    <div v-else-if="versions.length === 0" class="empty-card">
      <div class="empty-icon">📦</div>
      <h3>暂无版本记录</h3>
      <p>审查通过后自动生成 Git commit，版本记录会出现在这里</p>
    </div>

    <!-- Timeline -->
    <div v-else class="timeline">
      <div v-for="(v, i) in versions" :key="v.id" class="timeline-item">
        <!-- Line + dot -->
        <div class="timeline-track">
          <div class="timeline-dot" :class="{ latest: i === 0 }"></div>
          <div v-if="i < versions.length - 1" class="timeline-line"></div>
        </div>

        <!-- Content -->
        <div class="timeline-card">
          <div class="card-left">
            <code class="commit-hash" :title="v.commit_hash">{{ v.short_hash }}</code>
            <span class="commit-message">{{ v.commit_message }}</span>
          </div>
          <div class="card-right">
            <span class="commit-time">{{ formatDate(v.created_at) }}</span>
            <span v-if="v.review_id" class="review-link">审查 #{{ v.review_id }}</span>
            <button
              class="btn-rollback"
              :disabled="rollingBack === v.id"
              @click="rollback(v)"
              title="回退到此版本"
            >
              <svg v-if="rollingBack !== v.id" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>
              <span v-else class="mini-spinner"></span>
              回退
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-root { max-width: 900px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-title { font-size: 22px; font-weight: 700; margin: 0; }
.page-desc { font-size: 13.5px; color: var(--muted-foreground); margin: 4px 0 0; }
.header-right { display: flex; align-items: center; gap: 8px; }

.project-select {
  padding: 7px 12px; border: 1px solid var(--input); border-radius: var(--radius-md);
  font-size: 13.5px; background: var(--surface); color: var(--foreground); outline: none; min-width: 200px;
}
.btn-ghost-sm {
  width: 32px; height: 32px; border-radius: var(--radius-md); border: none;
  background: transparent; color: var(--muted-foreground); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
}
.btn-ghost-sm:hover { background: var(--surface-hover); color: var(--foreground); }

/* ── Timeline ───────────────────────────────────── */
.timeline { padding-left: 8px; }
.timeline-item { display: flex; gap: 16px; }

.timeline-track {
  display: flex; flex-direction: column; align-items: center; width: 20px; flex-shrink: 0;
}
.timeline-dot {
  width: 10px; height: 10px; border-radius: 50%;
  background: var(--surface-border); border: 2px solid var(--surface-border);
  margin-top: 14px; flex-shrink: 0;
}
.timeline-dot.latest {
  background: var(--brand); border-color: var(--brand); box-shadow: 0 0 0 3px oklch(0.55 0.22 255 / 0.15);
}
.timeline-line {
  width: 2px; flex: 1; min-height: 24px; background: var(--surface-border);
}

.timeline-card {
  flex: 1; display: flex; justify-content: space-between; align-items: center; gap: 12px;
  padding: 12px 16px; margin-bottom: 4px;
  background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-md); box-shadow: var(--shadow-surface);
  transition: border-color 0.12s;
}
.timeline-card:hover { border-color: var(--ring); }

.card-left { display: flex; align-items: center; gap: 10px; min-width: 0; }
.commit-hash {
  font-size: 12px; font-weight: 700; color: var(--brand); background: oklch(0.55 0.22 255 / 0.08);
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

.btn-rollback {
  display: flex; align-items: center; gap: 4px;
  padding: 5px 10px; border-radius: var(--radius-sm); border: 1px solid var(--surface-border);
  background: var(--surface); color: var(--muted-foreground);
  font-size: 12px; font-weight: 500; cursor: pointer; transition: all 0.12s;
}
.btn-rollback:hover { background: oklch(0.577 0.245 27 / 0.06); color: var(--danger); border-color: oklch(0.577 0.245 27 / 0.3); }
.btn-rollback:disabled { opacity: 0.6; cursor: default; }

.mini-spinner {
  width: 12px; height: 12px; border: 2px solid var(--surface-border);
  border-top-color: var(--danger); border-radius: 50%;
  animation: spin 0.8s linear infinite; display: inline-block;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ── Empty ──────────────────────────────────────── */
.empty-card { text-align: center; padding: 64px 32px; background: var(--surface); border: 1px solid var(--surface-border); border-radius: var(--radius-lg); box-shadow: var(--shadow-surface); }
.empty-icon { font-size: 40px; margin-bottom: 12px; }
.empty-card h3 { font-size: 16px; font-weight: 600; margin: 0 0 6px; }
.empty-card p { font-size: 13px; color: var(--muted-foreground); margin: 0; }
.loading-spinner { width: 28px; height: 28px; border: 3px solid var(--surface-border); border-top-color: var(--brand); border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto 12px; }
</style>
