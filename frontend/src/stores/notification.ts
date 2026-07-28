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

  /** Unread counts grouped by project id.  Key = "123", value = total unread. */
  const chatUnreadByProject = computed<Record<number, number>>(() => {
    const map: Record<number, number> = {}
    for (const [key, count] of Object.entries(chatUnreadByConversation.value)) {
      const pid = Number(key.split(':')[0])
      if (!pid || count <= 0) continue
      map[pid] = (map[pid] || 0) + count
    }
    return map
  })

  function projectChatUnread(projectId: number): number {
    return chatUnreadByProject.value[projectId] || 0
  }

  /** Per-member DM unread count for the current project. */
  function dmUnread(projectId: number, userId: number): number {
    return chatUnreadByConversation.value[`${projectId}:dm:${userId}`] || 0
  }

  function incrementChatUnread(conversationKey: string) {
    if (!conversationKey) return
    const prev = chatUnreadByConversation.value[conversationKey] || 0
    chatUnreadByConversation.value[conversationKey] = prev + 1
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
    chatUnreadByConversation,
    chatUnreadByProject,
    dmUnread,
    projectChatUnread,
    incrementChatUnread,
    clearChatUnread,
    resetChatUnread,
  }
})
