<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../stores/auth'
import api from '../api'

const auth = useAuthStore()

const displayName = ref(auth.displayName || '')
const saving = ref(false)
const message = ref('')

async function saveProfile() {
  saving.value = true
  message.value = ''
  try {
    await api.put('/auth/profile', { display_name: displayName.value })
    auth.updateDisplayName(displayName.value)
    message.value = '保存成功'
  } catch {
    message.value = '保存失败，请重试'
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  displayName.value = auth.displayName || ''
})
</script>

<template>
  <div class="profile-page">
    <div class="profile-card">
      <div class="profile-header">
        <div class="profile-avatar">{{ auth.displayName?.charAt(0) || '?' }}</div>
        <div>
          <h2 class="profile-name">{{ auth.displayName }}</h2>
          <p class="profile-username">@{{ auth.username }}</p>
        </div>
      </div>

      <div class="profile-form">
        <label class="profile-field">
          <span class="profile-field-label">显示名称</span>
          <input
            v-model="displayName"
            type="text"
            class="profile-input"
            maxlength="50"
            placeholder="输入显示名称"
          />
        </label>

        <button class="profile-save-btn" :disabled="saving" @click="saveProfile">
          {{ saving ? '保存中...' : '保存修改' }}
        </button>

        <p v-if="message" class="profile-message" :class="{ error: message.includes('失败') }">
          {{ message }}
        </p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.profile-page {
  max-width: 560px;
  margin: 0 auto;
}

.profile-card {
  background: var(--surface);
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.profile-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 28px;
  background: var(--surface-hover);
  border-bottom: 1px solid var(--surface-border);
}

.profile-avatar {
  width: 56px;
  height: 56px;
  border-radius: var(--radius-md);
  background: var(--primary);
  color: var(--primary-foreground);
  font-size: 22px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.profile-name {
  font-size: 18px;
  font-weight: 700;
  color: var(--foreground);
  margin: 0 0 2px;
}

.profile-username {
  font-size: 13px;
  color: var(--muted-foreground);
  margin: 0;
}

.profile-form {
  padding: 24px 28px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.profile-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.profile-field-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--foreground);
}

.profile-input {
  padding: 8px 12px;
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-md);
  font-size: 14px;
  font-family: var(--font-sans);
  background: var(--page-canvas);
  color: var(--foreground);
  outline: none;
  transition: border-color var(--transition-fast);
}

.profile-input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px oklch(0.55 0.2 260 / 0.12);
}

.profile-save-btn {
  align-self: flex-start;
  padding: 8px 20px;
  border: none;
  border-radius: var(--radius-md);
  background: var(--primary);
  color: var(--primary-foreground);
  font-size: 13px;
  font-weight: 600;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.profile-save-btn:hover {
  background: var(--primary-hover);
}

.profile-save-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.profile-message {
  font-size: 13px;
  color: var(--success);
  margin: 0;
}

.profile-message.error {
  color: var(--danger);
}
</style>
