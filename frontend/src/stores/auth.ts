import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  const username = ref(localStorage.getItem('username') || '')
  const displayName = ref(localStorage.getItem('displayName') || '')

  const isLoggedIn = computed(() => !!token.value)

  function setUser(data: { token: string; username: string; display_name: string }) {
    token.value = data.token
    username.value = data.username
    displayName.value = data.display_name
    localStorage.setItem('token', data.token)
    localStorage.setItem('username', data.username)
    localStorage.setItem('displayName', data.display_name)
  }

  function logout() {
    token.value = ''
    username.value = ''
    displayName.value = ''
    localStorage.removeItem('token')
    localStorage.removeItem('username')
    localStorage.removeItem('displayName')
  }

  return { token, username, displayName, isLoggedIn, setUser, logout }
})
