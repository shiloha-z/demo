<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import api from '../api'
import MemoryExplorer from '../components/MemoryExplorer.vue'

interface SettingField {
  key: string
  label: string
  type: string
  value: string
  masked_value: string
  configured?: boolean
}

interface SettingSection {
  key: string
  label: string
  fields: SettingField[]
}

const sections = ref<SettingSection[]>([])
const loading = ref(false)
// Track edited values per field key before saving
const edits = reactive<Record<string, string>>({})
const saving = reactive<Record<string, boolean>>({})
const showPassword = reactive<Record<string, boolean>>({})

onMounted(async () => {
  await loadSettings()
})

async function loadSettings() {
  loading.value = true
  try {
    const { data } = await api.get('/settings')
    sections.value = data.sections
  } catch {
    MessagePlugin.error('加载设置失败')
  } finally {
    loading.value = false
  }
}

function getDisplayValue(field: SettingField): string {
  // If there's a pending edit, show it; otherwise show the masked/raw value
  if (edits[field.key] !== undefined) return edits[field.key]
  return field.type === 'password' ? field.masked_value : field.value
}

function onFieldInput(field: SettingField, rawValue: string) {
  edits[field.key] = rawValue
}

function isModified(field: SettingField): boolean {
  if (field.type === 'password') return edits[field.key] !== undefined && edits[field.key].length > 0
  return edits[field.key] !== undefined && edits[field.key] !== field.value
}

async function saveField(field: SettingField) {
  const newValue = edits[field.key]
  if (newValue === undefined || newValue === field.value) return

  saving[field.key] = true
  try {
    await api.post('/settings', { key: field.key, value: newValue })
    MessagePlugin.success(`「${field.label}」已保存`)
    // Update local state to reflect saved value
    field.value = field.type === 'password' ? '' : newValue
    field.configured = field.type === 'password' ? Boolean(newValue) : field.configured
    if (field.type === 'password') {
      // Re-mask: show first 4 + **** + last 4
      const v = newValue
      field.masked_value = v.length <= 8 ? v.slice(0, 2) + '****' + v.slice(-2) : v.slice(0, 4) + '****' + v.slice(-4)
    }
    delete edits[field.key]
  } catch (e: any) {
    MessagePlugin.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving[field.key] = false
  }
}

function togglePasswordVisibility(fieldKey: string) {
  showPassword[fieldKey] = !showPassword[fieldKey]
}
</script>

<template>
  <div class="page-root">
    <div class="page-header">
      <div>
        <h1 class="page-title">系统设置</h1>
        <p class="page-desc">配置 API 密钥、端点地址和工作空间路径</p>
      </div>
    </div>

    <div v-if="loading" class="empty-card">
      <p>加载设置中...</p>
    </div>

    <div v-else class="settings-grid">
      <div v-for="section in sections" :key="section.key" class="settings-card">
        <div class="card-header">
          <h3 class="card-title">{{ section.label }}</h3>
        </div>
        <div class="card-body">
          <div v-for="field in section.fields" :key="field.key" class="field-row">
            <label class="field-label">{{ field.label }}</label>

            <!-- Boolean toggle -->
            <div v-if="field.type === 'boolean'" class="field-input-group">
              <label class="toggle-switch">
                <input
                  type="checkbox"
                  :checked="edits[field.key] !== undefined ? edits[field.key] === 'true' : field.value === 'true'"
                  @change="onFieldInput(field, ($event.target as HTMLInputElement).checked ? 'true' : 'false')"
                />
                <span class="toggle-slider"></span>
                <span class="toggle-label">{{ (edits[field.key] !== undefined ? edits[field.key] : field.value) === 'true' ? '已开启' : '已关闭' }}</span>
              </label>
              <t-button
                size="small"
                variant="outline"
                :disabled="!isModified(field)"
                :loading="saving[field.key]"
                @click="saveField(field)"
              >
                保存
              </t-button>
            </div>

            <!-- Text / Password -->
            <div v-else class="field-input-group">
              <div class="input-wrapper" :class="{ 'is-password': field.type === 'password' }">
                <input
                  v-if="field.type === 'password'"
                  :type="showPassword[field.key] ? 'text' : 'password'"
                  class="field-native-input"
                  :value="getDisplayValue(field)"
                  :placeholder="field.value ? '(已配置)' : '点击输入...'"
                  @input="onFieldInput(field, ($event.target as HTMLInputElement).value)"
                />
                <input
                  v-else
                  type="text"
                  class="field-native-input"
                  :value="getDisplayValue(field)"
                  placeholder="输入值..."
                  @input="onFieldInput(field, ($event.target as HTMLInputElement).value)"
                />
                <button
                  v-if="field.type === 'password' && field.value"
                  class="toggle-vis-btn"
                  type="button"
                  :title="showPassword[field.key] ? '隐藏' : '显示'"
                  @click="togglePasswordVisibility(field.key)"
                >
                  <svg v-if="showPassword[field.key]" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
                  <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                </button>
              </div>
              <t-button
                size="small"
                variant="outline"
                :disabled="!isModified(field)"
                :loading="saving[field.key]"
                @click="saveField(field)"
              >
                保存
              </t-button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Global Memory Viewer -->
    <div class="settings-card memory-settings-card">
      <MemoryExplorer
        scope="global"
        title="全局记忆"
        empty-hint="Agent 会将跨项目可复用的工程经验、安全模式和失败教训沉淀在这里。"
      />
    </div>
  </div>
