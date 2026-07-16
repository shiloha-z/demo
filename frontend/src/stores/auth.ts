import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  const username = ref(localStorage.getItem('username') || '')
  const displayName = ref(localStorage.getItem('displayName') || '')
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
  }

  function updateDisplayName(name: string) {
    displayName.value = name
    localStorage.setItem('displayName', name)
  }

  function logout() {
    token.value = ''
    username.value = ''
    displayName.value = ''
    userId.value = 0
    localStorage.removeItem('token')
    localStorage.removeItem('username')
    localStorage.removeItem('displayName')
    localStorage.removeItem('userId')
  }

  return { token, username, displayName, userId, isLoggedIn, setUser, updateDisplayName, logout }
})
