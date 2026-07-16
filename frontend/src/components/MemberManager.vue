<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import { useAuthStore } from '../stores/auth'
import { useWebSocketStore } from '../stores/websocket'
import api, { getErrorMessage } from '../api'

const props = defineProps<{ projectId: number; projectName: string }>()
const emit = defineEmits<{ close: [] }>()

const auth = useAuthStore()
const wsStore = useWebSocketStore()

interface Member {
  id: number
  project_id: number
  user_id: number
  username: string
  display_name: string
  role: string
  joined_at: string | null
}

const members = ref<Member[]>([])
const loading = ref(false)
const isMember = ref(false)
const myRole = ref('')
const showAdd = ref(false)
const addUsername = ref('')
const addRole = ref('member')
const adding = ref(false)
const transferring = ref(false)
const transferUsername = ref('')
const showTransfer = ref(false)

// Join request state
const myRequest = ref<{ id: number; status: string } | null>(null)
const joinRequests = ref<any[]>([])
const requestLoading = ref(false)
const joining = ref(false)

const roleLabels: Record<string, string> = {
  owner: '项目主管',
  admin: '管理员',
  member: '一般成员',
}
const roleColors: Record<string, string> = {
  owner: 'var(--primary)',
  admin: 'var(--warning)',
  member: 'var(--success)',
}

const isOwner = computed(() => myRole.value === 'owner')
const isOwnerOrAdmin = computed(() => myRole.value === 'owner' || myRole.value === 'admin')
const canManage = computed(() => isOwnerOrAdmin.value)

const pendingRequests = computed(() =>
  joinRequests.value.filter(r => r.status === 'pending')
)
const pendingRequestCount = computed(() => pendingRequests.value.length)
const processedRequests = computed(() =>
  joinRequests.value.filter(r => r.status !== 'pending')
)

let unsubMember: (() => void) | null = null

onMounted(async () => {
  await loadAll()
  unsubMember = wsStore.on('member_update', (data: any) => {
    if (data.project_id === props.projectId) loadAll()
  })
})

onUnmounted(() => { unsubMember?.() })

async function loadAll() {
  loading.value = true
  try {
    // Try loading members (will 403 if not a member)
    const { data } = await api.get(`/projects/${props.projectId}/members`)
    members.value = Array.isArray(data) ? data : []
    const me = members.value.find(m => m.user_id === auth.userId)
    isMember.value = !!me
    myRole.value = me?.role || ''
  } catch (e: any) {
    // Not a member or no access
    isMember.value = false
    myRole.value = ''
    members.value = []
  }

  // Load my join request
  if (!isMember.value) {
    try {
      const { data } = await api.get(`/projects/${props.projectId}/my-request`)
      myRequest.value = data.request
    } catch { myRequest.value = null }
  }

  // Load join requests if owner/admin
  if (isOwnerOrAdmin.value) {
    await loadJoinRequests()
  }

  loading.value = false
}

async function loadJoinRequests() {
  requestLoading.value = true
  try {
    const { data } = await api.get(`/projects/${props.projectId}/join-requests`)
    joinRequests.value = Array.isArray(data) ? data : []
  } catch { joinRequests.value = [] }
  finally { requestLoading.value = false }
}

async function loadMembers() {
  loading.value = true
  try {
    const { data } = await api.get(`/projects/${props.projectId}/members`)
    members.value = Array.isArray(data) ? data : []
  } catch { /* ignore */ }
  finally { loading.value = false }
}

async function handleAdd() {
  if (!addUsername.value.trim()) return
  adding.value = true
  try {
    await api.post(`/projects/${props.projectId}/members`, {
      username: addUsername.value.trim(),
      role: addRole.value,
    })
    MessagePlugin.success(`已添加 ${addUsername.value}`)
    addUsername.value = ''
    addRole.value = 'member'
    showAdd.value = false
    await loadMembers()
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '添加失败')) }
  finally { adding.value = false }
}

