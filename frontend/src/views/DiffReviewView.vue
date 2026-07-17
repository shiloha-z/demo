<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import { useProjectStore } from '../stores/project'
import { useWebSocketStore } from '../stores/websocket'
import { useAuthStore } from '../stores/auth'
import DiffViewer from '../components/DiffViewer.vue'
import AuditChainPanel from '../components/AuditChainPanel.vue'
import api, { getErrorMessage } from '../api'
import { renderMarkdown } from '../utils/markdown'

const store = useProjectStore()
const wsStore = useWebSocketStore()
const auth = useAuthStore()

// 审计责任链弹窗
const chainVisible = ref(false)
function openChain() { chainVisible.value = true }

const selectedProjectId = computed(() => store.currentProject?.id ?? null)
const reviews = ref<any[]>([])
const selectedReview = ref<any>(null)
const loading = ref(false)
const voteSummary = ref<any>(null)
const voteComment = ref('')

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
  wsStore.on('review_vote_update', (data: any) => {
    if (selectedReview.value?.id === data.review_id) voteSummary.value = data
  })
})

onUnmounted(() => {
  if (unsubReview) unsubReview()
})

watch(() => store.currentProject?.id, async (pid) => {
  if (!pid) return
  await loadReviews()
}, { immediate: true })

watch(() => selectedReview.value?.id, async (reviewId) => {
  voteSummary.value = null
  voteComment.value = ''
  if (!reviewId) return
  try {
    const { data } = await api.get(`/reviews/${reviewId}/votes`)
    voteSummary.value = data
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '加载投票信息失败')) }
})

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

const canVote = computed(() => voteSummary.value?.reviewers?.some((r: any) => r.user_id === auth.userId))
const hasApprovalQuorum = computed(() => {
  const summary = voteSummary.value
  return Boolean(
    summary &&
    summary.approve_count >= summary.required_approvals &&
    summary.reject_count === 0,
  )
})
async function castVote(decision: 'approve' | 'reject') {
  if (!selectedReview.value) return
  loading.value = true
  try {
    const reviewId = selectedReview.value.id
    const { data } = await api.post(`/reviews/${reviewId}/vote`, {
      decision,
      comment: voteComment.value.trim(),
    })
    voteComment.value = ''
    if (data.queued_for_merge) {
      MessagePlugin.success('通过票数已满足，已自动进入项目合并队列')
      await loadReviews()
      if (selectedReview.value?.id === reviewId) selectedReview.value = null
      return
    }
    const votes = await api.get(`/reviews/${reviewId}/votes`)
    voteSummary.value = votes.data
    MessagePlugin.success(decision === 'approve' ? '已投通过票' : '已投驳回票')
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '投票失败')) }
  finally { loading.value = false }
}

const feedbackDialogVisible = ref(false)
const feedbackText = ref('')
const feedbackSubmitting = ref(false)

function openRejectDialog() {
  feedbackText.value = ''
  feedbackDialogVisible.value = true
}

async function submitRejectWithFeedback() {
  if (!selectedReview.value || !feedbackText.value.trim()) return
  feedbackSubmitting.value = true
  try {
    await api.post(`/reviews/${selectedReview.value.id}/reject`, {
      feedback: feedbackText.value.trim(),
    })
    MessagePlugin.warning('已驳回，Agent 将根据反馈重新执行')
    feedbackDialogVisible.value = false
    await loadReviews()
    selectedReview.value = null
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '操作失败')) }
  finally { feedbackSubmitting.value = false }
}

