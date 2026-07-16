<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import api, { getErrorMessage } from '../api'

interface Skill {
  id: number
  name: string
  description: string
  prompt_content: string
  created_at: string | null
  updated_at: string | null
}

const skills = ref<Skill[]>([])
const loading = ref(false)

// Dialog state
const showCreateDialog = ref(false)
const showEditDialog = ref(false)
const editingSkill = ref<Skill | null>(null)
const formData = ref({ name: '', description: '', prompt_content: '' })
const saving = ref(false)
const currentTab = ref<'cards' | 'table'>('cards')

onMounted(async () => { await loadSkills() })

async function loadSkills() {
  loading.value = true
  try {
    const { data } = await api.get('/skills')
    skills.value = data
  } catch (e: any) {
    MessagePlugin.error(getErrorMessage(e, '加载技能列表失败'))
  } finally {
    loading.value = false
  }
}

function openCreateDialog() {
  formData.value = { name: '', description: '', prompt_content: '' }
  showCreateDialog.value = true
}

function openEditDialog(skill: Skill) {
  editingSkill.value = skill
  formData.value = {
    name: skill.name,
    description: skill.description,
    prompt_content: skill.prompt_content,
  }
  showEditDialog.value = true
}

async function createSkill() {
  if (!formData.value.name.trim()) return
  saving.value = true
  try {
    await api.post('/skills', formData.value)
    MessagePlugin.success('技能已创建')
    showCreateDialog.value = false
    await loadSkills()
  } catch (e: any) {
    MessagePlugin.error(getErrorMessage(e, '创建失败'))
  } finally {
    saving.value = false
  }
}

async function updateSkill() {
  if (!editingSkill.value || !formData.value.name.trim()) return
  saving.value = true
  try {
    await api.put(`/skills/${editingSkill.value.id}`, formData.value)
    MessagePlugin.success('技能已更新')
    showEditDialog.value = false
    editingSkill.value = null
    await loadSkills()
  } catch (e: any) {
    MessagePlugin.error(getErrorMessage(e, '更新失败'))
  } finally {
    saving.value = false
  }
}

async function deleteSkill(skill: Skill) {
  const confirmDialog = DialogPlugin.confirm({
    header: '确认删除',
    body: `确定要删除技能「${skill.name}」吗？此操作不可撤销。`,
    confirmBtn: { content: '删除', theme: 'danger' },
    cancelBtn: '取消',
    onConfirm: async () => {
      try {
        await api.delete(`/skills/${skill.id}`)
        MessagePlugin.success('技能已删除')
        await loadSkills()
      } catch (e: any) {
        MessagePlugin.error(getErrorMessage(e, '删除失败'))
      }
      confirmDialog.destroy()
    },
  })
}

function truncate(text: string, maxLen: number): string {
  if (!text) return ''
  return text.length > maxLen ? text.slice(0, maxLen) + '…' : text
}

function fmtTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <div class="page-root">
    <div class="page-header">
      <div>
        <h1 class="page-title">技能仓库</h1>
        <p class="page-desc">管理可复用的 Agent 提示词模板，创建 Agent 时可一键加载</p>
      </div>
      <t-button theme="primary" @click="openCreateDialog">
        <template #icon>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        </template>
        创建技能
      </t-button>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="empty-card">
      <div class="loading-spinner"></div>
      <p>加载中...</p>
    </div>

    <!-- Empty state -->
    <div v-else-if="skills.length === 0" class="empty-card">
      <div class="empty-icon">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
      </div>
      <h3>暂无技能</h3>
      <p>创建可复用的提示词模板，在创建 Agent 时快速加载</p>
      <t-button theme="primary" variant="outline" @click="openCreateDialog">创建第一个技能</t-button>
    </div>

    <!-- Skill cards grid -->
    <div v-else class="skill-grid">
      <article v-for="s in skills" :key="s.id" class="skill-card">
        <div class="skill-card-header">
          <div class="skill-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
          </div>
          <h3 class="skill-name">{{ s.name }}</h3>
        </div>

        <p v-if="s.description" class="skill-desc">{{ truncate(s.description, 120) }}</p>

        <div class="skill-prompt-preview">
          <pre>{{ truncate(s.prompt_content, 200) || '(无提示词内容)' }}</pre>
        </div>

        <div class="skill-card-footer">
          <span class="skill-time">{{ fmtTime(s.updated_at) }}</span>
          <div class="skill-actions">
            <t-button size="small" variant="text" @click="openEditDialog(s)">编辑</t-button>
            <t-button size="small" variant="text" theme="danger" @click="deleteSkill(s)" title="删除">
              <template #icon>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
              </template>
            </t-button>
          </div>
        </div>
      </article>
    </div>

    <!-- Create Dialog -->
    <t-dialog v-model:visible="showCreateDialog" header="创建技能" width="520px" :footer="false">
      <div class="dialog-form">
        <label class="field-label">名称 <span class="required">*</span></label>
        <t-input v-model="formData.name" placeholder="例如：代码生成专家" maxlength="100" />

        <label class="field-label">描述</label>
        <t-textarea v-model="formData.description" placeholder="简要描述该技能的用途..." :autosize="{ minRows: 2, maxRows: 4 }" />

        <label class="field-label">提示词内容</label>
        <t-textarea
          v-model="formData.prompt_content"
          placeholder="编写可复用的系统提示词模板，创建 Agent 时可一键加载..."
          :autosize="{ minRows: 6, maxRows: 14 }"
        />
      </div>
      <div class="dialog-footer">
        <t-button theme="default" variant="text" @click="showCreateDialog = false">取消</t-button>
        <t-button theme="primary" :disabled="!formData.name.trim()" :loading="saving" @click="createSkill">创建</t-button>
      </div>
    </t-dialog>

    <!-- Edit Dialog -->
    <t-dialog v-model:visible="showEditDialog" header="编辑技能" width="520px" :footer="false">
      <div class="dialog-form">
        <label class="field-label">名称 <span class="required">*</span></label>
        <t-input v-model="formData.name" placeholder="技能名称" maxlength="100" />

        <label class="field-label">描述</label>
        <t-textarea v-model="formData.description" placeholder="简要描述该技能的用途..." :autosize="{ minRows: 2, maxRows: 4 }" />

        <label class="field-label">提示词内容</label>
        <t-textarea
          v-model="formData.prompt_content"
          placeholder="编写可复用的系统提示词模板..."
          :autosize="{ minRows: 6, maxRows: 14 }"
        />
      </div>
      <div class="dialog-footer">
        <t-button theme="default" variant="text" @click="showEditDialog = false">取消</t-button>
        <t-button theme="primary" :disabled="!formData.name.trim()" :loading="saving" @click="updateSkill">保存</t-button>
      </div>
    </t-dialog>
  </div>
</template>

<style scoped>
.page-root { max-width: 1000px; }

/* ── Skill cards grid ──────────────────────────────────────────────── */
.skill-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 10px;
}

.skill-card {
  background: var(--surface);
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-surface);
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: border-color var(--transition-base), box-shadow var(--transition-base), transform var(--transition-base);
}

.skill-card:hover {
  border-color: var(--primary);
  box-shadow: var(--shadow-card-hover);
  transform: translateY(-1px);
}

.skill-card-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.skill-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background: var(--primary-light);
  color: var(--primary);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.skill-name {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--foreground);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.skill-desc {
  margin: 0;
  font-size: 13px;
  color: var(--muted-foreground);
  line-height: 1.5;
}

.skill-prompt-preview {
  background: var(--page-canvas);
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  max-height: 80px;
  overflow: hidden;
}

.skill-prompt-preview pre {
  margin: 0;
  font-size: 12px;
  font-family: var(--font-mono);
  color: var(--muted-foreground);
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.skill-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
}

.skill-time {
  font-size: 11px;
  color: var(--muted-foreground);
  opacity: 0.7;
}

.skill-actions {
  display: flex;
  gap: 2px;
}

/* ── Dialog ─────────────────────────────────────────────────── */
.required {
  color: var(--danger);
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
</style>
