import { defineStore } from 'pinia'
import { ref } from 'vue'

type WsCallback = (data: any) => void

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

  function connect() {
    const token = localStorage.getItem('token')
    if (!token) return

    // Determine ws:// or wss:// from current page protocol
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.hostname
    const port = '8000' // backend port
    const url = `${protocol}//${host}:${port}/api/ws?token=${encodeURIComponent(token)}`

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

        // Notify subscribers
        const subs = subscribers.get(msg.type)
        if (subs) {
          subs.forEach(cb => cb(msg.data))
        }
      } catch { /* ignore malformed JSON */ }
    }

    ws.onclose = () => {
      connected.value = false
      cleanupTimers()
      scheduleReconnect()
    }

    ws.onerror = () => {
      // onclose will fire after this, triggering reconnect
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

  return { connected, lastMessage, connect, disconnect, on }
})
