<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import api from '../api'
import MemoryExplorer from '../components/MemoryExplorer.vue'
import { COLOR_THEME_OPTIONS, useThemeStore } from '../stores/theme'

interface SettingField {
  key: string
  label: string
  type: string
  value: string
  masked_value: string
  configured?: boolean
  options?: { value: string; label: string }[]
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
const theme = useThemeStore()

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

function setDarkMode(value: boolean) {
  if (theme.isDark !== value) theme.toggleDark()
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

    <div class="settings-card appearance-settings-card">
      <div class="card-header">
        <h3 class="card-title">外观与颜色</h3>
      </div>
      <div class="appearance-body">
        <div class="appearance-row">
          <div class="appearance-label">
            <strong>颜色主题</strong>
            <span>同步应用于按钮、导航、状态强调和背景光斑</span>
          </div>
          <div class="theme-options" role="radiogroup" aria-label="颜色主题">
            <button
              v-for="option in COLOR_THEME_OPTIONS"
              :key="option.key"
              type="button"
              class="theme-option"
              :class="{ active: theme.colorTheme === option.key }"
              :aria-checked="theme.colorTheme === option.key"
              role="radio"
              @click="theme.setColorTheme(option.key)"
            >
              <span class="theme-swatches" aria-hidden="true">
                <i :style="{ background: option.colors[0] }"></i>
                <i :style="{ background: option.colors[1] }"></i>
              </span>
              <span>{{ option.label }}</span>
              <svg
                v-if="theme.colorTheme === option.key"
                class="theme-check"
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2.5"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </button>
          </div>
        </div>
        <div class="appearance-row appearance-row--mode">
          <div class="appearance-label">
            <strong>显示模式</strong>
            <span>颜色主题可分别适配亮色与暗色界面</span>
          </div>
          <div class="mode-options" aria-label="显示模式">
            <button type="button" :class="{ active: !theme.isDark }" @click="setDarkMode(false)">亮色</button>
            <button type="button" :class="{ active: theme.isDark }" @click="setDarkMode(true)">暗色</button>
          </div>
        </div>
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

            <!-- Select -->
            <div v-else-if="field.type === 'select'" class="field-input-group">
              <div class="input-wrapper">
                <select
                  class="field-native-input field-select"
                  :value="edits[field.key] !== undefined ? edits[field.key] : field.value"
                  @change="onFieldInput(field, ($event.target as HTMLSelectElement).value)"
                >
                  <option v-for="opt in field.options" :key="opt.value" :value="opt.value">
                    {{ opt.label }}
                  </option>
                </select>
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
  max-width: 900px;
}

/* Appearance settings */
.appearance-settings-card { margin-bottom: 16px; }
.appearance-body { padding: 16px 20px 18px; }
.appearance-row {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.appearance-row + .appearance-row {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--glass-border);
}
.appearance-label {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
}
.appearance-label strong {
  color: var(--foreground);
  font-size: 13px;
  font-weight: 650;
}
.appearance-label span {
  color: var(--muted-foreground);
  font-size: 11px;
  text-align: right;
}
.theme-options {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}
.theme-option {
  min-width: 0;
  height: 46px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  background: var(--glass-surface-soft);
  color: var(--muted-foreground);
  font: 600 12px var(--font-sans);
  cursor: pointer;
  box-shadow: var(--glass-highlight);
  transition:
    color var(--transition-fast),
    border-color var(--transition-fast),
    background-color var(--transition-fast),
    box-shadow var(--transition-fast),
    transform var(--motion-fast) var(--motion-ease-spring);
}
.theme-option:hover {
  color: var(--foreground);
  border-color: color-mix(in oklch, var(--primary) 32%, var(--glass-border));
  transform: translateY(-1px);
}
.theme-option.active {
  color: var(--primary);
  border-color: color-mix(in oklch, var(--primary) 48%, var(--glass-border));
  background: var(--primary-light);
  box-shadow: 0 0 0 2px var(--primary-lighter), var(--glass-highlight);
}
.theme-swatches {
  width: 34px;
  height: 24px;
  position: relative;
  flex-shrink: 0;
}
.theme-swatches i {
  position: absolute;
  top: 3px;
  width: 20px;
  height: 20px;
  border: 2px solid color-mix(in oklch, var(--surface) 78%, transparent);
  border-radius: 50%;
  box-shadow: 0 3px 8px rgba(15, 23, 42, 0.16);
}
.theme-swatches i:first-child { left: 0; }
.theme-swatches i:last-child { right: 0; }
.theme-check { margin-left: auto; flex-shrink: 0; }
.mode-options {
  width: fit-content;
  display: inline-flex;
  gap: 3px;
  padding: 3px;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  background: var(--glass-surface-soft);
  box-shadow: var(--glass-highlight);
}
.mode-options button {
  min-width: 66px;
  padding: 6px 14px;
  border: 0;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--muted-foreground);
  font: 600 12px var(--font-sans);
  cursor: pointer;
  transition:
    color var(--transition-fast),
    background-color var(--transition-fast),
    box-shadow var(--transition-fast);
}
.mode-options button.active {
  color: var(--primary);
  background: var(--glass-surface-strong);
  box-shadow: var(--shadow-surface), inset 0 0 0 1px var(--primary-light);
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
  background: var(--glass-surface-soft);
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
  padding: 10px 8px;
  margin-inline: -8px;
  border-radius: var(--radius-md);
  transition: background-color var(--transition-fast);
}
.field-row + .field-row { border-top: 1px solid var(--surface-border); }
.field-row:hover { background: color-mix(in oklch, var(--surface-hover) 64%, transparent); }
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
  background: var(--glass-surface-soft);
  color: var(--foreground);
  font-size: 13px;
  font-family: var(--font-mono);
  outline: none;
  transition:
    border-color var(--transition-fast),
    box-shadow var(--transition-fast),
    background-color var(--transition-fast);
  box-sizing: border-box;
}
.field-native-input:focus {
  border-color: var(--primary);
  background: var(--glass-surface-strong);
  box-shadow: 0 0 0 3px var(--ring);
}
.field-native-input::placeholder { color: var(--muted-foreground); font-family: var(--font-sans); }

.field-select {
  appearance: none;
  -webkit-appearance: none;
  cursor: pointer;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23999' stroke-width='2' stroke-linecap='round'><path d='M6 9l6 6 6-6'/></svg>");
  background-repeat: no-repeat;
  background-position: right 10px center;
  padding-right: 28px;
}

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
  box-shadow: inset 0 0 0 1px color-mix(in oklch, var(--foreground) 8%, transparent);
  transition:
    background-color var(--transition-fast),
    box-shadow var(--transition-fast);
  flex-shrink: 0;
}
.toggle-slider::after {
  content: '';
  position: absolute; top: 2px; left: 2px;
  width: 18px; height: 18px;
  background: #fff;
  border-radius: 50%;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.22);
  transition: transform var(--motion-base) var(--motion-ease-spring);
}
.toggle-switch input:checked + .toggle-slider {
  background: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-light);
}
.toggle-switch input:checked + .toggle-slider::after {
  transform: translateX(18px);
}
.toggle-label {
  font-size: 13px; color: var(--muted-foreground);
  user-select: none;
}

@media (max-width: 560px) {
  .theme-options { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .appearance-label { flex-direction: column; gap: 3px; }
  .appearance-label span { text-align: left; }
}

</style>
