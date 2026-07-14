<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, shallowRef } from 'vue'
import * as monaco from 'monaco-editor'
import { useThemeStore } from '../stores/theme'

const props = defineProps<{
  content: string
  language?: string
  readOnly?: boolean
  original?: string  // for diff mode
}>()

const themeStore = useThemeStore()
const container = ref<HTMLElement>()
const editor = shallowRef<monaco.editor.IStandaloneCodeEditor | monaco.editor.IStandaloneDiffEditor | null>(null)

function getLanguage(path: string): string {
  const map: Record<string, string> = {
    py: 'python', ts: 'typescript', js: 'javascript', vue: 'html',
    json: 'json', md: 'markdown', html: 'html', css: 'css', yml: 'yaml',
    yaml: 'yaml', sql: 'sql', sh: 'shell', txt: 'plaintext',
    c: 'c', h: 'c', cpp: 'cpp', hpp: 'cpp', java: 'java', go: 'go',
    rs: 'rust', rb: 'ruby', php: 'php', xml: 'xml', toml: 'ini',
  }
  const ext = path.split('.').pop() || ''
  return map[ext] || 'plaintext'
}

function getMonacoTheme(): string {
  return themeStore.isDark ? 'vs-dark' : 'vs'
}

onMounted(() => {
  if (!container.value) return
  const lang = getLanguage(props.language || 'plaintext')

  // Define a custom theme that matches our design tokens
  monaco.editor.defineTheme('agentcollab-light', {
    base: 'vs',
    inherit: true,
    rules: [],
    colors: {
      'editor.background': '#fafafa',
      'editor.foreground': '#2b2b2b',
      'editorLineNumber.foreground': '#b0b0b0',
      'editorLineNumber.activeForeground': '#666666',
      'editor.selectionBackground': '#e8e8f0',
      'editor.lineHighlightBackground': '#f5f5f5',
      'editorCursor.foreground': '#5466ff',
      'editorGutter.background': '#fafafa',
    },
  })

  monaco.editor.defineTheme('agentcollab-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: [],
    colors: {
      'editor.background': '#1e1e2e',
      'editor.foreground': '#d4d4d4',
      'editorLineNumber.foreground': '#555566',
      'editorLineNumber.activeForeground': '#9999aa',
      'editor.selectionBackground': '#3a3a55',
      'editor.lineHighlightBackground': '#262638',
      'editorCursor.foreground': '#7a8aff',
      'editorGutter.background': '#1e1e2e',
    },
  })

  function getThemeName() {
    return themeStore.isDark ? 'agentcollab-dark' : 'agentcollab-light'
  }

  if (props.original !== undefined) {
    editor.value = monaco.editor.createDiffEditor(container.value, {
      readOnly: props.readOnly ?? true,
      automaticLayout: true,
      minimap: { enabled: false },
      fontSize: 13,
      theme: getThemeName(),
    })
    const diffEditor = editor.value as monaco.editor.IStandaloneDiffEditor
    diffEditor.setModel({
      original: monaco.editor.createModel(props.original, lang),
      modified: monaco.editor.createModel(props.content, lang),
    })
  } else {
    editor.value = monaco.editor.create(container.value, {
      value: props.content,
      language: lang,
      readOnly: props.readOnly ?? true,
      automaticLayout: true,
      minimap: { enabled: false },
      fontSize: 13,
      lineNumbers: 'on',
      scrollBeyondLastLine: false,
      tabSize: 4,
      insertSpaces: true,
      detectIndentation: false,
      renderWhitespace: 'selection',
      theme: getThemeName(),
    })
  }
})

// Watch for theme changes
watch(() => themeStore.isDark, () => {
  if (!editor.value) return
  const themeName = themeStore.isDark ? 'agentcollab-dark' : 'agentcollab-light'
  monaco.editor.setTheme(themeName)
})

watch(() => props.content, (val) => {
  if (!editor.value) return
  if ('getModel' in editor.value) {
    const model = editor.value.getModel()
    if (model) {
      const e = model as monaco.editor.ITextModel
      if (e.getValue() !== val) e.setValue(val)
    }
  }
})

onBeforeUnmount(() => {
  editor.value?.dispose()
})
</script>

<template>
  <div ref="container" class="monaco-container"></div>
</template>

<style scoped>
.monaco-container {
  width: 100%;
  height: 100%;
  min-height: 300px;
}
</style>
