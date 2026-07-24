import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '../api'

export const useMessageStore = defineStore('message', () => {
  const unreadCount = ref(0)

  async function refresh() {
    try {
      // 后台轮询通知数（App.vue 每 30s 调用一次），静默执行，不触发顶部进度条。
      const { data } = await api.get('/messages/unread-count', { silent: true })
      unreadCount.value = data.count
    } catch {
      /* ignore */
    }
  }

  return { unreadCount, refresh }
})
