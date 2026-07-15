<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ diff: string }>()

interface DiffHunk {
  header: string
  lines: { type: 'add' | 'del' | 'ctx'; oldLine: number | null; newLine: number | null; text: string }[]
}

interface DiffFile {
  header: string
  oldFile: string
  newFile: string
  hunks: DiffHunk[]
}

function parseDiff(raw: string): DiffFile[] {
  if (!raw) return []

  const files: DiffFile[] = []
  const lines = raw.split('\n')
  let currentFile: DiffFile | null = null
  let currentHunk: DiffHunk | null = null
  let oldLine = 0
  let newLine = 0

  const FILE_RE = /^diff --git a\/(.*?) b\/(.*?)$/

  for (const line of lines) {
    const fileMatch = line.match(FILE_RE)
    if (fileMatch) {
      if (currentFile) files.push(currentFile)
      currentFile = {
        header: line,
        oldFile: fileMatch[1],
        newFile: fileMatch[2],
        hunks: [],
      }
      currentHunk = null
      continue
    }

    if (!currentFile) continue

    // Hunk header: @@ -old,count +new,count @@ context
    const hunkMatch = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/)
    if (hunkMatch) {
      if (currentHunk) currentFile.hunks.push(currentHunk)
      oldLine = parseInt(hunkMatch[1], 10)
      newLine = parseInt(hunkMatch[2], 10)
      currentHunk = { header: line, lines: [] }
      continue
    }

    if (currentHunk) {
      if (line.startsWith('+') && !line.startsWith('+++')) {
        currentHunk.lines.push({ type: 'add', oldLine: null, newLine: newLine++, text: line.slice(1) })
      } else if (line.startsWith('-') && !line.startsWith('---')) {
        currentHunk.lines.push({ type: 'del', oldLine: oldLine++, newLine: null, text: line.slice(1) })
      } else if (line.startsWith(' ') || line === '') {
        currentHunk.lines.push({ type: 'ctx', oldLine: oldLine++, newLine: newLine++, text: line.startsWith(' ') ? line.slice(1) : '' })
      }
      // Skip other lines (index, file markers, binary, etc.)
    }
  }

  if (currentFile) {
    if (currentHunk) currentFile.hunks.push(currentHunk)
    files.push(currentFile)
  }

  return files
}

const files = computed(() => parseDiff(props.diff))

function joinPath(oldPath: string, newPath: string): string {
  // Simplify: if both same, show one; otherwise show rename
  if (oldPath === newPath) return oldPath
  if (oldPath === '/dev/null') return `新增 → ${newPath}`
  if (newPath === '/dev/null') return `删除 → ${oldPath}`
  return `${oldPath} → ${newPath}`
}
</script>

<template>
  <div class="diff-viewer" v-if="files.length > 0">
    <div v-for="(file, fi) in files" :key="fi" class="diff-file">
      <div class="diff-file-header">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        <span class="diff-file-path">{{ joinPath(file.oldFile, file.newFile) }}</span>
        <span class="diff-file-stats">
          <span class="stat-add">+{{ file.hunks.reduce((s, h) => s + h.lines.filter(l => l.type === 'add').length, 0) }}</span>
          <span class="stat-del">−{{ file.hunks.reduce((s, h) => s + h.lines.filter(l => l.type === 'del').length, 0) }}</span>
        </span>
      </div>
      <div class="diff-hunks">
        <div v-for="(hunk, hi) in file.hunks" :key="hi" class="diff-hunk">
          <div class="diff-hunk-header">{{ hunk.header }}</div>
          <div class="diff-lines">
            <div
              v-for="(l, li) in hunk.lines"
              :key="li"
              class="diff-line"
              :class="l.type"
            >
              <span class="line-num old-num">{{ l.oldLine ?? '' }}</span>
              <span class="line-num new-num">{{ l.newLine ?? '' }}</span>
              <span class="line-prefix">{{ l.type === 'add' ? '+' : l.type === 'del' ? '−' : ' ' }}</span>
              <span class="line-text">{{ l.text }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="diff-viewer diff-empty">
    <p>无代码变更或无法解析的 diff 格式</p>
  </div>
</template>

<style scoped>
.diff-viewer {
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.5;
}

/* ── File header ─────────────────────────────────────────────── */
.diff-file {
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-md);
  overflow: hidden;
  margin-bottom: 14px;
}
.diff-file-header {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 14px;
  background: var(--surface-hover);
  border-bottom: 1px solid var(--surface-border);
  font-weight: 600; font-size: 12.5px; color: var(--foreground);
}
.diff-file-path { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.diff-file-stats { display: flex; gap: 8px; font-size: 11px; }
.stat-add { color: var(--diff-add, #22863a); }
.stat-del { color: var(--diff-del, #cb2431); }

/* ── Hunk header ─────────────────────────────────────────────── */
.diff-hunk-header {
  padding: 6px 14px;
  background: var(--primary-lighter);
  color: var(--muted-foreground);
  font-size: 11px; font-weight: 500;
  border-bottom: 1px solid oklch(0.6 0.15 260 / 0.15);
}

/* ── Lines ───────────────────────────────────────────────────── */
.diff-lines { overflow-x: auto; }

.diff-line {
  display: flex; align-items: stretch; min-height: 22px;
  border-bottom: 1px solid oklch(0 0 0 / 0.04);
}
.diff-line.add { background: var(--diff-add-bg, #e6ffec); }
.diff-line.del { background: var(--diff-del-bg, #ffebe9); }
.diff-line.ctx { background: transparent; }

.line-num {
  width: 44px; flex-shrink: 0; text-align: right; padding: 2px 6px 2px 4px;
  color: var(--muted-foreground); opacity: 0.5;
  font-size: 11px; user-select: none;
  border-right: 1px solid oklch(0 0 0 / 0.08);
}
.line-prefix {
  width: 18px; flex-shrink: 0; text-align: center; padding: 2px 0;
  user-select: none; font-weight: 700;
}
.diff-line.add .line-prefix { color: var(--diff-add, #22863a); }
.diff-line.del .line-prefix { color: var(--diff-del, #cb2431); }
.diff-line.ctx .line-prefix { color: var(--muted-foreground); opacity: 0.4; }

.line-text {
  padding: 2px 8px; white-space: pre; overflow: hidden; text-overflow: ellipsis;
  color: var(--foreground);
}
.diff-line.add .line-text { color: oklch(0.37 0.14 153); }
.diff-line.del .line-text { color: oklch(0.42 0.17 27); }

.diff-empty {
  text-align: center; color: var(--muted-foreground);
  padding: 32px; font-size: 13px;
}

/* Dark mode tuning */
:global(.dark) .diff-line.add { background: oklch(0.3 0.06 153 / 0.18); }
:global(.dark) .diff-line.del { background: oklch(0.3 0.08 27 / 0.18); }
:global(.dark) .diff-line.add .line-text { color: oklch(0.7 0.12 153); }
:global(.dark) .diff-line.del .line-text { color: oklch(0.72 0.12 27); }
</style>
