<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { useProjectStore } from '../stores/project'
import { useWebSocketStore } from '../stores/websocket'
import DiffViewer from '../components/DiffViewer.vue'
import api, { getErrorMessage } from '../api'
import { renderMarkdown } from '../utils/markdown'

const store = useProjectStore()
const wsStore = useWebSocketStore()

const selectedProjectId = computed(() => store.currentProject?.id ?? null)
const reviews = ref<any[]>([])
const selectedReview = ref<any>(null)
const loading = ref(false)

const statusLabels: Record<string, string> = {
  pending: '待审查', approved: '已通过', rejected: '已驳回',
}
const statusColors: Record<string, string> = {
  pending: 'var(--warning)', approved: 'var(--success)', rejected: 'var(--danger)',
}

let unsubReview: (() => void) | null = null

onMounted(() => {
  unsubReview = wsStore.on('review_update', (data: any) => {
    const pid = store.currentProject?.id
    if (pid && data.project_id === pid) {
      loadReviews()
    }
  })
})

onUnmounted(() => {
  if (unsubReview) unsubReview()
})

watch(() => store.currentProject?.id, async (pid) => {
  if (!pid) return
  await loadReviews()
}, { immediate: true })

async function loadReviews() {
  if (!selectedProjectId.value) { reviews.value = []; return }
  try {
    const { data } = await api.get(`/projects/${selectedProjectId.value}/reviews`)
    reviews.value = Array.isArray(data) ? data : []
  } catch (e: any) {
    console.error('加载审查记录失败:', e?.response?.status, e?.response?.data || e?.message)
    reviews.value = []
  }
}

async function approve(review: any) {
  loading.value = true
  try {
    await api.post(`/reviews/${review.id}/approve`)
    MessagePlugin.success('审查已通过，已提交到 Git')
    await loadReviews()
    if (selectedReview.value?.id === review.id) selectedReview.value = null
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '操作失败')) }
  finally { loading.value = false }
}

async function reject(review: any) {
  loading.value = true
  try {
    await api.post(`/reviews/${review.id}/reject`)
    MessagePlugin.warning('审查已驳回')
    await loadReviews()
    if (selectedReview.value?.id === review.id) selectedReview.value = null
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '操作失败')) }
  finally { loading.value = false }
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
        <h1 class="page-title">审查记录</h1>
        <p class="page-desc">查看 Agent 代码审查结果，通过或驳回</p>
      </div>
    </div>

    <div v-if="!selectedProjectId" class="empty-card empty-card--full">
      <div class="empty-icon">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      </div>
      <h3>请先选择一个项目</h3>
    </div>

    <template v-else>
      <div v-if="reviews.length === 0" class="empty-card empty-card--full">
        <div class="empty-icon">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
        </div>
        <h3>暂无审查记录</h3>
        <p>前往 Agent 面板创建任务，执行后将自动生成审查记录</p>
      </div>

      <div v-else class="review-layout">
        <div class="review-list">
          <div
            v-for="r in reviews"
            :key="r.id"
            class="review-item"
            :class="{ active: selectedReview?.id === r.id }"
            @click="selectedReview = r"
          >
            <div class="review-item-header">
              <span class="review-id">#{{ r.id }}</span>
              <span class="review-status" :style="{ color: statusColors[r.status] }">
                {{ statusLabels[r.status] || r.status }}
              </span>
            </div>
            <div class="review-item-time">{{ formatDate(r.created_at) }}</div>
          </div>
        </div>

        <div class="review-detail" v-if="selectedReview">
          <div class="detail-header">
            <h3>审查 #{{ selectedReview.id }}</h3>
            <div class="detail-actions" v-if="selectedReview.status === 'pending'">
              <t-button size="small" theme="danger" variant="outline" :disabled="loading" @click="reject(selectedReview)">驳回</t-button>
              <t-button size="small" theme="success" :disabled="loading" @click="approve(selectedReview)">通过</t-button>
            </div>
          </div>

          <div class="detail-section">
            <h4 class="detail-label">代码变更 (Diff)</h4>
            <div class="diff-container">
              <DiffViewer
                v-if="selectedReview.diff_content"
                :diff="selectedReview.diff_content"
              />
              <p v-else class="no-diff">无代码变更</p>
            </div>
          </div>

          <div class="detail-section">
            <h4 class="detail-label">审查报告</h4>
            <div class="review-summary" v-html="renderMarkdown(selectedReview.agent_review_summary)" />
          </div>
        </div>

        <div v-else class="empty-detail">
          <div class="empty-detail-icon">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M9 11l3 3 8-8"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
          </div>
          <p>选择左侧审查记录查看详情</p>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page-root { height: 100%; display: flex; flex-direction: column; max-width: 1400px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-shrink: 0; }

