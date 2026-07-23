<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import api from '../api'
import { useAuthStore } from '../stores/auth'
import { getErrorMessage } from '../api'

const router = useRouter()
const auth = useAuthStore()

// 非系统管理员无权访问
if (!auth.isSystemAdmin) {
  router.replace('/dashboard')
}

interface AdminUser {
  id: number
  username: string
  display_name: string
  email: string
  project_count: number
  agent_count: number
  skill_count: number
}

interface PromoteForm {
  username: string
  is_system_admin: boolean
}

const tab = ref('users')
const users = ref<AdminUser[]>([])
const loading = ref(false)
const promoteForm = ref<PromoteForm>({ username: '', is_system_admin: true })
const systemAdminIds = ref<Set<number>>(new Set())
const promoteLoading = ref(false)

async function loadUsers() {
  loading.value = true
  try {
    const { data } = await api.get('/admin/users', { params: { limit: 200 } })
    users.value = data.items || []
  } catch (e) {
    MessagePlugin.error(getErrorMessage(e, '加载用户列表失败'))
  } finally {
    loading.value = false
  }
}

async function loadSystemAdmins() {
  // 通过 profile 接口无法批量查询，这里用 admin 接口逐个判断不可行。
  // 改为在前端维护：登录用户的 isSystemAdmin 已知，其他用户需通过
  // promote 接口的反向查询。当前简化为：只标记当前登录用户。
  // 后续可扩展后端增加 /admin/users?include_admin=true 返回该字段。
  systemAdminIds.value = new Set<number>(
    auth.userId ? [auth.userId] : []
  )
}

async function promoteAdmin() {
  if (!promoteForm.value.username.trim()) {
    MessagePlugin.warning('请输入用户名')
    return
  }
  promoteLoading.value = true
  try {
    await api.post('/auth/promote-admin', {
      username: promoteForm.value.username.trim(),
      is_system_admin: promoteForm.value.is_system_admin,
    })
    MessagePlugin.success(
      `${promoteForm.value.is_system_admin ? '已授予' : '已撤销'} ${promoteForm.value.username} 的系统管理员权限`
    )
    promoteForm.value = { username: '', is_system_admin: true }
    await loadUsers()
  } catch (e) {
    MessagePlugin.error(getErrorMessage(e, '授权失败'))
  } finally {
    promoteLoading.value = false
  }
}

async function deleteUser(userId: number, username: string) {
  if (!confirm(`确认删除账号「${username}」？此操作将级联删除其所有项目、Agent 和技能，且不可恢复。`)) return
  try {
    await api.delete(`/admin/users/${userId}`)
    MessagePlugin.success(`账号「${username}」已删除`)
    await loadUsers()
  } catch (e) {
    MessagePlugin.error(getErrorMessage(e, '删除失败'))
  }
}

const userStats = computed(() => ({
  total: users.value.length,
  withProjects: users.value.filter(u => u.project_count > 0).length,
  withAgents: users.value.filter(u => u.agent_count > 0).length,
}))

onMounted(() => {
  loadUsers()
  loadSystemAdmins()
})
</script>

