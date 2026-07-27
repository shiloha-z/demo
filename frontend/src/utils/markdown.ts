import { marked } from 'marked'

// Configure marked for safe rendering
marked.setOptions({
  breaks: true,       // Single newline → <br>
  gfm: true,          // GitHub Flavored Markdown (tables, strikethrough, task lists)
})

const FORBIDDEN_TAGS = [
  'script', 'style', 'iframe', 'object', 'embed', 'link', 'meta', 'base',
  'form', 'input', 'button', 'textarea', 'select', 'option', 'svg', 'math',
]

function isSafeUrl(value: string, attribute: string): boolean {
  const normalized = value.trim().toLowerCase()
  if (!normalized || normalized.startsWith('#') || normalized.startsWith('/')) return true
  try {
    const url = new URL(value, window.location.origin)
    if (attribute === 'href') return ['http:', 'https:', 'mailto:'].includes(url.protocol)
    return ['http:', 'https:'].includes(url.protocol)
  } catch {
    return false
  }
}

function sanitizeHtml(html: string): string {
  if (typeof DOMParser === 'undefined') {
    return html.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  }
  const document = new DOMParser().parseFromString(html, 'text/html')
  document.querySelectorAll(FORBIDDEN_TAGS.join(',')).forEach(element => element.remove())
  document.body.querySelectorAll('*').forEach(element => {
    for (const attribute of [...element.attributes]) {
      const name = attribute.name.toLowerCase()
      if (
        name.startsWith('on')
        || name === 'style'
        || name === 'srcdoc'
        || name === 'srcset'
        || name === 'formaction'
        || ((name === 'href' || name === 'src' || name === 'xlink:href') && !isSafeUrl(attribute.value, name))
      ) {
        element.removeAttribute(attribute.name)
      }
    }
    if (element.tagName === 'A' && element.getAttribute('target') === '_blank') {
      element.setAttribute('rel', 'noopener noreferrer')
    }
  })
  return document.body.innerHTML
}

/**
 * Render Markdown text to safe HTML.
 * Wraps output in a div with class "md-rendered" for styling.
 */
export function renderMarkdown(text: string): string {
  if (!text) return ''
  const html = sanitizeHtml(marked.parse(text) as string)
  return `<div class="md-rendered">${html}</div>`
}