async function changeRole(member: Member, newRole: string) {
  try {
    await api.put(`/projects/${props.projectId}/members/${member.user_id}`, { role: newRole })
    MessagePlugin.success(`已将 ${member.display_name || member.username} 设为 ${roleLabels[newRole]}`)
    await loadMembers()
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '操作失败')) }
}

function startTransfer(member: Member) {
  transferUsername.value = member.username
  showTransfer.value = true
}

async function removeMember(member: Member) {
  const name = member.display_name || member.username
  const confirmDialog = DialogPlugin.confirm({
    header: '确认移除',
    body: `确定要将「${name}」移出项目吗？`,
    confirmBtn: { content: '移除', theme: 'danger' },
    cancelBtn: '取消',
    onConfirm: async () => {
      try {
        await api.delete(`/projects/${props.projectId}/members/${member.user_id}`)
        MessagePlugin.success(`已移除 ${name}`)
        await loadMembers()
      } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '移除失败')) }
      confirmDialog.destroy()
    },
  })
}

async function leaveProject() {
  const confirmDialog = DialogPlugin.confirm({
    header: '确认离开',
    body: `确定要离开项目「${props.projectName}」吗？`,
    confirmBtn: { content: '离开', theme: 'danger' },
    cancelBtn: '取消',
    onConfirm: async () => {
      try {
        await api.delete(`/projects/${props.projectId}/members/${auth.userId}`)
        MessagePlugin.success('已离开项目')
        confirmDialog.destroy()
        emit('close')
      } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '操作失败')) }
      confirmDialog.destroy()
    },
  })
}

async function handleTransfer() {
  if (!transferUsername.value.trim()) return
  transferring.value = true
  try {
    await api.post(`/projects/${props.projectId}/transfer`, {
      new_owner_username: transferUsername.value.trim(),
    })
    MessagePlugin.success(`已转让给 ${transferUsername.value}`)
    transferUsername.value = ''
    showTransfer.value = false
    await loadMembers()
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '转让失败')) }
  finally { transferring.value = false }
}

async function requestJoin() {
  joining.value = true
  try {
    const { data } = await api.post(`/projects/${props.projectId}/join`)
    myRequest.value = { id: data.id, status: 'pending' }
    MessagePlugin.success('申请已提交，等待管理员审核')
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '申请失败')) }
  finally { joining.value = false }
}

async function approveRequest(req: any) {
  try {
    await api.post(`/projects/${props.projectId}/join-requests/${req.id}/approve`)
    MessagePlugin.success(`${req.username} 已加入项目`)
    await loadAll()
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '操作失败')) }
}

async function rejectRequest(req: any) {
  try {
    await api.post(`/projects/${props.projectId}/join-requests/${req.id}/reject`)
    MessagePlugin.success(`已拒绝 ${req.username}`)
    await loadAll()
  } catch (e: any) { MessagePlugin.error(getErrorMessage(e, '操作失败')) }
}

