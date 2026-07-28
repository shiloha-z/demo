import { defineStore } from 'pinia'
import { ref } from 'vue'

let themeAnimTimer: ReturnType<typeof setTimeout> | undefined

export const COLOR_THEME_OPTIONS = [
  { key: 'indigo', label: '靛蓝', colors: ['#5268e8', '#7656df'] },
  { key: 'ocean', label: '海洋', colors: ['#168acb', '#18a9a1'] },
  { key: 'violet', label: '星紫', colors: ['#8656e8', '#c14fc5'] },
  { key: 'rose', label: '玫瑰', colors: ['#d84f83', '#e76657'] },
  { key: 'emerald', label: '翡翠', colors: ['#229b68', '#20a49b'] },
  { key: 'amber', label: '琥珀', colors: ['#d88719', '#db6040'] },
] as const

export type ColorTheme = typeof COLOR_THEME_OPTIONS[number]['key']

const colorThemeKeys = new Set<string>(COLOR_THEME_OPTIONS.map(option => option.key))

export const useThemeStore = defineStore('theme', () => {
  const isDark = ref(localStorage.getItem('theme') === 'dark')
  const storedColorTheme = localStorage.getItem('color-theme')
  const colorTheme = ref<ColorTheme>(
    storedColorTheme && colorThemeKeys.has(storedColorTheme)
      ? storedColorTheme as ColorTheme
      : 'indigo',
  )

  function applyTheme() {
    document.documentElement.classList.toggle('dark', isDark.value)
    document.documentElement.dataset.colorTheme = colorTheme.value
  }

  function animateThemeChange() {
    document.documentElement.classList.add('theme-anim')
    if (themeAnimTimer) clearTimeout(themeAnimTimer)
    themeAnimTimer = setTimeout(() => {
      document.documentElement.classList.remove('theme-anim')
    }, 340)
  }

  function toggleDark() {
    isDark.value = !isDark.value
    localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
    applyTheme()
    animateThemeChange()
  }

  function setColorTheme(value: ColorTheme) {
    if (!colorThemeKeys.has(value) || colorTheme.value === value) return
    colorTheme.value = value
    localStorage.setItem('color-theme', value)
    applyTheme()
    animateThemeChange()
  }

  function initTheme() {
    applyTheme()
  }

  return { isDark, colorTheme, toggleDark, setColorTheme, initTheme }
})
