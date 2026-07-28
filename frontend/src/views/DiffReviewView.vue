<script setup lang="ts">
import {
  ref, onActivated, onDeactivated, onUnmounted, watch, computed,
} from 'vue'
import { useRoute } from 'vue-router'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import { useProjectStore } from '../stores/project'
import { useWebSocketStore } from '../stores/websocket'
import { useAuthStore } from '../stores/auth'
import DiffViewer from '../components/DiffViewer.vue'
import AuditChainPanel from '../components/AuditChainPanel.vue'
import QualityGatePanel from '../components/QualityGatePanel.vue'
import api, { getErrorMessage } from '../api'
import { renderMarkdown } from '../utils/markdown'

const store = useProjectStore()
const wsStore = useWebSocketStore()
const auth = useAuthStore()
const route = useRoute()

// 审计责任链弹窗
const chainVisible = ref(false)
function openChain() { chainVisible.value = true }

const selectedProjectId = computed(() => store.currentProject?.id ?? null)
const reviews = ref<any[]>([])
const selectedReview = ref<any>(null)
const loading = ref(false)
const voteSummary = ref<any>(null)
const voteComment = ref('')
const qualityGate = ref<any>(null)
const rejectingGate = ref(false)
const retryingGate = ref(false)

const statusLabels: Record<string, string> = {
  pending: '待审查', approved: '已通过', rejected: '已驳回',
}

let unsubReview: (() => void) | null = null
let unsubVote: (() => void) | null = null
let unsubGate: (() => void) | null = null
let pageActive = false

function subscribeRealtime() {
  if (unsubReview) return
  unsubReview = wsStore.on('review_update', (data: any) => {
    const pid = store.currentProject?.id
    if (pid && data.project_id === pid) {
      loadReviews()
    }
  })
  unsubVote = wsStore.on('review_vote_update', (data: any) => {
    if (selectedReview.value?.id === data.review_id) voteSummary.value = data
  })
  unsubGate = wsStore.on('quality_gate_update', (data: any) => {
    if (selectedReview.value?.task_id === data.task_id) qualityGate.value = data
  })
}

function unsubscribeRealtime() {
  unsubReview?.()
  unsubVote?.()
  unsubGate?.()
  unsubReview = null
  unsubVote = null
  unsubGate = null
}

onActivated(() => {
  pageActive = true
  subscribeRealtime()
  if (store.currentProject?.id) void loadReviews()
})
onDeactivated(() => {
  pageActive = false
  unsubscribeRealtime()
})
onUnmounted(unsubscribeRealtime)

watch(() => store.currentProject?.id, async (pid) => {
  if (!pid || !pageActive) return
  await loadReviews()
})

// The route instance is cached, so entity query changes must reload and select
// explicitly instead of relying on a component remount.
watch([() => route.query.review_id, () => route.query.task_id], async () => {
  if (route.path !== '/reviews') return
  await loadReviews()
})

watch(() => selectedReview.value?.id, async (reviewId) => {
  voteSummary.value = null
  voteComment.value = ''
  qualityGate.value = null
  if (!reviewId) return
  try {
    const [votes, gate] = await Promise.all([
      api.get(`/reviews/${reviewId}/votes`),
      api.get(`/reviews/${reviewId}/quality-gate`),
    ])
    voteSummary.value = votes.data
    qualityGate.value = gate.data
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '加载投票信息失败')) }
})