async function closeReview(review: any) {
  const confirmDialog = DialogPlugin.confirm({
    header: '确认结束',
    body: '确定要结束此审查吗？任务将被标记为驳回且不会重新执行。',
    confirmBtn: { content: '确认结束', theme: 'danger' },
    cancelBtn: '取消',
    onConfirm: async () => {
      loading.value = true
      try {
        await api.post(`/reviews/${review.id}/close`)
        MessagePlugin.warning('审查已结束')
        await loadReviews()
        if (selectedReview.value?.id === review.id) selectedReview.value = null
      } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '操作失败')) }
      finally { loading.value = false }
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
        <h1 class="page-title">审查记录</h1>
        <p class="page-desc">查看 Agent 代码审查结果，通过、驳回反馈或结束</p>
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
            <div class="detail-actions">
              <t-button size="small" theme="default" variant="outline" @click="openChain()">
                <template #icon>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/></svg>
                </template>
                责任链
              </t-button>
              <template v-if="selectedReview.status === 'pending'">
                <t-button size="small" theme="warning" variant="outline" :disabled="loading" @click="openRejectDialog">驳回并修改</t-button>
                <span v-if="hasApprovalQuorum" class="merge-queue-hint">通过票数已满足，正在进入合并队列</span>
                <t-button size="small" theme="default" variant="text" :disabled="loading" @click="closeReview(selectedReview)">结束</t-button>
              </template>
            </div>
          </div>

          <section v-if="voteSummary" class="vote-panel">
            <div class="vote-panel-header">
              <strong>多人投票</strong>
              <span>{{ voteSummary.approve_count }}/{{ voteSummary.required_approvals }} 通过</span>
              <span v-if="voteSummary.reject_count" class="vote-reject-count">{{ voteSummary.reject_count }} 驳回</span>
            </div>
            <div class="vote-reviewers">
              <div v-for="reviewer in voteSummary.reviewers" :key="reviewer.user_id" class="vote-reviewer">
                <span>{{ reviewer.display_name }}</span>
                <span :class="['vote-status', reviewer.vote || 'pending']">
                  {{ reviewer.vote === 'approve' ? '通过' : reviewer.vote === 'reject' ? '驳回' : '未投票' }}
                </span>
                <small v-if="reviewer.comment">{{ reviewer.comment }}</small>
              </div>
            </div>
            <div v-if="selectedReview.status === 'pending' && canVote" class="vote-actions">
              <t-textarea v-model="voteComment" placeholder="投票意见；驳回时必填" :autosize="{ minRows: 2, maxRows: 4 }" />
              <div class="vote-buttons">
                <t-button size="small" theme="success" variant="outline" :disabled="loading" @click="castVote('approve')">投通过票</t-button>
                <t-button size="small" theme="warning" variant="outline" :disabled="loading" @click="castVote('reject')">投驳回票</t-button>
              </div>
            </div>
            <p v-else-if="selectedReview.status === 'pending'" class="vote-hint">你不在本轮审查人名单中。</p>
          </section>

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

    <!-- Feedback dialog for reject-with-feedback -->
    <t-dialog v-model:visible="feedbackDialogVisible" header="驳回并反馈" width="480px" :confirm-btn="{ content: '提交反馈', theme: 'warning', loading: feedbackSubmitting }" :cancel-btn="{ content: '取消' }" @confirm="submitRejectWithFeedback">
      <div class="feedback-dialog-body">
        <p class="feedback-hint">请说明驳回原因和改进方向，Agent 将根据反馈重新执行此任务。</p>
        <t-textarea v-model="feedbackText" placeholder="例如：登录页面缺少密码强度校验、需要添加手机号验证码登录方式..." :autosize="{ minRows: 3, maxRows: 6 }" />
      </div>
    </t-dialog>

    <AuditChainPanel v-model:visible="chainVisible" :task-id="selectedReview?.task_id ?? null" />
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
.merge-queue-hint {
  display: inline-flex; align-items: center;
  padding: 0 8px; border-radius: var(--radius-sm);
  color: var(--success); background: var(--success-light);
  font-size: 12px;
}

.detail-section { margin-bottom: 20px; }
.detail-label { font-size: 13px; font-weight: 700; color: var(--muted-foreground); margin: 0 0 8px; text-transform: uppercase; letter-spacing: 0.5px; }

.diff-container { border: 1px solid var(--surface-border); border-radius: var(--radius-md); overflow: hidden; max-height: 500px; overflow-y: auto; }
.no-diff { font-size: 13px; color: var(--muted-foreground); padding: 20px; text-align: center; }

.vote-panel {
  margin: 0 0 16px; padding: 12px;
  border: 1px solid var(--surface-border); border-radius: var(--radius-md);
  background: var(--surface);
}
.vote-panel-header { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.vote-panel-header strong { margin-right: auto; }
.vote-reject-count { color: var(--danger); }
.vote-reviewers { margin-top: 10px; display: grid; gap: 6px; }
.vote-reviewer { display: grid; grid-template-columns: 1fr auto; gap: 8px; font-size: 12px; align-items: center; }
.vote-reviewer small { grid-column: 1 / -1; color: var(--muted-foreground); white-space: pre-wrap; }
.vote-status { padding: 1px 7px; border-radius: 99px; background: var(--surface-hover); color: var(--muted-foreground); }
.vote-status.approve { color: var(--success); background: var(--success-light); }
.vote-status.reject { color: var(--danger); background: var(--danger-light); }
.vote-actions { margin-top: 10px; }
.vote-buttons { display: flex; gap: 8px; margin-top: 8px; }
.vote-hint { margin: 10px 0 0; color: var(--muted-foreground); font-size: 12px; }

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

.feedback-dialog-body { display: flex; flex-direction: column; gap: 10px; }
.feedback-hint { font-size: 13px; color: var(--muted-foreground); margin: 0; line-height: 1.5; }
</style>
