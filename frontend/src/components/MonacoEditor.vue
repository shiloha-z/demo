<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, shallowRef } from 'vue'
import * as monaco from 'monaco-editor'

const props = defineProps<{
  content: string
  language?: string
  readOnly?: boolean
  original?: string  // for diff mode
}>()

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

onMounted(() => {
  if (!container.value) return
  const lang = getLanguage(props.language || 'plaintext')

  if (props.original !== undefined) {
    // Diff mode
    editor.value = monaco.editor.createDiffEditor(container.value, {
      readOnly: props.readOnly ?? true,
      automaticLayout: true,
      minimap: { enabled: false },
      fontSize: 13,
    })
    const diffEditor = editor.value as monaco.editor.IStandaloneDiffEditor
    diffEditor.setModel({
      original: monaco.editor.createModel(props.original, lang),
      modified: monaco.editor.createModel(props.content, lang),
    })
  } else {
    // Normal editor
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
    })
  }
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