async function loadReviews() {
  if (!selectedProjectId.value) { reviews.value = []; return }
  try {
    const { data } = await api.get(
      `/projects/${selectedProjectId.value}/reviews`,
      { params: { page_size: 100 } },
    )
    reviews.value = data.items || data || []
    const targetReviewId = Number(route.query.review_id)
    const targetTaskId = Number(route.query.task_id)
    if (targetReviewId || targetTaskId) {
      let target = reviews.value.find((review: any) => (
        targetReviewId ? review.id === targetReviewId : review.task_id === targetTaskId
      ))
      if (!target && targetReviewId) {
        try {
          const { data: directReview } = await api.get(`/reviews/${targetReviewId}`)
          target = directReview
          reviews.value = [
            directReview,
            ...reviews.value.filter((review: any) => review.id !== directReview.id),
          ]
        } catch {
          target = null
        }
      }
      selectedReview.value = target || null
    } else if (selectedReview.value) {
      selectedReview.value =
        reviews.value.find((review: any) => review.id === selectedReview.value.id) || null
    }
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

async function rejectFailedQualityGate() {
  if (!selectedReview.value) return
  rejectingGate.value = true
  try {
    await api.post(`/reviews/${selectedReview.value.id}/reject-quality-gate`)
    MessagePlugin.warning('已将门禁失败明细打回，Agent 正在修改')
    await loadReviews()
    selectedReview.value = null
  } catch (e: any) {
    MessagePlugin.error(getErrorMessage(e, '打回 Agent 失败'))
  } finally {
    rejectingGate.value = false
  }
}

async function rerunQualityGate() {
  if (!selectedReview.value) return
  retryingGate.value = true
  try {
    const response = await api.post(`/reviews/${selectedReview.value.id}/rerun-quality-gate`)
    qualityGate.value = response.data
    MessagePlugin.success('确定性门禁已重新执行')
  } catch (e: any) {
    MessagePlugin.error(getErrorMessage(e, '重新执行门禁失败'))
  } finally {
    retryingGate.value = false
  }
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
            <div class="review-avatar" :class="`status-${r.status}`">
              <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <path d="M9 11l3 3 8-8"/>
                <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
              </svg>
            </div>
            <div class="review-item-body">
              <div class="review-item-header">
                <span class="review-id">审查 #{{ r.id }}</span>
                <span class="review-status" :class="r.status">
                  {{ statusLabels[r.status] || r.status }}
                </span>
              </div>
              <div class="review-item-meta">
                <span v-if="r.task_id">任务 #{{ r.task_id }}</span>
                <span class="review-item-time">{{ formatDate(r.created_at) }}</span>
              </div>
            </div>
            <svg class="review-item-arrow" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
              <polyline points="9 18 15 12 9 6"/>
            </svg>
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

          <div
            v-if="qualityGate || selectedReview.status === 'approved'"
            class="detail-section"
          >
            <h4 class="detail-label">审批前确定性门禁</h4>
            <QualityGatePanel
              :gate="qualityGate"
              :can-reject="selectedReview.status === 'pending' && qualityGate?.status === 'failed'"
              :can-retry="selectedReview.status === 'pending' && qualityGate?.status === 'failed'"
              :rejecting="rejectingGate"
              :retrying="retryingGate"
              @reject="rejectFailedQualityGate"
              @retry="rerunQualityGate"
            />
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
                <t-button
                  size="small"
                  theme="success"
                  variant="outline"
                  :disabled="loading || (qualityGate != null && qualityGate.status !== 'passed')"
                  @click="castVote('approve')"
                >投通过票</t-button>
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
  flex: 1;
  display: flex;
  gap: 14px;
  min-height: 0;
}

.review-list {
  width: 340px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 2px 4px 10px 2px;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.review-item {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 13px;
  padding: 15px 14px;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  background: var(--glass-surface-soft);
  box-shadow: var(--shadow-surface), var(--glass-highlight);
  cursor: pointer;
  overflow: hidden;
  transition:
    border-color var(--transition-base),
    background-color var(--transition-base),
    box-shadow var(--transition-base),
    transform var(--motion-base) var(--motion-ease-spring);
}
.review-item::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: var(--primary-gradient);
  opacity: 0;
  transform: scaleY(0.45);
  transition:
    opacity var(--transition-fast),
    transform var(--motion-base) var(--motion-ease-spring);
}
.review-item:hover {
  border-color: color-mix(in oklch, var(--primary) 48%, var(--glass-border));
  background: var(--glass-surface);
  box-shadow: var(--shadow-card-hover), var(--glass-highlight);
  transform: translateY(-2px);
}
.review-item.active {
  border-color: color-mix(in oklch, var(--primary) 58%, var(--glass-border));
  background:
    linear-gradient(115deg, var(--primary-light), transparent 62%),
    var(--glass-surface);
  box-shadow: 0 10px 28px var(--primary-glow), var(--glass-highlight);
}
.review-item.active::before {
  opacity: 1;
  transform: scaleY(1);
}
.review-avatar {
  width: 42px;
  height: 42px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  color: var(--primary);
  background: var(--primary-light);
  box-shadow: inset 0 0 0 1px color-mix(in oklch, var(--primary) 15%, transparent);
  transition:
    color var(--transition-fast),
    background-color var(--transition-fast),
    transform var(--motion-base) var(--motion-ease-spring);
}
.review-avatar.status-approved { color: var(--success); background: var(--success-light); }
.review-avatar.status-rejected { color: var(--danger); background: var(--danger-light); }
.review-avatar.status-pending { color: var(--warning); background: var(--warning-light); }
.review-item:hover .review-avatar { transform: scale(1.06) rotate(-2deg); }
.review-item-body { flex: 1; min-width: 0; }
.review-item-header { display: flex; justify-content: space-between; align-items: center; }
.review-id { font-size: 14px; font-weight: 650; color: var(--foreground); }
.review-status {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 10.5px;
  font-weight: 700;
  white-space: nowrap;
  color: var(--muted-foreground);
  background: var(--glass-surface-soft);
  border: 1px solid var(--glass-border);
}
.review-status.pending { color: var(--warning); background: var(--warning-light); border-color: transparent; }
.review-status.approved { color: var(--success); background: var(--success-light); border-color: transparent; }
.review-status.rejected { color: var(--danger); background: var(--danger-light); border-color: transparent; }
.review-item-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px 9px;
  margin-top: 7px;
  color: var(--muted-foreground);
  font-size: 11px;
}
.review-item-time {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.review-item-arrow {
  align-self: center;
  flex-shrink: 0;
  color: var(--muted-foreground);
  opacity: 0.55;
  transition:
    color var(--transition-fast),
    opacity var(--transition-fast),
    transform var(--motion-base) var(--motion-ease-spring);
}
.review-item:hover .review-item-arrow,
.review-item.active .review-item-arrow {
  color: var(--primary);
  opacity: 1;
  transform: translateX(2px);
}

.review-detail {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 20px 24px;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  background: var(--glass-surface);
  box-shadow: var(--shadow-surface), var(--glass-highlight);
  overscroll-behavior: contain;
}
.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--surface-border);
}
.detail-header h3 { font-size: 16px; font-weight: 700; margin: 0; }
.detail-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
.merge-queue-hint {
  display: inline-flex; align-items: center;
  padding: 0 8px; border-radius: var(--radius-sm);
  color: var(--success); background: var(--success-light);
  font-size: 12px;
}