function formatDate(iso: string | null) {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
</script>

<template>
  <div class="member-manager">
    <!-- Header -->
    <div class="mm-header">
      <h3>成员管理 — {{ projectName }}</h3>
      <div class="mm-header-actions">
        <!-- Non-member: join button -->
        <template v-if="!loading && !isMember">
          <span v-if="myRequest?.status === 'pending'" class="mm-request-status pending">申请审核中...</span>
          <span v-else-if="myRequest?.status === 'rejected'" class="mm-request-status rejected">已被拒绝</span>
          <span v-else-if="myRequest?.status === 'approved'" class="mm-request-status approved">已通过</span>
          <t-button v-if="!myRequest || myRequest.status === 'rejected'" size="small" theme="primary" :loading="joining" @click="requestJoin">
            申请加入
          </t-button>
        </template>
        <!-- Member: manage buttons -->
        <template v-if="canManage">
          <t-button size="small" theme="primary" variant="outline" @click="showAdd = !showAdd">
            <template #icon>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            </template>
            添加成员
          </t-button>
          <t-button v-if="isOwner" size="small" variant="text" @click="showTransfer = !showTransfer">转让项目</t-button>
        </template>
      </div>
    </div>

    <!-- Add member form -->
    <div class="mm-add-form" v-if="showAdd">
      <t-input v-model="addUsername" placeholder="输入用户名" size="small" style="flex:1" @enter="handleAdd" />
      <t-select v-model="addRole" size="small" style="width:110px">
        <t-option value="admin" label="管理员" />
        <t-option value="member" label="一般成员" />
      </t-select>
      <t-button size="small" theme="primary" :loading="adding" @click="handleAdd">添加</t-button>
    </div>

    <!-- Transfer form -->
    <div class="mm-add-form" v-if="showTransfer">
      <t-input v-model="transferUsername" placeholder="输入接收者的用户名" size="small" style="flex:1" @enter="handleTransfer" />
      <t-button size="small" theme="warning" :loading="transferring" @click="handleTransfer">确认转让</t-button>
    </div>

    <!-- Pending join requests (owner/admin only) -->
    <div class="mm-section" v-if="isOwnerOrAdmin">
      <div class="mm-section-header">
        <span>待审核的加入申请</span>
        <span class="mm-badge" v-if="pendingRequestCount > 0">{{ pendingRequestCount }}</span>
      </div>
      <div v-if="pendingRequests.length === 0" class="mm-empty-sub">
        暂无待审核的申请
      </div>
      <div v-for="req in pendingRequests" :key="req.id" class="mm-request-row">
        <div class="mm-user">
          <span class="mm-avatar mm-avatar-sm">@</span>
          <span class="mm-name">{{ req.username }}</span>
        </div>
        <div class="mm-request-actions">
          <t-button size="small" theme="success" @click="approveRequest(req)">通过</t-button>
          <t-button size="small" theme="danger" variant="outline" @click="rejectRequest(req)">拒绝</t-button>
        </div>
      </div>
      <div v-if="processedRequests.length > 0" class="mm-processed">
        <div class="mm-section-header">已处理</div>
        <div v-for="req in processedRequests" :key="req.id" class="mm-processed-row">
          <span class="mm-name">{{ req.username }}</span>
          <span class="mm-request-status" :class="req.status">{{ req.status === 'approved' ? '已通过' : '已拒绝' }}</span>
        </div>
      </div>
    </div>

    <!-- Member list (only visible to members) -->
    <div class="mm-list" v-if="isMember" v-loading="loading">
      <div v-for="m in members" :key="m.id" class="mm-row">
        <div class="mm-user">
          <span class="mm-avatar" :style="{ background: roleColors[m.role] || 'var(--muted-foreground)' }">
            {{ (m.display_name || m.username).slice(0, 2).toUpperCase() }}
          </span>
          <div>
            <div class="mm-name">{{ m.display_name || m.username }}</div>
            <div class="mm-username">@{{ m.username }}</div>
          </div>
        </div>

        <span class="mm-role-tag" :style="{ color: roleColors[m.role] || 'var(--muted-foreground)' }">
          {{ roleLabels[m.role] || m.role }}
        </span>

        <span class="mm-date">{{ formatDate(m.joined_at) }}</span>

        <!-- Actions (for owner/admin, but can't change owner) -->
        <div class="mm-actions" v-if="canManage && m.role !== 'owner'">
          <t-dropdown :min-column-width="110" trigger="click">
            <t-button size="small" variant="text" shape="square" title="管理">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/></svg>
            </t-button>
            <t-dropdown-menu>
              <t-dropdown-item v-if="m.role !== 'admin'" @click="changeRole(m, 'admin')">设为管理员</t-dropdown-item>
              <t-dropdown-item v-if="m.role !== 'member'" @click="changeRole(m, 'member')">设为一般成员</t-dropdown-item>
              <t-dropdown-item v-if="isOwner" @click="startTransfer(m)">转让项目给此成员</t-dropdown-item>
              <t-dropdown-item theme="error" @click="removeMember(m)">移出项目</t-dropdown-item>
            </t-dropdown-menu>
          </t-dropdown>
        </div>

        <!-- Leave button for self (non-owner) -->
        <div class="mm-actions" v-if="m.user_id === auth.userId && m.role !== 'owner'">
          <t-button size="small" variant="text" theme="danger" @click="leaveProject">离开</t-button>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!loading && members.length === 0" class="mm-empty">
      暂无成员
    </div>
  </div>
</template>

<style scoped>
.member-manager {
  display: flex; flex-direction: column;
  min-height: 280px;
}

.mm-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 16px;
}
.mm-header h3 { font-size: 15px; font-weight: 700; margin: 0; }
.mm-header-actions { display: flex; gap: 8px; align-items: center; }

.mm-add-form {
  display: flex; gap: 8px; align-items: center;
  padding: 10px 14px; margin-bottom: 12px;
  background: var(--surface-hover); border-radius: var(--radius-md);
}

.mm-list { min-height: 120px; }

.mm-row {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--surface-border);
}
.mm-row:last-child { border-bottom: none; }