</template>

<style scoped>
.page-root {
  /* The shared page shell uses height: 100% for split-pane screens. Settings
     is a document-flow page, so a fixed flex height would shrink the final
     memory card to its borders and clip the explorer via overflow: hidden. */
  height: auto;
  min-height: 100%;
  max-width: 720px;
}

/* ── Settings cards ──────────────────────────────────────────────────── */
.settings-grid { display: flex; flex-direction: column; gap: 16px; }
.settings-card {
  flex-shrink: 0;
  background: var(--surface);
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-surface);
  overflow: hidden;
}
.memory-settings-card { margin-top: 24px; }
.card-header {
  padding: 14px 20px;
  border-bottom: 1px solid var(--surface-border);
  background: var(--surface-hover);
}
.card-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--foreground);
}
.card-body { padding: 12px 20px 18px; }

/* ── Field row ───────────────────────────────────────────────────────── */
.field-row {
  display: flex; align-items: center; gap: 14px;
  padding: 10px 0;
}
.field-row + .field-row { border-top: 1px solid var(--surface-border); }
.field-label {
  width: 160px; flex-shrink: 0;
  font-size: 13px; font-weight: 500;
  color: var(--foreground);
}
.field-input-group {
  display: flex; align-items: center; gap: 8px;
  flex: 1; min-width: 0;
}
.input-wrapper {
  flex: 1; min-width: 0;
  position: relative;
}
.field-native-input {
  width: 100%;
  padding: 7px 10px;
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-md);
  background: var(--page-canvas);
  color: var(--foreground);
  font-size: 13px;
  font-family: var(--font-mono);
  outline: none;
  transition: border-color var(--transition-fast);
  box-sizing: border-box;
}
.field-native-input:focus { border-color: var(--primary); box-shadow: 0 0 0 2px var(--ring); }
.field-native-input::placeholder { color: var(--muted-foreground); font-family: var(--font-sans); }

.is-password .field-native-input {
  padding-right: 32px;
}
.toggle-vis-btn {
  position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
  width: 26px; height: 26px;
  display: flex; align-items: center; justify-content: center;
  border: none; background: transparent;
  color: var(--muted-foreground);
  cursor: pointer; border-radius: var(--radius-sm);
  transition: all var(--transition-fast);
}
.toggle-vis-btn:hover { color: var(--foreground); background: var(--surface-hover); }

/* ── Boolean toggle switch ──────────────────────────────────────────── */
.toggle-switch {
  display: flex; align-items: center; gap: 10px; cursor: pointer;
  position: relative;
}
.toggle-switch input { display: none; }
.toggle-slider {
  width: 40px; height: 22px;
  background: var(--surface-border);
  border-radius: 11px;
  position: relative;
  transition: background var(--transition-fast);
  flex-shrink: 0;
}
.toggle-slider::after {
  content: '';
  position: absolute; top: 2px; left: 2px;
  width: 18px; height: 18px;
  background: #fff;
  border-radius: 50%;
  transition: transform var(--transition-fast);
}
.toggle-switch input:checked + .toggle-slider {
  background: var(--primary);
}
.toggle-switch input:checked + .toggle-slider::after {
  transform: translateX(18px);
}
.toggle-label {
  font-size: 13px; color: var(--muted-foreground);
  user-select: none;
}

</style>
