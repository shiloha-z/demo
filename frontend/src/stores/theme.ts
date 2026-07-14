import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useThemeStore = defineStore('theme', () => {
  const isDark = ref(localStorage.getItem('theme') === 'dark')

  function applyTheme() {
    document.documentElement.classList.toggle('dark', isDark.value)
  }

  function toggleDark() {
    isDark.value = !isDark.value
    localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
    applyTheme()
  }

  function initTheme() {
    applyTheme()
  }

  return { isDark, toggleDark, initTheme }
})
