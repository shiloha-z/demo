import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '../api'

export interface MessageItem {
  id: number
  recipient_id: number | null
  project_id: number | null
  category: string
  level: string
  title: string
  body: string
  link: string
  read: boolean
  resolved: boolean
  created_at: string | null
}

const PAGE_SIZE = 100

export const useMessageStore = defineStore('message', () => {
  const items = ref<MessageItem[]>([])
  const unreadCount = ref(0)
  const loading = ref(false)
  const loadingMore = ref(false)
  const loaded = ref(false)
  const hasMore = ref(true)

  let refreshRequest: Promise<void> | null = null
  let listRequest: Promise<void> | null = null

  function sortItems() {
    items.value.sort((a, b) => b.id - a.id)
  }

  async function refresh() {
    if (refreshRequest) return refreshRequest
    refreshRequest = (async () => {
      try {
        const { data } = await api.get('/messages/unread-count', { silent: true })
        unreadCount.value = Number(data.count) || 0
      } catch {
        /* Background reconciliation is intentionally silent. */
      }
    })()
    try {
      await refreshRequest
    } finally {
      refreshRequest = null
    }
  }

  async function load(reset = true) {
    if (listRequest) return listRequest
    const beforeId = reset ? undefined : items.value.at(-1)?.id
    if (!reset && (!hasMore.value || beforeId == null)) return

    if (reset) loading.value = true
    else loadingMore.value = true

    listRequest = (async () => {
      const params: Record<string, number> = { limit: PAGE_SIZE }
      if (beforeId != null) params.before_id = beforeId
      const { data } = await api.get('/messages', { params })
      const page = (Array.isArray(data) ? data : []) as MessageItem[]
      if (reset) {
        items.value = page
      } else {
        const knownIds = new Set(items.value.map(item => item.id))
        items.value.push(...page.filter(item => !knownIds.has(item.id)))
      }
      sortItems()
      hasMore.value = page.length === PAGE_SIZE
      loaded.value = true
    })()

    try {
      await listRequest
    } finally {
      listRequest = null
      loading.value = false
      loadingMore.value = false
    }
  }

  async function ensureLoaded() {
    if (!loaded.value) await load(true)
  }

  function receive(message: MessageItem) {
    const existing = items.value.find(item => item.id === message.id)
    if (existing) {
      Object.assign(existing, message)
      return
    }
    items.value.unshift(message)
    sortItems()
    if (!message.read) unreadCount.value += 1
  }

  async function markRead(id: number) {
    const message = items.value.find(item => item.id === id)
    if (message?.read) return
    const previousCount = unreadCount.value
    if (message) message.read = true
    unreadCount.value = Math.max(0, unreadCount.value - 1)
    try {
      await api.post(`/messages/${id}/read`)
    } catch (error) {
      if (message) message.read = false
      unreadCount.value = previousCount
      throw error
    }
  }

  async function markAllRead() {
    const unreadIds = new Set(items.value.filter(item => !item.read).map(item => item.id))
    const previousCount = unreadCount.value
    items.value.forEach(item => { item.read = true })
    unreadCount.value = 0
    try {
      await api.post('/messages/read-all')
    } catch (error) {
      items.value.forEach(item => {
        if (unreadIds.has(item.id)) item.read = false
      })
      unreadCount.value = previousCount
      throw error
    }
  }

  async function dismiss(id: number) {
    const index = items.value.findIndex(item => item.id === id)
    const removed = index >= 0 ? items.value[index] : null
    const previousCount = unreadCount.value
    if (index >= 0) items.value.splice(index, 1)
    if (removed && !removed.read) {
      unreadCount.value = Math.max(0, unreadCount.value - 1)
    }
    try {
      await api.delete(`/messages/${id}`)
    } catch (error) {
      if (removed) {
        items.value.push(removed)
        sortItems()
      }
      unreadCount.value = previousCount
      throw error
    }
  }

  async function dismissAll(category?: string): Promise<number> {
    const snapshot = [...items.value]
    const previousCount = unreadCount.value
    const shouldRemove = (item: MessageItem) => !category || item.category === category
    items.value = items.value.filter(item => !shouldRemove(item))
    unreadCount.value = Math.max(
      0,
      unreadCount.value - snapshot.filter(item => shouldRemove(item) && !item.read).length,
    )
    try {
      const { data } = await api.delete('/messages', {
        params: category ? { category } : undefined,
      })
      await Promise.all([load(true), refresh()])
      return Number(data.count) || 0
    } catch (error) {
      items.value = snapshot
      unreadCount.value = previousCount
      throw error
    }
  }

  function reset() {
    items.value = []
    unreadCount.value = 0
    loaded.value = false
    hasMore.value = true
  }

  return {
    items,
    unreadCount,
    loading,
    loadingMore,
    loaded,
    hasMore,
    refresh,
    load,
    ensureLoaded,
    receive,
    markRead,
    markAllRead,
    dismiss,
    dismissAll,
    reset,
  }
})
