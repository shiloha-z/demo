import { defineStore } from 'pinia'
import { ref } from 'vue'

let themeAnimTimer: ReturnType<typeof setTimeout> | undefined

export const useThemeStore = defineStore('theme', () => {
  const isDark = ref(localStorage.getItem('theme') === 'dark')

  function applyTheme() {
    document.documentElement.classList.toggle('dark', isDark.value)
  }

  function toggleDark() {
    isDark.value = !isDark.value
    localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
    applyTheme()
    // Enable a one-shot smooth color transition during the switch only,
    // so hover/interaction states don't lag during normal use.
    document.documentElement.classList.add('theme-anim')
    if (themeAnimTimer) clearTimeout(themeAnimTimer)
    themeAnimTimer = setTimeout(() => {
      document.documentElement.classList.remove('theme-anim')
    }, 340)
  }

  function initTheme() {
    applyTheme()
  }

  return { isDark, toggleDark, initTheme }
})