.detail-section { margin-bottom: 20px; }
.detail-label { font-size: 13px; font-weight: 700; color: var(--muted-foreground); margin: 0 0 8px; text-transform: uppercase; letter-spacing: 0.5px; }

.diff-container {
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  overflow: hidden;
  max-height: 500px;
  overflow-y: auto;
  background: var(--glass-surface-soft);
}
.no-diff { font-size: 13px; color: var(--muted-foreground); padding: 20px; text-align: center; }

.vote-panel {
  margin: 0 0 16px; padding: 12px;
  border: 1px solid var(--glass-border); border-radius: var(--radius-md);
  background: var(--glass-surface-soft);
  box-shadow: var(--glass-highlight);
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
  background: var(--glass-surface-soft); border: 1px solid var(--glass-border);
  border-radius: var(--radius-md); padding: 16px 18px;
  box-shadow: var(--glass-highlight);
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

.empty-detail {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  background: var(--glass-surface-soft);
  box-shadow: var(--shadow-surface), var(--glass-highlight);
}
.empty-detail-icon { color: var(--muted-foreground); opacity: 0.5; }
.empty-detail p { font-size: 13px; color: var(--muted-foreground); }

.feedback-dialog-body { display: flex; flex-direction: column; gap: 10px; }
.feedback-hint { font-size: 13px; color: var(--muted-foreground); margin: 0; line-height: 1.5; }

@media (max-width: 900px) {
  .page-root {
    height: auto;
    min-height: 100%;
  }
  .review-layout {
    flex: none;
    flex-direction: column;
  }
  .review-list {
    width: 100%;
    max-height: none;
    padding-right: 2px;
    overflow: visible;
  }
  .review-detail {
    overflow: visible;
  }
  .empty-detail {
    min-height: 220px;
  }
}

@media (max-width: 640px) {
  .review-item {
    padding: 13px 12px;
  }
  .review-avatar {
    width: 38px;
    height: 38px;
  }
  .review-detail {
    padding: 16px;
  }
  .detail-header {
    align-items: flex-start;
    flex-direction: column;
  }
  .detail-actions {
    justify-content: flex-start;
  }
}
</style>
