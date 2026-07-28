<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import api, { getErrorMessage } from '../api'

interface Skill {
  id: number
  name: string
  description: string
  prompt_content: string
  source: string
  source_id: string
  source_url: string
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
const showSkillHubDialog = ref(false)
const showRemotePreview = ref(false)
const importInput = ref<HTMLInputElement | null>(null)
const importingFile = ref(false)
const remoteQuery = ref('')
const remoteSkills = ref<any[]>([])
const remoteLoading = ref(false)
const importingRemote = ref(false)
const selectedRemote = ref<any | null>(null)

onMounted(async () => { await loadSkills() })

async function loadSkills() {
  loading.value = true
  try {
    const { data } = await api.get('/skills')
    skills.value = data.items || data
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

function extractRemoteSkills(payload: any): any[] {
  if (Array.isArray(payload)) return payload
  for (const key of ['data', 'skills', 'results', 'items']) {
    if (Array.isArray(payload?.[key])) return payload[key]
  }
  return []
}

function remoteName(skill: any): string {
  return String(skill?.name || skill?.title || skill?.slug || skill?.id || 'Remote Skill')
}

function remoteDescription(skill: any): string {
  return String(skill?.description || skill?.summary || skill?.excerpt || '')
}

function remoteContent(skill: any): string {
  return String(skill?.skill_md || skill?.content || skill?.prompt_content || skill?.instructions || skill?.markdown || remoteDescription(skill))
}

function remoteId(skill: any): string {
  return String(skill?.id || skill?.slug || skill?.source_id || remoteName(skill))
}

function remoteUrl(skill: any): string {
  return String(skill?.url || skill?.source_url || skill?.github_url || '')
}

async function openSkillHubDialog() {
  showSkillHubDialog.value = true
  try {
    if (remoteSkills.value.length === 0) await loadSkillHubCatalog()
  } catch (e: any) {
    MessagePlugin.error(getErrorMessage(e, '无法连接 Agent Skills Hub'))
  }
}

async function loadSkillHubCatalog() {
  remoteLoading.value = true
  try {
    const { data } = await api.get('/skills/skillhub/catalog', { params: { limit: 20, sort: 'score' } })
    remoteSkills.value = extractRemoteSkills(data)
  } catch (e: any) {
    MessagePlugin.error(getErrorMessage(e, '加载 Agent Skills Hub 目录失败'))
  } finally {
    remoteLoading.value = false
  }
}

async function searchSkillHub() {
  if (remoteQuery.value.trim().length < 2) {
    MessagePlugin.warning('请输入至少两个字符')
    return
  }
  remoteLoading.value = true
  try {
    const { data } = await api.post('/skills/skillhub/search', { query: remoteQuery.value.trim(), limit: 20, method: 'hybrid' })
    remoteSkills.value = extractRemoteSkills(data)
  } catch (e: any) {
    MessagePlugin.error(getErrorMessage(e, '搜索 Agent Skills Hub 失败'))
  } finally {
    remoteLoading.value = false
  }
}

const previewContentLoading = ref(false)
const previewContent = ref('')

async function previewRemoteSkill(skill: any) {
  selectedRemote.value = skill
  previewContent.value = ''
  scanResult.value = null
  showRemotePreview.value = true
  // Fetch full SKILL.md content from Agent Skills Hub
  previewContentLoading.value = true
  try {
    const { data } = await api.get(`/skills/skillhub/content/${remoteId(skill)}`)
    previewContent.value = data.content || ''
    // Run security scan on the fetched content
    if (previewContent.value) {
      try {
        const scanResp = await api.post('/skills/scan-content', { name: remoteName(skill), content: previewContent.value })
        scanResult.value = scanResp.data
      } catch { scanResult.value = null }
    }
  } catch {
    previewContent.value = ''
  } finally {
    previewContentLoading.value = false
  }
}

const scanResult = ref<any>(null)
const severityLabels: Record<string, string> = {
  critical: '严重',
  high: '高危',
  medium: '中危',
  low: '低危',
}

async function importRemoteSkill() {
  if (!selectedRemote.value) return
  importingRemote.value = true
  try {
    await api.post('/skills/skillhub/import', {
      name: remoteName(selectedRemote.value),
      description: remoteDescription(selectedRemote.value),
      prompt_content: previewContent.value || remoteContent(selectedRemote.value),
      source_id: remoteId(selectedRemote.value),
      source_url: remoteUrl(selectedRemote.value),
    })
    MessagePlugin.success('已导入到本地技能仓库')
    showRemotePreview.value = false
    await loadSkills()
  } catch (e: any) {
    MessagePlugin.error(getErrorMessage(e, '导入技能失败'))
  } finally {
    importingRemote.value = false
  }
}

function truncate(text: string, maxLen: number): string {
  if (!text) return ''
  return text.length > maxLen ? text.slice(0, maxLen) + '…' : text
}

async function exportSkill(skill: Skill) {
  try {
    const { data } = await api.get(`/skills/${skill.id}/export`)
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${skill.name.replace(/[\\/:*?"<>|]/g, '_')}.skill.json`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    MessagePlugin.success('技能已导出')
  } catch (e: any) {
    MessagePlugin.error(getErrorMessage(e, '导出失败'))
  }
}

function openImportPicker() {
  importInput.value?.click()
}

async function importSkill(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  importingFile.value = true
  try {
    const payload = JSON.parse(await file.text())
    if (payload?.format !== 'skill-export' || payload?.version !== 1 || !payload?.skill) {
      throw new Error('请选择由本系统导出的技能 JSON 文件')
    }
    await api.post('/skills/import', payload)
    MessagePlugin.success('技能已导入')
    await loadSkills()
  } catch (e: any) {
    MessagePlugin.error(getErrorMessage(e, '导入失败'))
  } finally {
    importingFile.value = false
    input.value = ''
  }
}

function scanBadge(skill: any): { status: string; label: string } | null {
  if (!skill.security_scan_result) return null
  try {
    const r = typeof skill.security_scan_result === 'string' ? JSON.parse(skill.security_scan_result) : skill.security_scan_result
    if (r.status === 'safe') return { status: 'safe', label: '✅ 安全' }
    if (r.status === 'warning') return { status: 'warning', label: `⚠️ ${r.findings?.length || 0} 风险` }
    if (r.status === 'danger') return { status: 'danger', label: `🚫 ${r.critical_count || 0} 严重` }
  } catch { return null }
  return null
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
      <div class="header-actions">
        <input ref="importInput" type="file" accept=".skill.json,.json" style="display:none" @change="importSkill" />
        <t-button variant="outline" :loading="importingFile" @click="openImportPicker">
          <template #icon>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
          </template>
          导入技能
        </t-button>
        <t-button theme="primary" @click="openCreateDialog">
          <template #icon>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          </template>
          创建技能
        </t-button>
      </div>
    </div>

    <section class="external-source-card">
      <div>
        <strong>Agent Skills Hub</strong>
        <p>浏览 790+ 开源 Agent 技能，预览后导入为你的本地技能模板。</p>
      </div>
      <t-button variant="outline" @click="openSkillHubDialog">浏览 Agent Skills Hub</t-button>
    </section>

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
          <span v-if="scanBadge(s)" class="scan-card-badge" :class="'scan-card-' + scanBadge(s)!.status">{{ scanBadge(s)!.label }}</span>
        </div>

        <p v-if="s.description" class="skill-desc">{{ truncate(s.description, 120) }}</p>

        <div class="skill-prompt-preview">
          <pre>{{ truncate(s.prompt_content, 200) || '(无提示词内容)' }}</pre>
        </div>

        <div class="skill-card-footer">
          <span class="skill-time">{{ fmtTime(s.updated_at) }}</span>
          <div class="skill-actions">
            <t-button size="small" variant="text" @click="openEditDialog(s)">编辑</t-button>
            <t-button size="small" variant="text" @click="exportSkill(s)" title="导出">
              <template #icon>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
              </template>
            </t-button>
            <t-button size="small" variant="text" theme="danger" @click="deleteSkill(s)" title="删除">
              <template #icon>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
              </template>
            </t-button>
          </div>
        </div>
      </article>
    </div>

    <t-dialog v-model:visible="showSkillHubDialog" header="从 Agent Skills Hub 导入技能" width="760px" :footer="false">
      <div class="remote-search-row">
        <t-input v-model="remoteQuery" placeholder="搜索技能，例如：PDF processing" @enter="searchSkillHub" />
        <t-button theme="primary" :loading="remoteLoading" @click="searchSkillHub">搜索</t-button>
      </div>
      <div v-if="remoteLoading" class="remote-empty">正在加载技能…</div>
      <div v-else-if="remoteSkills.length === 0" class="remote-empty">未找到可导入的技能。</div>
      <div v-else class="remote-skill-list">
        <article v-for="skill in remoteSkills" :key="remoteId(skill)" class="remote-skill-item">
          <div>
            <h4>{{ remoteName(skill) }}</h4>
            <p>{{ truncate(remoteDescription(skill), 220) || '暂无简介。' }}</p>
          </div>
          <t-button size="small" variant="outline" @click="previewRemoteSkill(skill)">预览并导入</t-button>
        </article>
      </div>
    </t-dialog>

      <t-dialog v-model:visible="showRemotePreview" header="预览技能" width="760px" :footer="false">
      <template v-if="selectedRemote">
        <div class="remote-preview-meta">
          <strong>{{ remoteName(selectedRemote) }}</strong>
          <a v-if="remoteUrl(selectedRemote)" :href="remoteUrl(selectedRemote)" target="_blank" rel="noreferrer">查看来源</a>
        </div>
        <div v-if="previewContentLoading" class="remote-empty">正在加载技能详情…</div>
        <pre v-else class="remote-preview-content">{{ previewContent || remoteContent(selectedRemote) || '未返回完整内容；将导入当前简介。' }}</pre>
        <!-- Security scan result -->
        <div v-if="scanResult" class="scan-result" :class="'scan-' + scanResult.status">
          <div class="scan-result-header">
            <span v-if="scanResult.status === 'safe'" class="scan-badge safe">✅ 安全检测通过</span>
            <span v-else-if="scanResult.status === 'warning'" class="scan-badge warning">⚠️ 发现 {{ scanResult.findings.length }} 个风险项</span>
            <span v-else class="scan-badge danger">🚫 发现 {{ scanResult.critical_count }} 个严重风险</span>
          </div>
          <div v-if="scanResult.findings.length > 0" class="scan-findings">
            <div v-for="(f, i) in scanResult.findings.slice(0, 5)" :key="i" class="scan-finding-item" :class="'sev-' + f.severity">
              <span class="sev-tag">{{ severityLabels[String(f.severity)] || f.severity }}</span>
              <span class="finding-msg">{{ f.message }}</span>
              <span v-if="f.line" class="finding-line">L{{ f.line }}</span>
            </div>
            <div v-if="scanResult.findings.length > 5" class="scan-more">另有 {{ scanResult.findings.length - 5 }} 项未展示</div>
          </div>
        </div>
        <div class="dialog-footer">
          <t-button theme="default" variant="text" @click="showRemotePreview = false">取消</t-button>
          <t-button theme="primary" :loading="importingRemote" @click="importRemoteSkill">导入到本地仓库</t-button>
        </div>
      </template>
    </t-dialog>

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
.header-actions { display: flex; align-items: center; gap: 8px; }

.page-root { max-width: 1000px; }

.external-source-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  padding: 14px 18px;
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg);
  background: var(--surface);
}
.external-source-card strong { font-size: 14px; }
.external-source-card p { margin: 4px 0 0; color: var(--muted-foreground); font-size: 13px; }
.remote-search-row { display: flex; gap: 8px; margin-bottom: 14px; }
.remote-skill-list { display: flex; flex-direction: column; gap: 8px; max-height: 420px; overflow: auto; }
.remote-skill-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px;
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-md);
}
.remote-skill-item h4 { margin: 0; font-size: 14px; }
.remote-skill-item p { margin: 5px 0 0; color: var(--muted-foreground); font-size: 12px; line-height: 1.5; }
.remote-empty { padding: 24px; text-align: center; color: var(--muted-foreground); }
.remote-preview-meta { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.remote-preview-meta a { color: var(--primary); font-size: 13px; }
.remote-preview-content {
  max-height: 420px;
  margin: 0;
  padding: 12px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-md);
  background: var(--page-canvas);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.5;
}

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
  background:
    linear-gradient(145deg, var(--primary-light), var(--glass-surface-strong));
  color: var(--primary);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: 1px solid color-mix(in oklch, var(--primary) 14%, var(--glass-border));
  box-shadow: var(--glass-highlight);
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
  background: var(--glass-surface-soft);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  max-height: 80px;
  overflow: hidden;
  box-shadow: inset 0 1px 8px color-mix(in oklch, var(--foreground) 3%, transparent);
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

/* ── Security scan results ───────────────────────────────────────── */
.scan-result {
  margin: 10px 0 0;
  border-radius: var(--radius-md);
  overflow: hidden;
}
.scan-result.scan-safe { border: 1px solid #22c55e33; background: #22c55e0d; }
.scan-result.scan-warning { border: 1px solid #eab30833; background: #eab3080d; }
.scan-result.scan-danger { border: 1px solid #ef444433; background: #ef44440d; }

.scan-result-header {
  padding: 8px 12px;
  font-size: 13px;
  font-weight: 600;
}
.scan-badge.safe { color: #16a34a; }
.scan-badge.warning { color: #ca8a04; }
.scan-badge.danger { color: #dc2626; }

.scan-findings { padding: 0 12px 8px; }
.scan-finding-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 12px;
  border-bottom: 1px solid var(--surface-border);
}
.scan-finding-item:last-child { border-bottom: none; }

.sev-tag {
  display: inline-block;
  padding: 0 4px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.sev-critical .sev-tag { color: #dc2626; background: #dc262622; }
.sev-high .sev-tag { color: #ea580c; background: #ea580c22; }
.sev-medium .sev-tag { color: #ca8a04; background: #ca8a0422; }
.sev-low .sev-tag { color: #6b7280; background: #6b728022; }

.finding-msg { flex: 1; color: var(--foreground); }
.finding-line { color: var(--muted-foreground); font-size: 11px; }
.scan-more { padding: 4px 0 0; font-size: 11px; color: var(--muted-foreground); }

/* ── Scan badge on skill cards ──────────────────────────────────── */
.scan-card-badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 10px;
  font-size: 11px;
  white-space: nowrap;
  flex-shrink: 0;
}
.scan-card-safe { color: #16a34a; background: #22c55e18; }
.scan-card-warning { color: #ca8a04; background: #eab30818; }
.scan-card-danger { color: #dc2626; background: #ef444418; }
</style>
