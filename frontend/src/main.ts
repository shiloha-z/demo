import { createApp } from 'vue'
import {
  Button as TButton,
  Dialog as TDialog,
  Dropdown as TDropdown,
  DropdownItem as TDropdownItem,
  DropdownMenu as TDropdownMenu,
  Input as TInput,
  InputNumber as TInputNumber,
  Option as TOption,
  Select as TSelect,
  Switch as TSwitch,
  Tag as TTag,
  Textarea as TTextarea,
} from 'tdesign-vue-next'
import 'tdesign-vue-next/es/style/index.css'
import { createPinia } from 'pinia'
import router from './router'
import App from './App.vue'
import jsonWorkerUrl from 'monaco-editor/esm/vs/language/json/json.worker?worker&url'
import './styles/tokens.css'
import './styles/components.css'
import './style.css'

const app = createApp(App)

// Register only the components used by templates. Importing the full TDesign
// plugin forced every page to parse the entire component library up front.
const tdesignComponents = {
  TButton,
  TDialog,
  TDropdown,
  TDropdownItem,
  TDropdownMenu,
  TInput,
  TInputNumber,
  TOption,
  TSelect,
  TSwitch,
  TTag,
  TTextarea,
}
Object.entries(tdesignComponents).forEach(([name, component]) => {
  app.component(name, component)
})

app.use(createPinia())
app.use(router)

// Initialize theme before mount to avoid flash
import { useThemeStore } from './stores/theme'
useThemeStore().initTheme()

async function warmDeferredRuntimeAssets() {
  const bootStatus = document.querySelector<HTMLElement>('.app-boot__status')
  if (bootStatus) bootStatus.textContent = '正在缓存编辑器运行资源…'

  const warmups: Promise<unknown>[] = [
    fetch(jsonWorkerUrl, { cache: 'force-cache' }).then((response) => {
      if (!response.ok) throw new Error(`Worker preload failed: ${response.status}`)
      return response.arrayBuffer()
    }),
  ]
  if (document.fonts) {
    warmups.push(document.fonts.load('16px codicon'))
  }
  await Promise.allSettled(warmups)
}

async function bootstrap() {
  try {
    await Promise.all([
      router.isReady(),
      warmDeferredRuntimeAssets(),
    ])
  } catch (error) {
    // The app remains usable if an optional warmup fails; the browser can
    // retry that resource when the relevant editor feature is first used.
    console.warn('Application preload completed with warnings', error)
  }
  app.mount('#app')
}

void bootstrap()
