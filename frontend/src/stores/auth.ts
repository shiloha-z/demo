import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  const username = ref(localStorage.getItem('username') || '')
  const displayName = ref(localStorage.getItem('displayName') || '')
  const avatarUrl = ref(localStorage.getItem('avatarUrl') || '')
  const userId = ref(Number(localStorage.getItem('userId')) || 0)

  const isLoggedIn = computed(() => !!token.value)

  function setUser(data: { token: string; username: string; display_name: string; user_id: number }) {
    token.value = data.token
    username.value = data.username
    displayName.value = data.display_name
    userId.value = data.user_id
    localStorage.setItem('token', data.token)
    localStorage.setItem('username', data.username)
    localStorage.setItem('displayName', data.display_name)
    localStorage.setItem('userId', String(data.user_id))
    // Fetch avatar URL from profile
    loadAvatar()
  }

  function updateDisplayName(name: string) {
    displayName.value = name
    localStorage.setItem('displayName', name)
  }

  async function loadAvatar() {
    try {
      const { data } = await api.get('/auth/profile')
      avatarUrl.value = data.avatar_url || ''
      localStorage.setItem('avatarUrl', avatarUrl.value)
    } catch { /* ignore */ }
  }

  function setAvatarUrl(url: string) {
    avatarUrl.value = url
    localStorage.setItem('avatarUrl', url)
  }

  function logout() {
    token.value = ''
    username.value = ''
    displayName.value = ''
    avatarUrl.value = ''
    userId.value = 0
    localStorage.removeItem('token')
    localStorage.removeItem('username')
    localStorage.removeItem('displayName')
    localStorage.removeItem('avatarUrl')
    localStorage.removeItem('userId')
  }

  return { token, username, displayName, avatarUrl, userId, isLoggedIn, setUser, updateDisplayName, loadAvatar, setAvatarUrl, logout }
})
