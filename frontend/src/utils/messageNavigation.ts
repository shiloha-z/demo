import type { RouteLocationRaw, Router } from 'vue-router'
import type { MessageItem } from '../stores/message'
import { useProjectStore } from '../stores/project'

function firstNumericMatch(text: string, pattern: RegExp): string | undefined {
  return text.match(pattern)?.[1]
}

/**
 * Convert both current and legacy message links into an internal, entity-aware
 * route. Legacy rows often only stored "/tasks" or "/versions"; their title and
 * body still contain enough identity to recover a precise destination.
 */
export function messageLocation(message: MessageItem): RouteLocationRaw | null {
  const rawLink = message.link?.trim()
  let path = rawLink?.split('?')[0] || ''
  const rawQuery = rawLink?.includes('?') ? rawLink.slice(rawLink.indexOf('?') + 1) : ''
  const params = new URLSearchParams(rawQuery)
  const searchable = `${message.title} ${message.body}`

  if (!path) {
    if (message.category === 'member' && message.project_id != null) {
      path = '/dashboard'
      params.set('panel', 'members')
    } else {
      return null
    }
  }
  if (!path.startsWith('/') || path.startsWith('//')) return null

  if (message.project_id != null && !params.has('project_id')) {
    params.set('project_id', String(message.project_id))
  }

  if (path === '/tasks' && !params.has('task_id')) {
    const taskId = firstNumericMatch(searchable, /任务\s*#(\d+)/)
    if (taskId) params.set('task_id', taskId)
  }

  if (path === '/reviews' && !params.has('review_id') && !params.has('task_id')) {
    const reviewId = firstNumericMatch(searchable, /审查\s*#(\d+)/)
    const taskId = firstNumericMatch(searchable, /任务\s*#(\d+)/)
    if (reviewId) params.set('review_id', reviewId)
    else if (taskId) params.set('task_id', taskId)
  }

  if (path === '/versions' && !params.has('version_id') && !params.has('commit')) {
    const commit = searchable.match(/\b([0-9a-f]{7,40})\b/i)?.[1]
    if (commit) params.set('commit', commit)
  }

  if (path === '/dashboard' && /@\s*了你/.test(message.title) && !params.has('open_chat')) {
    params.set('open_chat', 'team')
  }

  const query = Object.fromEntries(params.entries())
  return { path, query }
}

export async function navigateToMessage(
  message: MessageItem,
  router: Router,
): Promise<boolean> {
  const location = messageLocation(message)
  if (!location) return false

  if (message.project_id != null) {
    const projectStore = useProjectStore()
    if (projectStore.currentProject?.id !== message.project_id) {
      let project = projectStore.switchableProjects.find(
        item => item.id === message.project_id,
      )
      if (!project) {
        try {
          await projectStore.fetchSwitchableProjects()
          project = projectStore.switchableProjects.find(
            item => item.id === message.project_id,
          )
        } catch {
          // Direct navigation still gives the target page a chance to show an
          // access or stale-message state.
        }
      }
      if (project) projectStore.setCurrentProject(project)
    }
  }

  await router.push(location)
  return true
}