.mm-user { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; }
.mm-avatar {
  width: 36px; height: 36px; border-radius: var(--radius-md);
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; color: #fff; flex-shrink: 0;
}
.mm-name { font-size: 13px; font-weight: 600; color: var(--foreground); line-height: 1.2; }
.mm-username { font-size: 11px; color: var(--muted-foreground); }

.mm-role-tag {
  font-size: 11px; font-weight: 700; padding: 2px 8px;
  border-radius: 999px; white-space: nowrap;
  background: oklch(from currentColor 0.5 0.1 h / 0.1);
}

.mm-date { font-size: 11px; color: var(--muted-foreground); white-space: nowrap; }

.mm-actions { flex-shrink: 0; }

.mm-empty {
  flex: 1; display: flex; align-items: center; justify-content: center;
  font-size: 13px; color: var(--muted-foreground);
}

/* ── Join requests ─────────────────── */
.mm-section { margin-bottom: 16px; }
.mm-section-header {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; font-weight: 700; color: var(--muted-foreground);
  text-transform: uppercase; letter-spacing: 0.3px;
  margin-bottom: 8px; padding-bottom: 6px;
  border-bottom: 1px solid var(--surface-border);
}
.mm-badge {
  font-size: 10px; font-weight: 700;
  background: var(--danger); color: #fff;
  min-width: 18px; height: 18px; line-height: 18px;
  text-align: center; border-radius: 9px; padding: 0 5px;
}
.mm-empty-sub { font-size: 12px; color: var(--muted-foreground); padding: 8px 0; }

.mm-request-row, .mm-processed-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 0; border-bottom: 1px solid var(--surface-border);
}
.mm-request-row:last-child { border-bottom: none; }
.mm-request-actions { display: flex; gap: 6px; }

.mm-avatar-sm {
  width: 28px; height: 28px; font-size: 14px;
  background: var(--surface-hover); color: var(--muted-foreground);
}

.mm-request-status {
  font-size: 11px; font-weight: 600;
  padding: 1px 8px; border-radius: 999px;
}
.mm-request-status.pending {
  color: var(--warning);
  background: oklch(from var(--warning) 0.5 0.1 h / 0.1);
}
.mm-request-status.approved {
  color: var(--success);
  background: oklch(from var(--success) 0.5 0.1 h / 0.1);
}
.mm-request-status.rejected {
  color: var(--danger);
  background: oklch(from var(--danger) 0.5 0.1 h / 0.1);
}

.mm-processed { margin-top: 8px; }
.mm-processed .mm-section-header {
  font-size: 11px; text-transform: none; margin-bottom: 4px;
}
</style>
