export type MemoryScope = 'global' | 'project' | 'agent'

export interface MemoryEntry {
  id: string
  document: string
  metadata: Record<string, string | number | boolean>
  score?: number
}

/** 记忆类型 → 中文标签，与后端 memory_type 取值保持一致。 */
export const typeLabels: Record<string, string> = {
  review_result: '执行结果',
  review_decision: '审查反馈',
  error: '失败教训',
  lesson: '经验',
  pattern: '通用模式',
  progress: '执行进度',
  uncategorized: '未分类',
}

export function typeLabel(type: string): string {
  return typeLabels[type] || String(type).replaceAll('_', ' ')
}

/** 记忆类型 → 主题色 CSS 变量，保证图表随亮/暗模式切换。 */
export const typeColorVars: Record<string, string> = {
  review_result: 'var(--primary)',
  review_decision: 'var(--info)',
  error: 'var(--danger)',
  lesson: 'var(--warning)',
  pattern: 'var(--success)',
  progress: 'var(--muted-foreground)',
  uncategorized: 'var(--muted-foreground)',
}

export function typeColor(type: string): string {
  return typeColorVars[type] || 'var(--muted-foreground)'
}

export function sourceLabel(metadata: MemoryEntry['metadata']): string {
  const source = String(metadata.source || '')
  if (source === 'crewai_tool') return 'CrewAI'
  if (source) return source
  if (metadata.runner_type) return String(metadata.runner_type)
  return ''
}

export function formatTime(raw: unknown): string {
  if (!raw) return ''
  const date = new Date(String(raw))
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function relevanceLabel(score?: number): string {
  if (score === undefined) return ''
  if (score >= 0.78) return '高度相关'
  if (score >= 0.62) return '较相关'
  return '相关'
}

/** 将命中关键词的片段拆分为高亮片段，供列表与卡片复用。 */
export function highlightSegments(
  document: string,
  query: string,
): { text: string; match: boolean }[] {
  const keyword = query.trim()
  if (!keyword) return [{ text: document, match: false }]
  const tokens = [...new Set(keyword.split(/\s+/).filter(Boolean))]
  if (!tokens.length) return [{ text: document, match: false }]
  const escaped = tokens.map(token => token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const loweredTokens = new Set(tokens.map(token => token.toLocaleLowerCase()))
  const matcher = new RegExp(`(${escaped.join('|')})`, 'gi')
  return document
    .split(matcher)
    .filter(Boolean)
    .map(text => ({ text, match: loweredTokens.has(text.toLocaleLowerCase()) }))
}
