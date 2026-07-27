import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

/**
 * Ephemeral per-conversation chat unread state.
 *
 * Persistent system/task notifications live in useMessageStore. Keeping the
 * two domains separate prevents the bell from advertising chat messages that
 * the notification dropdown cannot display.
 */
export const useNotificationStore = defineStore('notification', () => {
  const chatUnreadByConversation = ref<Record<string, number>>({})

  const chatUnread = computed(() => Object.values(chatUnreadByConversation.value)
    .reduce((sum, count) => sum + count, 0))

  function incrementChatUnread(conversationKey: string) {
    if (!conversationKey) return
    chatUnreadByConversation.value[conversationKey] =
      (chatUnreadByConversation.value[conversationKey] || 0) + 1
  }

  function clearChatUnread(conversationKey: string) {
    if (!conversationKey) return
    delete chatUnreadByConversation.value[conversationKey]
  }

  function resetChatUnread() {
    chatUnreadByConversation.value = {}
  }

  return {
    chatUnread,
    incrementChatUnread,
    clearChatUnread,
    resetChatUnread,
  }
})
