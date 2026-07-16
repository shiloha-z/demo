import { defineStore } from 'pinia'
import { ref } from 'vue'

type WsCallback = (data: any) => void
type TaskProgressEntry = { message: string; step: string; timestamp: string }

const MAX_TASK_PROGRESS_ENTRIES = 500

export const useWebSocketStore = defineStore('websocket', () => {
  const connected = ref(false)
  const lastMessage = ref<any>(null)

  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let pingTimer: ReturnType<typeof setInterval> | null = null
  let reconnectAttempts = 0
  const maxReconnectAttempts = 10

  // Subscribers: Map<eventType, Set<callback>>
  const subscribers = new Map<string, Set<WsCallback>>()
  // Keep progress outside route components so navigating away does not lose it.
  const taskProgressById = new Map<number, TaskProgressEntry[]>()

  function recordTaskProgress(data: any) {
    const taskId = Number(data?.task_id)
    if (!Number.isInteger(taskId) || taskId <= 0 || !data?.message) return

    const entries = taskProgressById.get(taskId) || []
    entries.push({
      message: String(data.message),
      step: String(data.step || ''),
      timestamp: data.timestamp || new Date().toISOString(),
    })
    if (entries.length > MAX_TASK_PROGRESS_ENTRIES) {
      entries.splice(0, entries.length - MAX_TASK_PROGRESS_ENTRIES)
    }
    taskProgressById.set(taskId, entries)
  }

  function getTaskProgress(taskId: number): TaskProgressEntry[] {
    return [...(taskProgressById.get(taskId) || [])]
  }

  function connect() {
    const token = localStorage.getItem('token')
    if (!token) return
    if (ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING) return

    // Determine ws:// or wss:// from current page protocol
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}/api/ws?token=${encodeURIComponent(token)}`

    try {
      ws = new WebSocket(url)
    } catch {
      scheduleReconnect()
      return
    }

    ws.onopen = () => {
      connected.value = true
      reconnectAttempts = 0
      // Heartbeat: send "ping" every 30s
      pingTimer = setInterval(() => {
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send('ping')
        }
      }, 30_000)
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        lastMessage.value = msg

        // Skip internal messages (connected, pong)
        if (msg.type === 'connected' || msg.type === 'pong') return

        if (msg.type === 'task_progress') {
          recordTaskProgress(msg.data)
        }

        // Notify subscribers
        const subs = subscribers.get(msg.type)
        if (subs) {
          subs.forEach(cb => cb(msg.data))
        }
      } catch { /* ignore malformed JSON */ }
    }

    ws.onclose = (event) => {
      connected.value = false
      cleanupTimers()
      // Don't reconnect on auth failure (1008) or normal closure (1000)
      if (event.code === 1008 || event.code === 1000) {
        reconnectAttempts = maxReconnectAttempts // prevent reconnect
        return
      }
      scheduleReconnect()
    }

    ws.onerror = () => {
      // onclose will fire after this
      ws?.close()
    }
  }

  function disconnect() {
    cleanupTimers()
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    reconnectAttempts = maxReconnectAttempts // prevent reconnect
    if (ws) {
      ws.close()
      ws = null
    }
    connected.value = false
    taskProgressById.clear()
  }

  function scheduleReconnect() {
    if (reconnectAttempts >= maxReconnectAttempts) return
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30_000)
    reconnectAttempts++
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      connect()
    }, delay)
  }

  function cleanupTimers() {
    if (pingTimer) {
      clearInterval(pingTimer)
      pingTimer = null
    }
  }

  /**
   * Subscribe to a specific event type. Returns an unsubscribe function.
   * Usage: const unsub = wsStore.on('task_update', (data) => { ... })
   */
  function on(eventType: string, callback: WsCallback): () => void {
    if (!subscribers.has(eventType)) {
      subscribers.set(eventType, new Set())
    }
    subscribers.get(eventType)!.add(callback)

    // Return unsubscribe function
    return () => {
      const subs = subscribers.get(eventType)
      if (subs) {
        subs.delete(callback)
        if (subs.size === 0) subscribers.delete(eventType)
      }
    }
  }

  /** Send a raw string over the WebSocket (e.g., typing indicator). */
  function send(data: string) {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(data)
    }
  }

  return { connected, lastMessage, connect, disconnect, on, send, getTaskProgress }
})
