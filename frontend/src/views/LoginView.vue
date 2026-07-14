<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import api from '../api'

const router = useRouter()
const auth = useAuthStore()

const isRegister = ref(false)
const form = ref({ username: '', password: '', display_name: '' })
const loading = ref(false)
const error = ref('')

async function submit() {
  loading.value = true
  error.value = ''
  try {
    const url = isRegister.value ? '/auth/register' : '/auth/login'
    const { data } = await api.post(url, form.value)
    auth.setUser(data)
    router.push('/dashboard')
  } catch (e: any) {
    error.value = e.response?.data?.detail || '请求失败，请重试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <span class="login-logo">🤖</span>
        <h1>AgentCollab</h1>
        <p>多 Agent 协作审查平台</p>
      </div>

      <form @submit.prevent="submit" class="login-form">
        <label class="field-label">用户名</label>
        <input v-model="form.username" class="field-input" placeholder="请输入用户名" autocomplete="username" />

        <label v-if="isRegister" class="field-label">昵称</label>
        <input v-if="isRegister" v-model="form.display_name" class="field-input" placeholder="选填" />

        <label class="field-label">密码</label>
        <input v-model="form.password" class="field-input" type="password" placeholder="请输入密码" autocomplete="current-password" />

        <div v-if="error" class="login-error">{{ error }}</div>

        <button type="submit" class="btn-primary" :disabled="loading">
          {{ loading ? '请稍候...' : (isRegister ? '注册' : '登录') }}
        </button>
      </form>

      <p class="login-switch">
        {{ isRegister ? '已有账号？' : '没有账号？' }}
        <a href="#" @click.prevent="isRegister = !isRegister; error = ''">
          {{ isRegister ? '去登录' : '去注册' }}
        </a>
      </p>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  display: flex; align-items: center; justify-content: center;
  height: 100vh; background: var(--app-shell);
}
.login-card {
  width: 380px; background: var(--surface);
  border: 1px solid var(--surface-border); border-radius: var(--radius-xl);
  box-shadow: var(--shadow-floating); padding: 36px 32px;
}
.login-header { text-align: center; margin-bottom: 28px; }
.login-logo { font-size: 36px; }
.login-header h1 { font-size: 20px; font-weight: 700; margin: 8px 0 4px; letter-spacing: -0.3px; }
.login-header p { font-size: 13px; color: var(--muted-foreground); margin: 0; }

.login-form { display: flex; flex-direction: column; gap: 6px; }
.field-label { font-size: 13px; font-weight: 600; color: var(--foreground); margin-top: 8px; }
.field-input {
  padding: 9px 12px; border: 1px solid var(--input); border-radius: var(--radius-md);
  font-size: 14px; font-family: var(--font-sans); background: var(--surface);
  color: var(--foreground); outline: none; transition: border-color 0.15s;
}
.field-input:focus { border-color: var(--ring); }

.login-error {
  font-size: 13px; color: var(--danger); background: oklch(0.577 0.245 27 / 0.08);
  padding: 8px 12px; border-radius: var(--radius-md); margin-top: 4px;
}
.btn-primary {
  margin-top: 12px; padding: 10px; border-radius: var(--radius-md);
  background: var(--primary); color: var(--primary-foreground);
  border: none; font-size: 14px; font-weight: 600; cursor: pointer; transition: opacity 0.15s;
}
.btn-primary:hover { opacity: 0.85; }
.login-switch { text-align: center; margin-top: 18px; font-size: 13px; color: var(--muted-foreground); }
.login-switch a { color: var(--brand); text-decoration: none; font-weight: 500; }
</style>
