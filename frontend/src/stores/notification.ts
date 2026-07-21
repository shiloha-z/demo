import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useMessageStore } from './message'

/**
 * Unified notification store.
 *
 * Aggregates unread counts from two sources into a single badge:
 *   - system / task messages   (useMessageStore.unreadCount)
 *   - chat conversations        (chatUnread)
 * so the top bar only needs ONE notification dot instead of two.
 */
export const useNotificationStore = defineStore('notification', () => {
  const chatUnread = ref(0)

  function incrementChatUnread() {
    chatUnread.value++
  }
  function resetChatUnread() {
    chatUnread.value = 0
  }

  const msgStore = useMessageStore()
  const total = computed(() => chatUnread.value + msgStore.unreadCount)

  return { chatUnread, incrementChatUnread, resetChatUnread, total }
})
