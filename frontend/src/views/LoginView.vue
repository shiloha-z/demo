<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { MessagePlugin } from 'tdesign-vue-next'
import api from '../api'

const router = useRouter()
const auth = useAuthStore()

const isRegister = ref(false)
const form = ref({ username: '', password: '', display_name: '' })
const loading = ref(false)

async function submit() {
  loading.value = true
  try {
    const url = isRegister.value ? '/auth/register' : '/auth/login'
    const { data } = await api.post(url, form.value)
    auth.setUser(data)
    router.push('/dashboard')
  } catch (e: any) {
    MessagePlugin.error(e.response?.data?.detail || '请求失败，请重试')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <!-- Left: brand panel -->
    <div class="brand-panel">
      <div class="brand-content">
        <div class="brand-logo">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none">
            <rect x="3" y="7" width="18" height="13" rx="3" fill="rgba(255,255,255,0.9)"/>
            <circle cx="8.5" cy="13" r="1.5" fill="var(--primary)"/>
            <circle cx="15.5" cy="13" r="1.5" fill="var(--primary)"/>
            <path d="M9 16.5h6" stroke="var(--primary)" stroke-width="1.5" stroke-linecap="round"/>
            <rect x="9" y="3" width="6" height="4" rx="1.5" fill="rgba(255,255,255,0.9)"/>
            <circle cx="6" cy="10" r="1" fill="rgba(255,255,255,0.7)"/>
            <circle cx="18" cy="10" r="1" fill="rgba(255,255,255,0.7)"/>
          </svg>
        </div>
        <h1 class="brand-title">AgentCollab</h1>
        <p class="brand-subtitle">多 Agent 协作审查平台</p>
        <div class="brand-features">
          <div class="feature-item">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
            <span>AI 代码生成与审查流水线</span>
          </div>
          <div class="feature-item">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>
            <span>人工决策闭环，通过即提交</span>
          </div>
          <div class="feature-item">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            <span>版本回退，全程可追溯</span>
          </div>
        </div>
      </div>
      <div class="brand-decoration">
        <div class="deco-circle deco-circle-1"></div>
        <div class="deco-circle deco-circle-2"></div>
        <div class="deco-grid"></div>
      </div>
    </div>

    <!-- Right: form panel -->
    <div class="form-panel">
      <div class="login-card">
        <div class="login-header">
          <h2>{{ isRegister ? '创建账号' : '欢迎回来' }}</h2>
          <p>{{ isRegister ? '注册开始你的 Agent 协作之旅' : '登录到你的工作区' }}</p>
        </div>

        <form @submit.prevent="submit" class="login-form">
          <div class="form-field">
            <label class="field-label">用户名</label>
            <div class="input-wrapper">
              <svg class="input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
              <input v-model="form.username" class="field-input" placeholder="请输入用户名" autocomplete="username" />
            </div>
          </div>

          <div v-if="isRegister" class="form-field">
            <label class="field-label">昵称</label>
            <div class="input-wrapper">
              <svg class="input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
              <input v-model="form.display_name" class="field-input" placeholder="选填" />
            </div>
          </div>

          <div class="form-field">
            <label class="field-label">密码</label>
            <div class="input-wrapper">
              <svg class="input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
              <input v-model="form.password" class="field-input" type="password" placeholder="请输入密码" autocomplete="current-password" />
            </div>
          </div>

          <button type="submit" class="btn-submit" :disabled="loading">
            <span v-if="loading" class="btn-spinner"></span>
            {{ loading ? '请稍候...' : (isRegister ? '注册' : '登录') }}
          </button>
        </form>

        <p class="login-switch">
          {{ isRegister ? '已有账号？' : '没有账号？' }}
          <a href="#" @click.prevent="isRegister = !isRegister">{{ isRegister ? '去登录' : '去注册' }}</a>
        </p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  height: 100vh;
  background: var(--page-canvas);
}

/* ── Brand panel ────────────────────────────────────────────────── */
.brand-panel {
  flex: 1;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, oklch(0.546 0.215 264) 0%, oklch(0.45 0.2 280) 100%);
  overflow: hidden;
}

.brand-content {
  position: relative;
  z-index: 1;
  text-align: left;
  padding: 60px;
  max-width: 460px;
  color: #fff;
  animation: fadeUp 0.6s cubic-bezier(0.4, 0, 0.2, 1) both;
}

.brand-logo {
  margin-bottom: 20px;
}

.brand-title {
  font-size: 32px;
  font-weight: 800;
  margin: 0 0 8px;
  letter-spacing: -1px;
  color: #fff;
}

.brand-subtitle {
  font-size: 16px;
  color: rgba(255, 255, 255, 0.8);
  margin: 0 0 48px;
}

.brand-features {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.feature-item {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 14px;
  color: rgba(255, 255, 255, 0.9);
}

.feature-item svg {
  flex-shrink: 0;
  opacity: 0.9;
}

/* ── Decoration ─────────────────────────────────────────────────── */
.brand-decoration {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.deco-circle {
  position: absolute;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.06);
}

.deco-circle-1 {
  width: 400px;
  height: 400px;
  top: -100px;
  right: -100px;
}

.deco-circle-2 {
  width: 300px;
  height: 300px;
  bottom: -80px;
  left: -80px;
}

.deco-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.04) 1px, transparent 1px);
  background-size: 40px 40px;
  mask-image: radial-gradient(ellipse at center, black 30%, transparent 70%);
  -webkit-mask-image: radial-gradient(ellipse at center, black 30%, transparent 70%);
}

/* ── Form panel ─────────────────────────────────────────────────── */
.form-panel {
  width: 480px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface);
}

.login-card {
  width: 100%;
  max-width: 340px;
  padding: 40px;
  animation: fadeUp 0.5s cubic-bezier(0.4, 0, 0.2, 1) both;
}

@keyframes fadeUp {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: none; }
}

.login-header {
  margin-bottom: 28px;
}

.login-header h2 {
  font-size: 22px;
  font-weight: 700;
  margin: 0 0 6px;
  letter-spacing: -0.3px;
  color: var(--foreground);
}

.login-header p {
  font-size: 13.5px;
  color: var(--muted-foreground);
  margin: 0;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.input-wrapper {
  position: relative;
}

.input-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--muted-foreground);
  pointer-events: none;
}

.field-input {
  width: 100%;
  padding: 10px 12px 10px 38px;
  border: 1px solid var(--input);
  border-radius: var(--radius-md);
  font-size: 14px;
  font-family: var(--font-sans);
  background: var(--surface);
  color: var(--foreground);
  outline: none;
  box-sizing: border-box;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.field-input::placeholder {
  color: oklch(0.6 0.01 280);
}

.field-input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--ring);
}

.btn-submit {
  margin-top: 8px;
  padding: 11px;
  border-radius: var(--radius-md);
  background: var(--primary);
  color: var(--primary-foreground);
  border: none;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: background var(--transition-fast);
}

.btn-submit:hover:not(:disabled) {
  background: var(--primary-hover);
}

.btn-submit:active:not(:disabled) {
  background: var(--primary-active);
}

.btn-submit:disabled {
  opacity: 0.6;
  cursor: default;
}

.btn-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.login-switch {
  text-align: center;
  margin-top: 24px;
  font-size: 13px;
  color: var(--muted-foreground);
}

.login-switch a {
  color: var(--primary);
  text-decoration: none;
  font-weight: 600;
}

.login-switch a:hover {
  text-decoration: underline;
}

/* ── Responsive ─────────────────────────────────────────────────── */
@media (max-width: 900px) {
  .brand-panel { display: none; }
  .form-panel { width: 100%; }
}
</style>