<template>
  <div class="admin-console">
    <div class="page-header">
      <div>
        <h2 class="page-title">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          管理后台
        </h2>
        <p class="page-desc">
          系统管理员可在此管理账号、查看资源分布、授予系统管理员权限。所有操作均记入审计日志。
        </p>
      </div>
    </div>

    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-value">{{ userStats.total }}</div>
        <div class="stat-label">账号总数</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ userStats.withProjects }}</div>
        <div class="stat-label">拥有项目的账号</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ userStats.withAgents }}</div>
        <div class="stat-label">创建了 Agent 的账号</div>
      </div>
    </div>

    <div class="promote-card">
      <h3 class="card-title">授予/撤销系统管理员权限</h3>
      <div class="promote-form">
        <input
          v-model="promoteForm.username"
          class="promote-input"
          placeholder="目标用户名"
          @keyup.enter="promoteAdmin"
        />
        <label class="promote-switch">
          <input type="checkbox" v-model="promoteForm.is_system_admin" />
          <span>{{ promoteForm.is_system_admin ? '授予' : '撤销' }}</span>
        </label>
        <button class="btn-primary" :disabled="promoteLoading" @click="promoteAdmin">
          {{ promoteLoading ? '处理中…' : '执行' }}
        </button>
      </div>
      <p class="card-hint">
        授予后该账号可访问管理后台、修改银行化安全策略、配置模型白名单等。所有变更记入审计日志。
      </p>
    </div>

    <div class="users-card">
      <div class="card-header">
        <h3 class="card-title">账号列表</h3>
        <button class="btn-ghost" @click="loadUsers" :disabled="loading">
          {{ loading ? '加载中…' : '刷新' }}
        </button>
      </div>
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>用户名</th>
              <th>显示名</th>
              <th>邮箱</th>
              <th>项目数</th>
              <th>Agent 数</th>
              <th>技能数</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in users" :key="u.id">
              <td>{{ u.id }}</td>
              <td>
                {{ u.username }}
                <span v-if="systemAdminIds.has(u.id)" class="tag-admin">系统管理员</span>
              </td>
              <td>{{ u.display_name || '-' }}</td>
              <td>{{ u.email || '-' }}</td>
              <td>{{ u.project_count }}</td>
              <td>{{ u.agent_count }}</td>
              <td>{{ u.skill_count }}</td>
              <td>
                <button
                  v-if="u.id !== auth.userId"
                  class="btn-danger-sm"
                  @click="deleteUser(u.id, u.username)"
                >删除</button>
                <span v-else class="tag-self">当前账号</span>
              </td>
            </tr>
            <tr v-if="!loading && users.length === 0">
              <td colspan="8" class="empty-row">暂无账号</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.admin-console {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 24px;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 22px;
  font-weight: 700;
  margin: 0 0 6px;
  color: var(--foreground);
}

.page-desc {
  font-size: 13px;
  color: var(--muted-foreground);
  margin: 0;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  background: var(--surface);
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-md);
  padding: 18px 20px;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--primary);
  line-height: 1.2;
}

.stat-label {
  font-size: 12px;
  color: var(--muted-foreground);
  margin-top: 4px;
}

.promote-card,
.users-card {
  background: var(--surface);
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-md);
  padding: 20px;
  margin-bottom: 20px;
}

.card-title {
  font-size: 15px;
  font-weight: 600;
  margin: 0 0 14px;
  color: var(--foreground);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}

.card-header .card-title {
  margin: 0;
}

.promote-form {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

.promote-input {
  flex: 1;
  min-width: 200px;
  padding: 8px 12px;
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-sm);
  background: var(--background);
  color: var(--foreground);
  font-size: 13px;
  font-family: var(--font-sans);
}

.promote-input:focus {
  outline: none;
  border-color: var(--primary);
}

.promote-switch {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--foreground);
  cursor: pointer;
}

.btn-primary,
.btn-ghost {
  padding: 8px 16px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.btn-primary {
  background: var(--primary);
  color: var(--primary-foreground);
  border: 1px solid var(--primary);
}

.btn-primary:hover:not(:disabled) {
  background: var(--primary-hover);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-ghost {
  background: transparent;
  color: var(--foreground);
  border: 1px solid var(--surface-border);
}

.btn-ghost:hover:not(:disabled) {
  background: var(--surface-hover);
}

.card-hint {
  font-size: 12px;
  color: var(--muted-foreground);
  margin: 10px 0 0;
}

.table-wrap {
  overflow-x: auto;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.data-table th,
.data-table td {
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid var(--surface-border);
}

.data-table th {
  font-weight: 600;
  color: var(--muted-foreground);
  background: var(--surface-hover);
}

.data-table tbody tr:hover {
  background: var(--surface-hover);
}

.tag-admin {
  display: inline-block;
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 8px;
  font-size: 10px;
  font-weight: 600;
  background: var(--warning-light, #fff7e6);
  color: var(--warning, #d97706);
  border: 1px solid var(--warning, #d97706);
}

.tag-self {
  font-size: 11px;
  color: var(--muted-foreground);
}

.btn-danger-sm {
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  background: transparent;
  color: var(--danger);
  border: 1px solid var(--danger);
  cursor: pointer;
  font-family: var(--font-sans);
  transition: all var(--transition-fast);
}

.btn-danger-sm:hover {
  background: var(--danger);
  color: #fff;
}

.empty-row {
  text-align: center;
  color: var(--muted-foreground);
  padding: 32px;
}
</style>
