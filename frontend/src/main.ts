import { createApp } from 'vue'
import TDesign from 'tdesign-vue-next'
import 'tdesign-vue-next/es/style/index.css'
import { createPinia } from 'pinia'
import router from './router'
import App from './App.vue'
import './styles/tokens.css'
import './styles/components.css'
import './style.css'

const app = createApp(App)

app.use(TDesign)
app.use(createPinia())
app.use(router)

// Initialize theme before mount to avoid flash
import { useThemeStore } from './stores/theme'
useThemeStore().initTheme()

app.mount('#app')
