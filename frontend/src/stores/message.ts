import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '../api'

export const useMessageStore = defineStore('message', () => {
  const unreadCount = ref(0)

  async function refresh() {
    try {
      const { data } = await api.get('/messages/unread-count')
      unreadCount.value = data.count
    } catch {
      /* ignore */
    }
  }

  return { unreadCount, refresh }
})