.review-layout {
  flex: 1; display: flex; gap: 0;
  border: 1px solid var(--surface-border); border-radius: var(--radius-lg);
  overflow: hidden; min-height: 0;
  box-shadow: var(--shadow-surface);
}

.review-list {
  width: 260px; border-right: 1px solid var(--surface-border);
  background: var(--app-shell); overflow-y: auto; flex-shrink: 0;
}
.review-item {
  padding: 12px 14px; border-bottom: 1px solid var(--surface-border);
  cursor: pointer; transition: background var(--transition-fast);
}
.review-item:hover { background: var(--surface-hover); }
.review-item.active { background: var(--primary-lighter); border-left: 3px solid var(--primary); padding-left: 11px; }
.review-item-header { display: flex; justify-content: space-between; align-items: center; }
.review-id { font-size: 13px; font-weight: 600; color: var(--foreground); }
.review-status { font-size: 11px; font-weight: 600; }
.review-item-time { font-size: 11px; color: var(--muted-foreground); margin-top: 4px; }

.review-detail { flex: 1; overflow-y: auto; padding: 20px 24px; background: var(--page-canvas); }
.detail-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.detail-header h3 { font-size: 16px; font-weight: 700; margin: 0; }
.detail-actions { display: flex; gap: 8px; }

.detail-section { margin-bottom: 20px; }
.detail-label { font-size: 13px; font-weight: 700; color: var(--muted-foreground); margin: 0 0 8px; text-transform: uppercase; letter-spacing: 0.5px; }

.diff-container { border: 1px solid var(--surface-border); border-radius: var(--radius-md); overflow: hidden; max-height: 500px; overflow-y: auto; }
.no-diff { font-size: 13px; color: var(--muted-foreground); padding: 20px; text-align: center; }

.review-summary {
  background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-md); padding: 16px 18px;
  font-size: 13.5px; line-height: 1.7;
}
.review-summary :deep(h1) { font-size: 16px; font-weight: 700; margin: 0 0 8px; border-bottom: 1px solid var(--surface-border); padding-bottom: 6px; }
.review-summary :deep(h2) { font-size: 15px; font-weight: 700; margin: 12px 0 6px; }
.review-summary :deep(h3) { font-size: 14px; font-weight: 700; margin: 10px 0 4px; }
.review-summary :deep(h4) { font-size: 13px; font-weight: 600; margin: 8px 0 4px; }
.review-summary :deep(p) { margin: 0 0 8px; }
.review-summary :deep(ul), .review-summary :deep(ol) { margin: 0 0 8px; padding-left: 20px; }
.review-summary :deep(li) { margin-bottom: 2px; }
.review-summary :deep(code) {
  background: var(--surface-hover); padding: 1px 5px; border-radius: 3px;
  font-family: var(--font-mono); font-size: 12px;
}
.review-summary :deep(pre) {
  background: var(--page-canvas); border: 1px solid var(--surface-border);
  border-radius: var(--radius-md); padding: 10px 14px; overflow-x: auto;
  margin: 8px 0; font-size: 12px; line-height: 1.5;
}
.review-summary :deep(pre code) { background: none; padding: 0; }
.review-summary :deep(blockquote) {
  border-left: 3px solid var(--primary); padding: 4px 12px;
  margin: 8px 0; color: var(--muted-foreground); background: var(--surface-hover);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}
.review-summary :deep(table) { border-collapse: collapse; width: 100%; margin: 8px 0; }
.review-summary :deep(th), .review-summary :deep(td) {
  border: 1px solid var(--surface-border); padding: 6px 10px;
  text-align: left; font-size: 12px;
}
.review-summary :deep(th) { background: var(--surface-hover); font-weight: 600; }
.review-summary :deep(hr) { border: none; border-top: 1px solid var(--surface-border); margin: 12px 0; }
.review-summary :deep(strong) { font-weight: 700; }
.review-summary :deep(a) { color: var(--primary); }
.review-summary :deep(del) { text-decoration: line-through; opacity: 0.7; }

.empty-detail { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; background: var(--page-canvas); }
.empty-detail-icon { color: var(--muted-foreground); opacity: 0.5; }
.empty-detail p { font-size: 13px; color: var(--muted-foreground); }
</style>
