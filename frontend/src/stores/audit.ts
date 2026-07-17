import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '../api'

export interface AuditActionMeta {
  value: string
  label: string
  group: string
  group_label: string
  token: string
}

export interface AuditEntry {
  id: number
  actor_id: number | null
  actor_type: 'human' | 'agent' | 'system'
  actor_name: string
  project_id: number | null
  task_id: number | null
  task_node_id: number | null
  action: string
  target_type: string
  target_id: string
  intent: string
  payload: string
  impact: string
  ip: string
  ua: string
  created_at: string | null
}

export const useAuditStore = defineStore('audit', () => {
  const entries = ref<AuditEntry[]>([])
  const loading = ref(false)
  // Action registry mirrored from the backend (GET /api/audit/actions). Adding
  // a new audit action requires no frontend change — it shows up automatically.
  const actionMeta = ref<Record<string, AuditActionMeta>>({})

  async function load(params: Record<string, unknown> = {}) {
    loading.value = true
    try {
      const { data } = await api.get('/audit', { params })
      entries.value = data.entries
    } catch {
      entries.value = []
    } finally {
      loading.value = false
    }
  }

  async function fetchChain(taskId: number): Promise<{
    task_id: number
    project_id: number
    timeline: AuditEntry[]
  } | null> {
    try {
      const { data } = await api.get('/audit/chain', { params: { task_id: taskId } })
      return data
    } catch {
      return null
    }
  }

  async function fetchActions(): Promise<{ actions: AuditActionMeta[]; actor_types: string[] }> {
    try {
      const { data } = await api.get('/audit/actions')
      const map: Record<string, AuditActionMeta> = {}
      for (const a of data.actions as AuditActionMeta[]) {
        map[a.value] = a
      }
      actionMeta.value = map
      return data as { actions: AuditActionMeta[]; actor_types: string[] }
    } catch {
      return { actions: [], actor_types: [] }
    }
  }

  /** Resolve metadata for an action value, with a safe fallback. */
  function metaFor(action: string): AuditActionMeta {
    return actionMeta.value[action] || { value: action, label: action, group: 'system', group_label: '其他', token: 'system' }
  }

  return { entries, loading, actionMeta, load, fetchChain, fetchActions, metaFor }
})
