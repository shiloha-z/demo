import { marked } from 'marked'

// Configure marked for safe rendering
marked.setOptions({
  breaks: true,       // Single newline → <br>
  gfm: true,          // GitHub Flavored Markdown (tables, strikethrough, task lists)
})

/**
 * Render Markdown text to safe HTML.
 * Wraps output in a div with class "md-rendered" for styling.
 */
export function renderMarkdown(text: string): string {
  if (!text) return ''
  const html = marked.parse(text) as string
  return `<div class="md-rendered">${html}</div>`
}
