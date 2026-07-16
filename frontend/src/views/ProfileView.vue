<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../stores/auth'
import api from '../api'

const auth = useAuthStore()

interface Profile {
  username: string
  display_name: string
  email: string
  phone: string
  bio: string
  avatar_url: string
}

const profile = ref<Profile>({
  username: '',
  display_name: '',
  email: '',
  phone: '',
  bio: '',
  avatar_url: '',
})

const saving = ref(false)
const message = ref('')
const avatarUploading = ref(false)

async function loadProfile() {
  try {
    const { data } = await api.get('/auth/profile')
    profile.value = data
  } catch { /* ignore */ }
}

onMounted(loadProfile)

async function saveProfile() {
  saving.value = true
  message.value = ''
  try {
    const { data } = await api.put('/auth/profile', {
      display_name: profile.value.display_name,
      email: profile.value.email,
      phone: profile.value.phone,
      bio: profile.value.bio,
    })
    profile.value = { ...profile.value, ...data }
    auth.updateDisplayName(profile.value.display_name)
    message.value = '保存成功'
  } catch {
    message.value = '保存失败，请重试'
  } finally {
    saving.value = false
  }
}

async function handleAvatarUpload(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  avatarUploading.value = true
  try {
    const form = new FormData()
    form.append('file', file)
    const { data } = await api.post('/auth/profile/avatar', form)
    profile.value.avatar_url = data.avatar_url + '?t=' + Date.now()
  } catch { /* ignore */ }
  finally {
    avatarUploading.value = false
    input.value = ''
  }
}
</script>

<template>
  <div class="profile-page">
    <div class="profile-card">
      <!-- Header with avatar -->
      <div class="profile-header">
        <label class="profile-avatar-wrap" :class="{ uploading: avatarUploading }">
          <img
            v-if="profile.avatar_url"
            :src="profile.avatar_url"
            class="profile-avatar-img"
          />
          <div v-else class="profile-avatar-text">{{ auth.displayName?.charAt(0) || '?' }}</div>
          <div class="avatar-overlay">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
          </div>
          <input
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            class="avatar-file-input"
            @change="handleAvatarUpload"
          />
        </label>
        <div>
          <h2 class="profile-name">{{ auth.displayName }}</h2>
          <p class="profile-username">@{{ auth.username }}</p>
        </div>
      </div>

      <!-- Form -->
      <div class="profile-form">
        <label class="profile-field">
          <span class="profile-field-label">显示名称</span>
          <input
            v-model="profile.display_name"
            type="text"
            class="profile-input"
            maxlength="50"
            placeholder="输入显示名称"
          />
        </label>

        <div class="profile-row">
          <label class="profile-field">
            <span class="profile-field-label">邮箱</span>
            <input
              v-model="profile.email"
              type="email"
              class="profile-input"
              maxlength="200"
              placeholder="your@email.com"
            />
          </label>

          <label class="profile-field">
            <span class="profile-field-label">电话</span>
            <input
              v-model="profile.phone"
              type="tel"
              class="profile-input"
              maxlength="30"
              placeholder="+86 138-0000-0000"
            />
          </label>
        </div>

        <label class="profile-field">
          <span class="profile-field-label">个人简介</span>
          <textarea
            v-model="profile.bio"
            class="profile-textarea"
            maxlength="500"
            rows="4"
            placeholder="介绍一下自己..."
          ></textarea>
          <span class="profile-field-hint">{{ profile.bio.length }} / 500</span>
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
  max-width: 600px;
  margin: 0 auto;
}

.profile-card {
  background: var(--surface);
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

/* ── Header ────────────────────────────────────────────────────── */
.profile-header {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 32px 28px;
  background: var(--surface-hover);
  border-bottom: 1px solid var(--surface-border);
}

.profile-avatar-wrap {
  position: relative;
  width: 72px;
  height: 72px;
  border-radius: var(--radius-md);
  flex-shrink: 0;
  cursor: pointer;
  overflow: hidden;
}

.profile-avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.profile-avatar-text {
  width: 100%;
  height: 100%;
  background: var(--primary);
  color: var(--primary-foreground);
  font-size: 28px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.avatar-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0,0,0,0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  opacity: 0;
  transition: opacity var(--transition-fast);
}

.profile-avatar-wrap:hover .avatar-overlay,
.profile-avatar-wrap.uploading .avatar-overlay {
  opacity: 1;
}

.avatar-file-input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}

.profile-name {
  font-size: 20px;
  font-weight: 700;
  color: var(--foreground);
  margin: 0 0 4px;
}

.profile-username {
  font-size: 13px;
  color: var(--muted-foreground);
  margin: 0;
}

/* ── Form ───────────────────────────────────────────────────────── */
.profile-form {
  padding: 24px 28px 28px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.profile-row {
  display: flex;
  gap: 16px;
}

.profile-row .profile-field {
  flex: 1;
  min-width: 0;
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

.profile-field-hint {
  font-size: 11px;
  color: var(--muted-foreground);
  align-self: flex-end;
}

.profile-input,
.profile-textarea {
  padding: 9px 12px;
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-md);
  font-size: 14px;
  font-family: var(--font-sans);
  background: var(--page-canvas);
  color: var(--foreground);
  outline: none;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.profile-textarea {
  resize: vertical;
  min-height: 80px;
}

.profile-input:focus,
.profile-textarea:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px oklch(0.55 0.2 260 / 0.12);
}

.profile-save-btn {
  align-self: flex-start;
  padding: 9px 24px;
  border: none;
  border-radius: var(--radius-md);
  background: var(--primary);
  color: var(--primary-foreground);
  font-size: 14px;
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
