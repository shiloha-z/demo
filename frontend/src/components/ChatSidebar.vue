<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, computed, watch } from 'vue'
import { useWebSocketStore } from '../stores/websocket'
import { useAuthStore } from '../stores/auth'
import { useProjectStore } from '../stores/project'
import { useNotificationStore } from '../stores/notification'
import { MessagePlugin } from 'tdesign-vue-next'
import api, { getErrorMessage } from '../api'
import { renderMarkdown } from '../utils/markdown'
import { playChatPop } from '../utils/notificationSound'

const props = defineProps<{
  visible: boolean
  focusMessageId?: number | null
}>()
const emit = defineEmits<{
  'update:visible': [value: boolean]
  'unreadCount': [conversationKey: string]
  'conversationViewed': [conversationKey: string]
}>()

const ws = useWebSocketStore()
const auth = useAuthStore()
const projectStore = useProjectStore()
const notifStore = useNotificationStore()

// ── Chat mode: team | dm ──────────────────────────────────────────
type ChatMode = 'team' | 'dm'
interface ChatMember {
  id: number
  username: string
  display_name: string
  avatar_url?: string
  role: string
}
interface ChatMemberProfile extends ChatMember {
  bio: string
  email: string
  phone: string
}
const chatMode = ref<ChatMode>('team')
const dmUser = ref<ChatMember | null>(null)
const members = ref<ChatMember[]>([])

// ── @mention autocomplete ─────────────────────────────────────────
const mentionActive = ref(false)
const mentionQuery = ref('')
const mentionIndex = ref(0)
const inputEl = ref<HTMLTextAreaElement>()
const filteredMembers = computed(() => {
  const q = mentionQuery.value.trim().toLocaleLowerCase()
  const onlineIds = new Set(onlineUsers.value.map(u => u.user_id))
  // Online members first, then the rest
  const sorted = [...members.value].sort((a, b) => {
    const aOn = onlineIds.has(a.id) ? 0 : 1
    const bOn = onlineIds.has(b.id) ? 0 : 1
    return aOn - bOn
  })
  if (!q) return sorted.slice(0, 8)
  return sorted.filter(m =>
    m.username.toLocaleLowerCase().includes(q)
    || m.display_name.toLocaleLowerCase().includes(q)
  ).slice(0, 8)
})

function updateMentionFromCaret(el: HTMLTextAreaElement) {
  const val = el.value
  const cursor = el.selectionStart ?? 0
  if (chatMode.value !== 'team') {
    mentionActive.value = false
    return
  }
  // Match the unfinished token immediately before the caret. Unlike \w,
  // this also supports Chinese display-name queries.
  const beforeCursor = val.slice(0, cursor)
  const match = beforeCursor.match(/@([^\s@]*)$/u)
  if (match) {
    const nextQuery = match[1]
    if (!mentionActive.value || mentionQuery.value !== nextQuery) {
      mentionIndex.value = 0
    }
    mentionActive.value = true
    mentionQuery.value = nextQuery
  } else {
    mentionActive.value = false
  }
}

function onInputWithMention(e: Event) {
  updateMentionFromCaret(e.target as HTMLTextAreaElement)
  onInput()
}

function onInputCaretMove(e: Event) {
  updateMentionFromCaret(e.target as HTMLTextAreaElement)
}

function closeMentionMenu() {
  mentionActive.value = false
}

function insertMention(member: ChatMember) {
  const el = inputEl.value
  if (!el) return
  const val = inputText.value
  const cursor = el.selectionStart ?? 0
  const beforeCursor = val.slice(0, cursor)
  const afterCursor = val.slice(cursor)
  const atPos = beforeCursor.lastIndexOf('@')
  if (atPos === -1) return
  const newText = beforeCursor.slice(0, atPos) + `@${member.username} ` + afterCursor
  inputText.value = newText
  mentionActive.value = false
  el.focus()
  nextTick(() => {
    const pos = atPos + member.username.length + 2
    el.setSelectionRange(pos, pos)
  })
}

function handleMentionKeydown(e: KeyboardEvent): boolean {
  if (!mentionActive.value) return false
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    mentionIndex.value = Math.min(mentionIndex.value + 1, Math.max(filteredMembers.value.length - 1, 0))
    return true
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    mentionIndex.value = Math.max(mentionIndex.value - 1, 0)
    return true
  }
  else if (e.key === 'Enter' || e.key === 'Tab') {
    const m = filteredMembers.value[mentionIndex.value]
    if (m) {
      e.preventDefault()
      insertMention(m)
      return true
    }
    mentionActive.value = false
    if (e.key === 'Tab') {
      e.preventDefault()
      return true
    }
  }
  else if (e.key === 'Escape') {
    e.preventDefault()
    mentionActive.value = false
    return true
  }
  return false
}

function handleChatKeydown(e: KeyboardEvent) {
  if (handleMentionKeydown(e)) return
  handleKeydown(e)
}

function renderMsgWithMentions(text: string): string {
  if (!text) return ''
  const html = renderMsg(text)
  const template = document.createElement('template')
  template.innerHTML = html
  const walker = document.createTreeWalker(template.content, NodeFilter.SHOW_TEXT)
  const textNodes: Text[] = []
  let node: Node | null
  while ((node = walker.nextNode())) textNodes.push(node as Text)
  for (const textNode of textNodes) {
    if (textNode.parentElement?.closest('code, pre, a')) continue
    const parts = textNode.data.split(/(@\w+)/g)
    if (parts.length === 1) continue
    const fragment = document.createDocumentFragment()
    for (const part of parts) {
      if (/^@\w+$/.test(part)) {
        const span = document.createElement('span')
        span.className = 'mention-tag'
        span.textContent = part
        fragment.appendChild(span)
      } else {
        fragment.appendChild(document.createTextNode(part))
      }
    }
    textNode.replaceWith(fragment)
  }
  return template.innerHTML
}

interface ChatMsg {
  id: number
  user_id: number
  username: string
  display_name?: string
  avatar_url?: string
  message: string
  project_id?: number
  recipient_id?: number | null
  created_at: string
  system?: boolean
  file_url?: string
  file_name?: string
  file_type?: string
  file_size?: number
}

function conversationKeyForMessage(message: ChatMsg): string {
  const projectId = message.project_id ?? projectStore.currentProject?.id
  if (projectId == null) return ''
  if (message.recipient_id == null) return `${projectId}:team`
  const otherUserId = message.user_id === auth.userId
    ? message.recipient_id
    : message.user_id
  return `${projectId}:dm:${otherUserId}`
}

function activeConversationKey(): string {
  const projectId = projectStore.currentProject?.id
  if (projectId == null) return ''
  return chatMode.value === 'dm' && dmUser.value
    ? `${projectId}:dm:${dmUser.value.id}`
    : `${projectId}:team`
}

function dmUnreadForMember(memberId: number): number {
  const pid = projectStore.currentProject?.id
  return pid ? notifStore.dmUnread(pid, memberId) : 0
}

function markActiveConversationViewed() {
  const key = activeConversationKey()
  if (props.visible && key) emit('conversationViewed', key)
}

interface OnlineUser {
  user_id: number
  username: string
  display_name: string
}

const messages = ref<ChatMsg[]>([])
const onlineUsers = ref<OnlineUser[]>([])
const typingUsers = ref<Map<number, { username: string; timer: ReturnType<typeof setTimeout> }>>(new Map())
const inputText = ref('')
const sending = ref(false)
const scrollEl = ref<HTMLElement>()
const loading = ref(false)
const hasMore = ref(true)
const showOnlineUsers = ref(true)
const newMessagesBelow = ref(0)
const fileInput = ref<HTMLInputElement>()
const uploading = ref(false)
const lightboxImage = ref<string | null>(null)
const memberProfile = ref<ChatMemberProfile | null>(null)
const memberProfileOpen = ref(false)
const memberProfileLoading = ref(false)
const memberProfileError = ref('')
let memberProfileRequest = 0

let unsubChat: (() => void) | null = null
let unsubOnline: (() => void) | null = null
let unsubOffline: (() => void) | null = null
let unsubTyping: (() => void) | null = null
let typingTimer: ReturnType<typeof setTimeout> | null = null
let focusTimer: ReturnType<typeof setTimeout> | null = null
const focusedMessageId = ref<number | null>(null)

// ── Grouped messages with date separators ─────────────────────
interface MessageGroup {
  date: string
  items: (ChatMsg & { showAvatar: boolean; showMeta: boolean })[]
}

const groupedMessages = computed<MessageGroup[]>(() => {
  const groups: MessageGroup[] = []
  let currentDate = ''
  let lastUserId = -1

  for (const msg of messages.value) {
    const msgDate = formatDateLabel(msg.created_at)
    if (msgDate !== currentDate) {
      currentDate = msgDate
      lastUserId = -1
      groups.push({ date: msgDate, items: [] })
    }
    const group = groups[groups.length - 1]
    const showMeta = msg.user_id !== lastUserId || Boolean(msg.system)
    group.items.push({ ...msg, showAvatar: showMeta, showMeta })
    lastUserId = msg.user_id
  }
  return groups
})

const typingText = computed(() => {
  const names = [...typingUsers.value.values()].map(u => u.username)
  if (names.length === 0) return ''
  if (names.length === 1) return `${names[0]} 正在输入...`
  if (names.length === 2) return `${names[0]}、${names[1]} 正在输入...`
  return `${names[0]} 等 ${names.length} 人正在输入...`
})

const memberProfileOnline = computed(() =>
  memberProfile.value
    ? onlineUsers.value.some(user => user.user_id === memberProfile.value?.id)
    : false,
)

const canStartProfileDM = computed(() =>
  Boolean(
    memberProfile.value
    && memberProfile.value.id !== auth.userId
    && members.value.some(member => member.id === memberProfile.value?.id),
  ),
)

// ── Lifecycle ──────────────────────────────────────────────────
onMounted(async () => {
  setupWS()
  if (projectStore.currentProject) {
    joinProjectRoom(projectStore.currentProject.id)
  }
  document.addEventListener('paste', onGlobalPaste)
  document.addEventListener('keydown', onGlobalKeydown)
})

onUnmounted(() => {
  unsubChat?.()
  unsubOnline?.()
  unsubOffline?.()
  unsubTyping?.()
  sendTyping(false)
  if (typingTimer) clearTimeout(typingTimer)
  for (const entry of typingUsers.value.values()) clearTimeout(entry.timer)
  if (focusTimer) clearTimeout(focusTimer)
  document.removeEventListener('paste', onGlobalPaste)
  document.removeEventListener('keydown', onGlobalKeydown)
})

// Watch for project changes — switch chat room when user selects a different project
watch(() => projectStore.currentProject?.id, (newId, oldId) => {
  closeMemberProfile()
  if (newId && newId !== oldId) {
    joinProjectRoom(newId)
  } else if (!newId) {
    // No project selected — clear chat
    messages.value = []
    onlineUsers.value = []
    members.value = []
    newMessagesBelow.value = 0
  }
})

watch(() => ws.connected, (connected, wasConnected) => {
  const projectId = projectStore.currentProject?.id
  if (connected && wasConnected === false && projectId != null) {
    void rejoinAndReconcile(projectId)
  }
})

function switchToTeam() {
  sendTyping(false)
  mentionActive.value = false
  chatMode.value = 'team'
  dmUser.value = null
  messages.value = []
  newMessagesBelow.value = 0
  void loadMessages()
  markActiveConversationViewed()
}

function switchToDM(user: ChatMember) {
  sendTyping(false)
  mentionActive.value = false
  chatMode.value = 'dm'
  dmUser.value = user
  messages.value = []
  newMessagesBelow.value = 0
  void loadMessages()
  markActiveConversationViewed()
}

function roleLabel(role: string): string {
  return {
    owner: '项目负责人',
    admin: '项目管理员',
    member: '项目成员',
    security_reviewer: '安全复核人',
    auditor: '审计人员',
    former_member: '历史成员',
  }[role] || role || '项目成员'
}

async function openMemberProfile(message: ChatMsg) {
  if (message.system || !message.user_id) return
  const knownMember = members.value.find(member => member.id === message.user_id)
  memberProfile.value = {
    id: message.user_id,
    username: message.username,
    display_name: message.display_name || message.username,
    avatar_url: message.avatar_url || knownMember?.avatar_url || '',
    role: knownMember?.role || 'member',
    bio: '',
    email: '',
    phone: '',
  }
  memberProfileError.value = ''
  memberProfileOpen.value = true
  memberProfileLoading.value = true
  const requestId = ++memberProfileRequest
  const projectId = projectStore.currentProject?.id
  if (projectId == null) {
    memberProfileLoading.value = false
    return
  }
  try {
    const { data } = await api.get(`/chat/members/${message.user_id}/profile`, {
      params: { project_id: projectId },
      silent: true,
    } as any)
    if (requestId !== memberProfileRequest || !memberProfileOpen.value) return
    memberProfile.value = data
  } catch (error) {
    if (requestId !== memberProfileRequest || !memberProfileOpen.value) return
    memberProfileError.value = getErrorMessage(error, '成员资料加载失败')
  } finally {
    if (requestId === memberProfileRequest) memberProfileLoading.value = false
  }
}

function closeMemberProfile() {
  memberProfileRequest += 1
  memberProfileOpen.value = false
  memberProfileLoading.value = false
  memberProfileError.value = ''
}

function startProfileDM() {
  const profile = memberProfile.value
  if (!profile || !canStartProfileDM.value) return
  const member = members.value.find(item => item.id === profile.id)
  if (!member) {
    MessagePlugin.warning('该用户已不是当前项目成员，无法发起私聊')
    return
  }
  closeMemberProfile()
  switchToDM(member)
}

function onGlobalKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  if (memberProfileOpen.value) {
    closeMemberProfile()
  } else {
    mentionActive.value = false
  }
}

async function joinProjectRoom(projectId: number) {
  try {
    ws.send(JSON.stringify({ type: 'join_project', project_id: projectId }))
  } catch { /* ignore */ }
  messages.value = []
  chatMode.value = 'team'
  dmUser.value = null
  inputText.value = ''
  mentionActive.value = false
  newMessagesBelow.value = 0
  await loadMessages()
  await loadOnlineUsers()
  await loadMembers()
  markActiveConversationViewed()
}

async function rejoinAndReconcile(projectId: number) {
  try {
    ws.send(JSON.stringify({ type: 'join_project', project_id: projectId }))
  } catch { /* connection state is checked by the watcher */ }
  await Promise.all([reconcileLatestMessages(), loadOnlineUsers(), loadMembers()])
}

function setupWS() {
  unsubChat = ws.on('chat_message', (data: ChatMsg & { system?: boolean }) => {
    const currentPid = projectStore.currentProject?.id
    if (currentPid == null) return
    const isCurrentProject = data.project_id === currentPid
    const belongsToActiveConversation = isCurrentProject
      && conversationKeyForMessage(data) === activeConversationKey()
    const wasNearBottom = isNearBottom()

    // Cross-project messages: still count as unread but don't display here.
    if (!isCurrentProject) {
      if (data.user_id !== auth.userId) {
        emit('unreadCount', conversationKeyForMessage(data))
        playChatPop()
      }
      return
    }

    if (!belongsToActiveConversation) {
      if (data.user_id !== auth.userId) {
        emit('unreadCount', conversationKeyForMessage(data))
        playChatPop()
      }
      return
    }
    if (!messages.value.some(m => m.id === data.id)) {
      messages.value.push(data)
      const isOwnMessage = data.user_id === auth.userId
      if (isOwnMessage || (props.visible && wasNearBottom)) {
        newMessagesBelow.value = 0
        scrollToBottom()
        if (props.visible) markActiveConversationViewed()
      } else {
        if (props.visible) newMessagesBelow.value += 1
        if (!isOwnMessage) {
          emit('unreadCount', conversationKeyForMessage(data))
          playChatPop()
        }
      }
    }
  })
  unsubOnline = ws.on('user_online', (data: { user_id: number; username: string; display_name: string; online_users: OnlineUser[] }) => {
    onlineUsers.value = data.online_users || []
  })
  unsubOffline = ws.on('user_offline', (data: { user_id: number; online_users: OnlineUser[] }) => {
    onlineUsers.value = data.online_users || []
    typingUsers.value.delete(data.user_id)
  })
  unsubTyping = ws.on('user_typing', (data: { user_id: number; username: string; display_name: string; project_id?: number; recipient_id?: number | null; typing: boolean }) => {
    // Only process typing for the current project
    const currentPid = projectStore.currentProject?.id
    if (currentPid == null || data.project_id !== currentPid) return
    if (data.user_id === auth.userId) return
    const typingConversation = data.recipient_id == null
      ? `${currentPid}:team`
      : `${currentPid}:dm:${data.user_id}`
    if (typingConversation !== activeConversationKey()) return
    if (data.typing) {
      const existing = typingUsers.value.get(data.user_id)
      if (existing) clearTimeout(existing.timer)
      typingUsers.value.set(data.user_id, {
        username: data.display_name || data.username,
        timer: setTimeout(() => typingUsers.value.delete(data.user_id), 4000),
      })
    } else {
      typingUsers.value.delete(data.user_id)
    }
  })
}

// ── Load ───────────────────────────────────────────────────────
async function loadMembers() {
  const pid = projectStore.currentProject?.id
  if (pid == null) return
  try {
    const { data } = await api.get('/chat/members', { params: { project_id: pid } })
    if (projectStore.currentProject?.id !== pid) return
    members.value = data.members || []
  } catch { /* ignore */ }
}

async function loadMessages(beforeId?: number) {
  const pid = projectStore.currentProject?.id
  if (pid == null) return
  const requestConversationKey = activeConversationKey()
  loading.value = true
  try {
    const params: Record<string, any> = { project_id: pid, limit: 50 }
    if (chatMode.value === 'dm' && dmUser.value) params.recipient_id = dmUser.value.id
    if (beforeId) params.before_id = beforeId
    const viewport = scrollEl.value
    const previousScrollHeight = viewport?.scrollHeight ?? 0
    const previousScrollTop = viewport?.scrollTop ?? 0
    const { data } = await api.get('/chat/messages', { params, silent: true } as any)
    if (activeConversationKey() !== requestConversationKey) return
    const arr: ChatMsg[] = Array.isArray(data) ? data : []
    if (beforeId && arr.length === 0) {
      hasMore.value = false
    } else if (!beforeId) {
      messages.value = arr
      hasMore.value = arr.length >= 50
      await nextTick()
      if (!focusRequestedMessage()) scrollToBottom()
    } else {
      const knownIds = new Set(messages.value.map(message => message.id))
      messages.value = [...arr.filter(message => !knownIds.has(message.id)), ...messages.value]
      hasMore.value = arr.length >= 50
      await nextTick()
      if (viewport) {
        viewport.scrollTop = viewport.scrollHeight - previousScrollHeight + previousScrollTop
      }
    }
  } catch (error) {
    MessagePlugin.error(getErrorMessage(error, '聊天记录加载失败'))
  }
  finally { loading.value = false }
}

async function reconcileLatestMessages() {
  const pid = projectStore.currentProject?.id
  if (pid == null) return
  const requestConversationKey = activeConversationKey()
  const params: Record<string, any> = { project_id: pid, limit: 50 }
  if (chatMode.value === 'dm' && dmUser.value) params.recipient_id = dmUser.value.id
  try {
    const wasNearBottom = isNearBottom()
    const { data } = await api.get('/chat/messages', { params, silent: true } as any)
    if (activeConversationKey() !== requestConversationKey) return
    const latest: ChatMsg[] = Array.isArray(data) ? data : []
    const knownIds = new Set(messages.value.map(message => message.id))
    const missed = latest.filter(message => !knownIds.has(message.id))
    if (!missed.length) return
    const merged = new Map(messages.value.map(message => [message.id, message]))
    for (const message of latest) merged.set(message.id, message)
    messages.value = [...merged.values()].sort((a, b) => a.id - b.id)
    const incomingCount = missed.filter(message => message.user_id !== auth.userId).length
    if (props.visible && wasNearBottom) {
      scrollToBottom()
      markActiveConversationViewed()
    } else if (incomingCount) {
      if (props.visible) newMessagesBelow.value += incomingCount
      for (let index = 0; index < incomingCount; index += 1) {
        emit('unreadCount', activeConversationKey())
      }
    }
  } catch {
    // The next reconnect or explicit conversation switch retries the sync.
  }
}

async function loadOnlineUsers() {
  try {
    const pid = projectStore.currentProject?.id
    if (pid == null) return
    const { data } = await api.get('/chat/online', { params: { project_id: pid }, silent: true } as any)
    onlineUsers.value = data.online_users || []
  } catch { /* ignore */ }
}

// ── Scroll ─────────────────────────────────────────────────────
function onScroll() {
  if (!scrollEl.value) return
  if (isNearBottom()) {
    newMessagesBelow.value = 0
    markActiveConversationViewed()
  }
  if (loading.value || !hasMore.value) return
  if (scrollEl.value.scrollTop < 60) {
    const firstId = messages.value[0]?.id
    if (firstId) loadMessages(firstId)
  }
}

function isNearBottom(threshold = 80): boolean {
  const element = scrollEl.value
  if (!element) return true
  return element.scrollHeight - element.scrollTop - element.clientHeight <= threshold
}

function scrollToBottom(behavior: ScrollBehavior = 'auto') {
  nextTick(() => {
    if (scrollEl.value) {
      scrollEl.value.scrollTo({ top: scrollEl.value.scrollHeight, behavior })
    }
  })
}

function jumpToLatest() {
  newMessagesBelow.value = 0
  scrollToBottom('smooth')
  markActiveConversationViewed()
}

function focusRequestedMessage(): boolean {
  const id = Number(props.focusMessageId)
  if (!id || !scrollEl.value) return false
  const target = scrollEl.value.querySelector<HTMLElement>(`[data-message-id="${id}"]`)
  if (!target) return false
  target.scrollIntoView({ block: 'center', behavior: 'smooth' })
  focusedMessageId.value = id
  if (focusTimer) clearTimeout(focusTimer)
  focusTimer = setTimeout(() => {
    if (focusedMessageId.value === id) focusedMessageId.value = null
  }, 3000)
  return true
}

// ── Send ───────────────────────────────────────────────────────
async function sendMessage() {
  const text = inputText.value.trim()
  if (!text && !pendingFiles.value.length) return
  if (sending.value) return

  sending.value = true
  const targetConversationKey = activeConversationKey()
  const targetRecipientId = chatMode.value === 'dm' ? dmUser.value?.id : undefined
  try {
    // Upload pending files first
    for (const pf of pendingFiles.value) {
      await uploadAndSendFile(pf, targetRecipientId)
    }
    pendingFiles.value = []

    // Send text message
    if (text) {
      const pid = projectStore.currentProject?.id
      if (pid == null) return
      const form = new FormData()
      form.append('project_id', String(pid))
      form.append('message', text)
      if (targetRecipientId != null) {
        form.append('recipient_id', String(targetRecipientId))
      }
      const { data } = await api.post('/chat/messages', form)
      // Optimistically add message to local list so it appears immediately.
      // Dedup: the WebSocket broadcast will also deliver it, so skip duplicates.
      if (activeConversationKey() === targetConversationKey && !messages.value.some(m => m.id === data.id)) {
        messages.value.push(data)
        scrollToBottom()
      }
      if (activeConversationKey() === targetConversationKey && inputText.value.trim() === text) {
        inputText.value = ''
      }
      sendTyping(false)
    }
  } catch (error) {
    MessagePlugin.error(getErrorMessage(error, '消息发送失败，请重试'))
  }
  finally { sending.value = false }
}

// ── File upload ────────────────────────────────────────────────
const pendingFiles = ref<File[]>([])

function triggerFileInput() {
  fileInput.value?.click()
}

async function handleFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  const files = input.files
  if (!files || files.length === 0) return

  const targetRecipientId = chatMode.value === 'dm' ? dmUser.value?.id : undefined
  for (const f of files) {
    await uploadAndSendFile(f, targetRecipientId)
  }
  input.value = ''
}

async function uploadAndSendFile(
  file: File,
  targetRecipientId = chatMode.value === 'dm' ? dmUser.value?.id : undefined,
) {
  uploading.value = true
  try {
    const pid = projectStore.currentProject?.id
    if (pid == null) return
    const targetConversationKey = targetRecipientId == null
      ? `${pid}:team`
      : `${pid}:dm:${targetRecipientId}`

    // Upload file
    const uploadForm = new FormData()
    uploadForm.append('project_id', String(pid))
    uploadForm.append('file', file)
    const { data } = await api.post('/chat/upload', uploadForm)

    // Send as chat message
    const msgForm = new FormData()
    msgForm.append('project_id', String(pid))
    msgForm.append('message', inputText.value.trim())
    msgForm.append('file_url', data.file_url)
    msgForm.append('file_name', data.file_name)
    msgForm.append('file_type', data.file_type)
    msgForm.append('file_size', String(data.file_size))
    if (targetRecipientId != null) {
      msgForm.append('recipient_id', String(targetRecipientId))
    }
    const response = await api.post('/chat/messages', msgForm)
    if (
      activeConversationKey() === targetConversationKey
      && !messages.value.some(message => message.id === response.data.id)
    ) {
      messages.value.push(response.data)
    }
    if (activeConversationKey() === targetConversationKey) {
      inputText.value = ''
      newMessagesBelow.value = 0
      scrollToBottom()
    }
  } catch (error) {
    MessagePlugin.error(getErrorMessage(error, '文件发送失败，请重试'))
  }
  finally { uploading.value = false }
}

// ── Paste ──────────────────────────────────────────────────────
function onGlobalPaste(e: ClipboardEvent) {
  if (!props.visible) return
  const items = e.clipboardData?.items
  if (!items) return
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      e.preventDefault()
      const blob = item.getAsFile()
      if (blob) {
        uploadAndSendFile(new File([blob], `paste-${Date.now()}.png`, { type: blob.type }))
      }
      break
    }
  }
}

// ── Drag & drop ────────────────────────────────────────────────
function onDragOver(e: DragEvent) {
  e.preventDefault()
  e.dataTransfer!.dropEffect = 'copy'
}
function onDrop(e: DragEvent) {
  e.preventDefault()
  const files = e.dataTransfer?.files
  if (!files) return
  for (const f of files) {
    uploadAndSendFile(f)
  }
}

// ── Lightbox ───────────────────────────────────────────────────
function openLightbox(url: string) {
  lightboxImage.value = url
}
function closeLightbox() {
  lightboxImage.value = null
}

// ── Typing ─────────────────────────────────────────────────────
function sendTyping(isTyping: boolean) {
  try {
    ws.send(JSON.stringify({
      type: 'typing',
      typing: isTyping,
      recipient_id: chatMode.value === 'dm' ? dmUser.value?.id : undefined,
    }))
  } catch { /* ignore */ }
}

function onInput() {
  if (typingTimer) clearTimeout(typingTimer)
  if (inputText.value) {
    sendTyping(true)
    typingTimer = setTimeout(() => sendTyping(false), 2000)
  }
}

// ── Handle Enter key ───────────────────────────────────────────
function handleKeydown(e: KeyboardEvent) {
  if (mentionActive.value) return  // don't send while choosing a mention
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

// ── Formatting ─────────────────────────────────────────────────
const AVATAR_COLORS = [
  '#4f46e5', '#0891b2', '#059669', '#d97706', '#dc2626',
  '#7c3aed', '#db2777', '#2563eb', '#ea580c', '#65a30d',
]

function avatarColor(username: string): string {
  let hash = 0
  for (const c of username) hash = (hash * 31 + c.charCodeAt(0)) | 0
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length]
}

function avatarInitials(username: string): string {
  return username.slice(0, 2).toUpperCase()
}

function formatTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function formatDateLabel(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const msgDay = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const diffDays = Math.round((today.getTime() - msgDay.getTime()) / 86400000)

  if (diffDays === 0) return '今天'
  if (diffDays === 1) return '昨天'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}年${d.getMonth() + 1}月${pad(d.getDate())}日`
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1048576).toFixed(1)} MB`
}

function renderMsg(text: string): string {
  if (!text) return ''
  if (text.includes('```') || text.includes('**') || text.includes('#') || text.includes('> ') || text.includes('- ')) {
    return renderMarkdown(text)
  }
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>')
}

function fileIcon(ext: string): string {
  const map: Record<string, string> = {
    pdf: '📄', doc: '📝', docx: '📝', xls: '📊', xlsx: '📊',
    ppt: '📽️', pptx: '📽️', zip: '📦', rar: '📦', '7z': '📦', tar: '📦', gz: '📦',
    txt: '📃', md: '📝', csv: '📊', json: '📋', xml: '📋',
    py: '🐍', js: '🟨', ts: '🟦', vue: '💚', java: '☕', go: '🔵', rs: '🦀',
  }
  return map[ext] || '📎'
}

// ── Watch visibility ───────────────────────────────────────────
watch(() => props.visible, (v) => {
  if (v) {
    markActiveConversationViewed()
    nextTick(() => {
      if (!focusRequestedMessage()) scrollToBottom()
    })
  } else {
    closeMemberProfile()
  }
})

watch(() => props.focusMessageId, () => {
  if (props.visible) nextTick(focusRequestedMessage)
})
</script>

<template>
  <aside
    class="chat-panel"
    :class="{ open: visible }"
    @dragover="onDragOver"
    @drop="onDrop"
  >
    <!-- Drag overlay -->
    <div class="drag-overlay" v-if="false"></div>

    <!-- ── Header ─────────────────────────── -->
    <div class="chat-header">
      <div class="chat-header-left">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        <template v-if="chatMode === 'dm' && dmUser">
          <span>{{ dmUser.display_name }}</span>
          <button class="chat-mode-btn" @click="switchToTeam()" title="切换回团队聊天">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </template>
        <template v-else>
          <span>团队聊天</span>
          <span class="chat-badge" v-if="onlineUsers.length > 0">{{ onlineUsers.length }} 在线</span>
        </template>
      </div>
      <div class="chat-header-actions">
        <button class="chat-icon-btn" :class="{ active: showOnlineUsers }" title="在线成员" @click="showOnlineUsers = !showOnlineUsers">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
        </button>
        <button class="chat-icon-btn" @click="emit('update:visible', false)" title="关闭">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
    </div>

    <!-- ── Team member / direct-message picker ─────────────── -->
    <div class="chat-online-bar" v-if="showOnlineUsers && members.length > 0">
      <span class="member-picker-label">{{ chatMode === 'dm' ? '切换私聊：' : '团队成员：' }}</span>
      <button
        v-for="m in members" :key="m.id"
        class="dm-chip"
        :class="{ active: dmUser?.id === m.id }"
        @click="switchToDM(m)"
      >
        {{ m.display_name }}
        <span class="dm-chip-dot" :class="{ online: onlineUsers.some(u => u.user_id === m.id) }"></span>
        <span class="dm-chip-unread" v-if="dmUnreadForMember(m.id) > 0">{{ dmUnreadForMember(m.id) > 99 ? '99+' : dmUnreadForMember(m.id) }}</span>
      </button>
    </div>

    <!-- ── Messages ───────────────────────── -->
    <div class="chat-messages" ref="scrollEl" @scroll="onScroll">
      <div v-if="loading && messages.length === 0" class="chat-status">
        <span class="mini-spinner"></span> 加载中...
      </div>
      <div v-else-if="hasMore && messages.length > 0" class="chat-load-more">
        <span v-if="loading" class="mini-spinner"></span>
        <span v-else class="load-more-hint">向上滚动加载历史消息</span>
      </div>

      <template v-if="messages.length === 0 && !loading">
        <div class="chat-empty">
          <!-- No project selected -->
          <template v-if="!projectStore.currentProject">
            <div class="chat-empty-icon">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
            </div>
            <p class="chat-empty-title">请先选择一个项目</p>
            <p class="chat-empty-hint">在左侧边栏选择一个项目后即可开始聊天</p>
          </template>
          <!-- Empty chat in current project -->
          <template v-else>
            <div class="chat-empty-icon">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            </div>
            <p class="chat-empty-title">暂无消息</p>
            <p class="chat-empty-hint">发送消息、粘贴图片或拖拽文件开始交流</p>
          </template>
        </div>
      </template>

      <template v-for="group in groupedMessages" :key="group.date">
        <!-- Date separator -->
        <div class="chat-date-sep"><span>{{ group.date }}</span></div>

        <!-- Messages in group -->
        <div
          v-for="msg in group.items"
          :key="msg.id"
          :data-message-id="msg.id"
          class="chat-msg"
          :class="{
            mine: msg.user_id === auth.userId && !msg.system,
            system: msg.system,
            consecutive: !msg.showMeta,
            focused: focusedMessageId === msg.id,
          }"
        >
          <!-- System message -->
          <template v-if="msg.system">
            <div class="system-msg">{{ msg.message }}</div>
          </template>

          <!-- Normal message -->
          <template v-else>
            <button
              v-if="msg.showAvatar"
              class="msg-avatar-trigger"
              type="button"
              :title="`查看 ${msg.display_name || msg.username} 的资料`"
              :aria-label="`查看 ${msg.display_name || msg.username} 的资料`"
              @click="openMemberProfile(msg)"
            >
              <img v-if="msg.avatar_url" class="msg-avatar-img" :src="msg.avatar_url" />
              <span v-else class="msg-avatar" :style="{ background: avatarColor(msg.username) }">
                {{ avatarInitials(msg.display_name || msg.username) }}
              </span>
            </button>
            <div class="msg-avatar-spacer" v-else />
            <div class="msg-body">
              <div class="msg-meta" v-if="msg.showMeta">
                <span class="msg-user" :style="{ color: avatarColor(msg.username) }">{{ msg.username }}</span>
                <span class="msg-time">{{ formatTime(msg.created_at) }}</span>
              </div>

              <!-- Text content -->
              <div class="msg-bubble" v-if="msg.message" v-html="renderMsgWithMentions(msg.message)" />

              <!-- Image attachment -->
              <div class="msg-attachment" v-if="msg.file_type === 'image' && msg.file_url">
                <img
                  v-image-loading="msg.file_url"
                  :src="msg.file_url"
                  :alt="msg.file_name"
                  class="msg-image"
                  @click="openLightbox(msg.file_url)"
                  loading="lazy"
                />
              </div>

              <!-- File attachment -->
              <div class="msg-attachment" v-if="msg.file_type === 'file' && msg.file_url">
                <a :href="msg.file_url" target="_blank" class="msg-file-card" :download="msg.file_name">
                  <span class="msg-file-icon">{{ fileIcon((msg.file_name || '').split('.').pop() || '') }}</span>
                  <div class="msg-file-info">
                    <span class="msg-file-name">{{ msg.file_name }}</span>
                    <span class="msg-file-size">{{ formatSize(msg.file_size ?? 0) }}</span>
                  </div>
                  <svg class="msg-file-dl" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                </a>
              </div>
            </div>
          </template>
        </div>
      </template>
      <Transition name="inline-rise">
        <button
          v-if="newMessagesBelow > 0"
          class="chat-new-messages"
          @click="jumpToLatest"
        >
          {{ newMessagesBelow }} 条新消息 · 回到最新
        </button>
      </Transition>
    </div>

    <!-- ── Typing indicator ──────────────── -->
    <Transition name="inline-rise">
      <div class="chat-typing" v-if="typingText">
        <span class="typing-dots"><span></span><span></span><span></span></span>
        {{ typingText }}
      </div>
    </Transition>

    <!-- ── Upload indicator ──────────────── -->
    <Transition name="inline-rise">
      <div class="chat-uploading" v-if="uploading">
        <span class="mini-spinner"></span> 上传文件中...
      </div>
    </Transition>

    <!-- ── Input ──────────────────────────── -->
    <div class="chat-input-area">
      <!-- This popup must stay inside the positioned input container. -->
      <Transition name="menu-pop">
        <div
          v-if="mentionActive"
          id="chat-mention-list"
          class="mention-dropdown"
          role="listbox"
          aria-label="可提及的团队成员"
        >
          <div class="mention-dropdown-header">
            <span>选择要提及的成员</span>
            <span>↑↓ 选择 · Enter 补全</span>
          </div>
          <button
            v-for="(m, i) in filteredMembers"
            :id="`chat-mention-${m.id}`"
            :key="m.id"
            class="mention-item"
            :class="{ active: i === mentionIndex }"
            role="option"
            :aria-selected="i === mentionIndex"
            @mousedown.prevent="insertMention(m)"
            @mouseenter="mentionIndex = i"
          >
            <span class="mention-avatar" :style="{ background: avatarColor(m.username) }">
              {{ avatarInitials(m.display_name || m.username) }}
            </span>
            <span class="mention-member">
              <span class="mention-name">{{ m.display_name }}</span>
              <span class="mention-username">@{{ m.username }}</span>
            </span>
            <span class="mention-online-dot" v-if="onlineUsers.some(u => u.user_id === m.id)"></span>
          </button>
          <div v-if="filteredMembers.length === 0" class="mention-empty">
            {{ members.length === 0 ? '当前项目暂无其他可提及成员' : `未找到“${mentionQuery}”` }}
          </div>
        </div>
      </Transition>
      <input
        ref="fileInput"
        type="file"
        multiple
        style="display:none"
        @change="handleFileSelect"
      />
      <button
        class="chat-attach-btn"
        title="发送文件或图片"
        :disabled="uploading || !projectStore.currentProject"
        @click="triggerFileInput"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
      </button>
      <textarea
        ref="inputEl"
        v-model="inputText"
        class="chat-input"
        :placeholder="projectStore.currentProject ? '输入消息，输入 @ 提及团队成员...' : '请先在左侧边栏选择一个项目'"
        rows="2"
        maxlength="2000"
        :disabled="!projectStore.currentProject"
        :aria-expanded="mentionActive"
        aria-controls="chat-mention-list"
        :aria-activedescendant="mentionActive && filteredMembers[mentionIndex] ? `chat-mention-${filteredMembers[mentionIndex].id}` : undefined"
        @keydown="handleChatKeydown"
        @keyup="onInputCaretMove"
        @click="onInputCaretMove"
        @blur="closeMentionMenu"
        @input="onInputWithMention"
      />
      <button
        class="chat-send-btn"
        :disabled="(!inputText.trim() && pendingFiles.length === 0) || sending || !projectStore.currentProject"
        @click="sendMessage"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
      </button>
    </div>

    <!-- ── Member profile ─────────────────── -->
    <Teleport to="body">
      <Transition name="profile-card-fade">
        <div
          v-if="memberProfileOpen && memberProfile"
          class="member-profile-backdrop"
          @click="closeMemberProfile"
        >
          <section
            class="member-profile-card"
            role="dialog"
            aria-modal="true"
            :aria-label="`${memberProfile.display_name} 的个人资料`"
            @click.stop
          >
            <button class="member-profile-close" type="button" title="关闭" @click="closeMemberProfile">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
            <div class="member-profile-hero">
              <img
                v-if="memberProfile.avatar_url"
                v-image-loading="memberProfile.avatar_url"
                :src="memberProfile.avatar_url"
                class="member-profile-avatar"
                :alt="memberProfile.display_name"
              />
              <div
                v-else
                class="member-profile-avatar member-profile-avatar-fallback"
                :style="{ background: avatarColor(memberProfile.username) }"
              >
                {{ avatarInitials(memberProfile.display_name || memberProfile.username) }}
              </div>
              <div class="member-profile-identity">
                <h3>{{ memberProfile.display_name }}</h3>
                <p>@{{ memberProfile.username }}</p>
                <div class="member-profile-badges">
                  <span class="member-role-badge">{{ roleLabel(memberProfile.role) }}</span>
                  <span class="member-online-badge" :class="{ online: memberProfileOnline }">
                    <i></i>{{ memberProfileOnline ? '在线' : '离线' }}
                  </span>
                </div>
              </div>
            </div>
            <div class="member-profile-content">
              <div class="member-profile-section-title">个人简介</div>
              <p class="member-profile-bio">
                {{ memberProfile.bio || '该成员暂未填写个人简介。' }}
              </p>
              <div class="member-profile-section-title" style="margin-top: 14px;">联系方式</div>
              <div class="member-profile-contact">
                <div class="contact-row">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>
                  <span>{{ memberProfile.email || '未填写邮箱' }}</span>
                </div>
                <div class="contact-row">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>
                  <span>{{ memberProfile.phone || '未填写电话' }}</span>
                </div>
              </div>
              <div v-if="memberProfileLoading" class="member-profile-loading">
                <span class="mini-spinner"></span> 正在加载资料...
              </div>
              <p v-else-if="memberProfileError" class="member-profile-error">
                {{ memberProfileError }}
              </p>
            </div>
            <div class="member-profile-actions">
              <span v-if="memberProfile.id === auth.userId" class="member-profile-self">这是你自己</span>
              <button
                v-else
                class="member-profile-dm"
                type="button"
                :disabled="!canStartProfileDM"
                @click="startProfileDM"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                发起私聊
              </button>
            </div>
          </section>
        </div>
      </Transition>
    </Teleport>

    <!-- ── Lightbox ──────────────────────── -->
    <Teleport to="body">
      <Transition name="lightbox-fade">
        <div class="lightbox-backdrop" v-if="lightboxImage" @click="closeLightbox">
          <img
            v-image-loading="lightboxImage"
            :src="lightboxImage"
            class="lightbox-img"
            @click.stop
          />
          <button class="lightbox-close" @click="closeLightbox" title="关闭">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
      </Transition>
    </Teleport>
  </aside>
</template>

<style scoped>
.chat-panel {
  --chat-open-duration: 380ms;
  position: absolute;
  inset: 0 0 0 auto;
  width: min(360px, 100vw);
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--glass-surface-strong);
  -webkit-backdrop-filter: blur(var(--glass-blur-lg)) saturate(var(--glass-saturate));
  backdrop-filter: blur(var(--glass-blur-lg)) saturate(var(--glass-saturate));
  border-left: 1px solid var(--glass-border);
  box-shadow: -12px 0 34px color-mix(in oklch, var(--primary-glow) 34%, transparent), var(--glass-highlight);
  transition:
    width var(--chat-open-duration) var(--motion-ease-spring),
    transform var(--chat-open-duration) var(--motion-ease-spring),
    opacity var(--motion-base) var(--motion-ease-standard),
    box-shadow var(--motion-slow) var(--motion-ease-standard),
    -webkit-backdrop-filter 150ms var(--motion-ease-standard) 130ms,
    backdrop-filter 150ms var(--motion-ease-standard) 130ms,
    visibility 0s linear;
  overflow: hidden;
  z-index: 200;
  contain: layout style;
  transform: translate3d(0, 0, 0) scaleX(1);
  transform-origin: right center;
  will-change: width, transform, opacity;
}
.chat-panel:not(.open) {
  width: 0;
  border-left: none;
  opacity: 0;
  transform: translate3d(18px, 0, 0) scaleX(0.985);
  -webkit-backdrop-filter: blur(0) saturate(1);
  backdrop-filter: blur(0) saturate(1);
  box-shadow: none;
  visibility: hidden;
  pointer-events: none;
  transition:
    width var(--motion-slow) var(--motion-ease-exit),
    transform var(--motion-slow) var(--motion-ease-exit),
    opacity var(--motion-fast) var(--motion-ease-exit),
    box-shadow var(--motion-fast) var(--motion-ease-exit),
    -webkit-backdrop-filter 80ms linear,
    backdrop-filter 80ms linear,
    visibility 0s linear var(--motion-slow);
}
.chat-panel::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  z-index: 4;
  width: 2px;
  pointer-events: none;
  background: linear-gradient(
    transparent 4%,
    color-mix(in oklch, var(--primary) 42%, transparent) 24%,
    color-mix(in oklch, var(--ambient-spot-cyan) 66%, var(--primary)) 54%,
    color-mix(in oklch, var(--primary) 36%, transparent) 80%,
    transparent 96%
  );
  opacity: 0.84;
  transform: scaleY(0.82);
  transition:
    opacity var(--motion-base) var(--motion-ease-standard) 100ms,
    transform var(--chat-open-duration) var(--motion-ease-spring) 70ms;
}
.chat-panel:not(.open)::before {
  opacity: 0;
  transform: scaleY(0.25);
  transition-delay: 0s;
}
.chat-panel > * {
  min-width: min(360px, 100vw);
}

.chat-panel > :is(.chat-header, .chat-online-bar, .chat-messages, .chat-typing, .chat-uploading, .chat-input-area) {
  transition:
    opacity var(--motion-base) var(--motion-ease-standard),
    transform var(--motion-slow) var(--motion-ease-spring);
  transition-delay: var(--chat-content-delay, 70ms);
}

.chat-panel:not(.open) > :is(.chat-header, .chat-online-bar, .chat-messages, .chat-typing, .chat-uploading, .chat-input-area) {
  opacity: 0;
  transform: translate3d(14px, 0, 0) scale(0.995);
  transition-delay: 0s;
}

.chat-panel > .chat-header { --chat-content-delay: 55ms; }
.chat-panel > .chat-online-bar { --chat-content-delay: 80ms; }
.chat-panel > .chat-messages { --chat-content-delay: 105ms; }
.chat-panel > :is(.chat-typing, .chat-uploading) { --chat-content-delay: 120ms; }
.chat-panel > .chat-input-area { --chat-content-delay: 135ms; }

/* ── Header ─────────────────────────── */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--surface-border);
  background: var(--glass-surface-soft);
  box-shadow: var(--glass-highlight);
  flex-shrink: 0;
}
.chat-header-left { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 700; color: var(--foreground); }
.chat-badge {
  font-size: 10.5px; font-weight: 600; color: var(--success);
  background: var(--success-light); padding: 1px 7px; border-radius: 999px;
  animation: chat-badge-in 300ms var(--motion-ease-spring) both;
}
.chat-header-actions { display: flex; gap: 2px; }
.chat-icon-btn {
  width: 30px; height: 30px; border-radius: var(--radius-sm);
  border: none; background: transparent; color: var(--muted-foreground);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: all var(--transition-fast);
}
.chat-icon-btn:hover, .chat-icon-btn.active { background: var(--surface-hover); color: var(--foreground); }

/* ── Online bar ──────────────────────── */
.chat-online-bar { display: flex; flex-wrap: wrap; gap: 4px; padding: 8px 16px; border-bottom: 1px solid var(--surface-border); flex-shrink: 0; }
.member-picker-label { font-size: 12px; color: var(--muted-foreground); padding: 2px 4px; }
.online-user-chip { display: flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 500; color: var(--muted-foreground); background: var(--surface-hover); padding: 2px 8px; border-radius: 999px; }
.online-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--success); flex-shrink: 0;
  animation: online-beacon 2.4s var(--motion-ease-standard) infinite;
}

/* ── Messages ───────────────────────── */
.chat-messages { flex: 1; overflow-y: auto; padding: 8px 0; display: flex; flex-direction: column; }
.chat-new-messages {
  position: sticky;
  bottom: 10px;
  z-index: 3;
  align-self: center;
  margin: 8px auto 2px;
  padding: 7px 13px;
  border: 1px solid color-mix(in srgb, var(--primary) 35%, var(--surface-border));
  border-radius: 999px;
  background: color-mix(in srgb, var(--card) 94%, var(--primary));
  color: var(--primary);
  box-shadow: 0 5px 18px rgba(15, 23, 42, 0.14);
  cursor: pointer;
  font-size: 12px;
  transition: transform 0.18s ease, box-shadow 0.18s ease;
  animation: chat-new-message-in 320ms var(--motion-ease-spring) backwards;
}
.chat-new-messages:hover { transform: translateY(-1px); box-shadow: 0 7px 22px rgba(15, 23, 42, 0.2); }
.chat-status, .chat-load-more, .chat-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 20px; color: var(--muted-foreground); font-size: 12px; gap: 8px; }
.chat-empty { flex: 1; }
.chat-empty-icon { opacity: 0.3; margin-bottom: 4px; }
.chat-empty-title { font-size: 14px; font-weight: 600; color: var(--foreground); margin: 0; }
.chat-empty-hint { font-size: 12px; color: var(--muted-foreground); margin: 0; }
.load-more-hint { font-size: 11px; opacity: 0.6; }

/* ── Date separator ──────────────────── */
.chat-date-sep { display: flex; align-items: center; justify-content: center; padding: 12px 16px 8px; }
.chat-date-sep span { font-size: 11px; font-weight: 600; color: var(--muted-foreground); background: var(--surface); padding: 2px 12px; border-radius: 999px; border: 1px solid var(--surface-border); }

/* ── Message rows ───────────────────── */
.chat-msg { display: flex; align-items: flex-start; gap: 8px; padding: 2px 16px; animation: msgEnter 0.32s var(--motion-ease-enter) both; }
@keyframes msgEnter {
  from { opacity: 0; transform: translateY(10px) scale(0.97); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
.chat-msg.focused {
  background: var(--primary-light);
  animation: focused-message-pulse 1.2s ease-out 2;
}
.chat-msg.consecutive { padding-top: 1px; }
.chat-msg.mine { flex-direction: row-reverse; }
.chat-msg.system { justify-content: center; padding: 6px 16px; }
@keyframes focused-message-pulse {
  0%, 100% { box-shadow: inset 3px 0 0 transparent; }
  50% { box-shadow: inset 3px 0 0 var(--primary); }
}

.msg-avatar {
  width: 32px; height: 32px; border-radius: var(--radius-md);
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; color: #fff; flex-shrink: 0;
}
.msg-avatar-img {
  width: 32px; height: 32px; border-radius: var(--radius-md);
  object-fit: cover; flex-shrink: 0;
}
.msg-avatar-trigger {
  width: 32px; height: 32px; margin-top: 2px; padding: 0;
  border: none; border-radius: var(--radius-md); background: transparent;
  flex-shrink: 0; cursor: pointer;
  transition: transform var(--motion-fast) var(--motion-ease-standard), box-shadow var(--motion-fast) var(--motion-ease-standard);
}
.msg-avatar-trigger:hover {
  transform: translateY(-1px) scale(1.04);
  box-shadow: 0 0 0 2px var(--surface), 0 0 0 4px color-mix(in srgb, var(--primary) 45%, transparent);
}
.msg-avatar-trigger:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}
.msg-avatar-spacer { width: 32px; flex-shrink: 0; }
.msg-body { max-width: 75%; min-width: 0; }

.msg-meta { display: flex; align-items: baseline; gap: 8px; padding: 0 4px; margin-bottom: 2px; }
.chat-msg.mine .msg-meta { flex-direction: row-reverse; }
.msg-user { font-size: 12px; font-weight: 600; }
.msg-time { font-size: 10.5px; color: var(--muted-foreground); font-family: var(--font-mono); }

.msg-bubble {
  padding: 7px 12px; border-radius: var(--radius-md);
  font-size: 13px; line-height: 1.55; word-break: break-word;
  background: color-mix(in oklch, var(--glass-surface-strong) 84%, var(--surface-hover));
  color: var(--foreground);
  border: 1px solid color-mix(in oklch, var(--glass-border) 72%, transparent);
  transition:
    transform var(--motion-fast) var(--motion-ease-spring),
    box-shadow var(--transition-fast);
}
.chat-msg.mine .msg-bubble { background: var(--primary); color: var(--primary-foreground); }
.chat-msg:not(.system):hover .msg-bubble {
  transform: translate3d(0, -1px, 0);
  box-shadow: 0 5px 14px rgba(15, 23, 42, 0.09);
}
.msg-bubble :deep(p) { margin: 0 0 4px; }
.msg-bubble :deep(p:last-child) { margin-bottom: 0; }
.msg-bubble :deep(code) { background: rgba(0,0,0,0.1); padding: 1px 4px; border-radius: 3px; font-size: 11.5px; font-family: var(--font-mono); }
.msg-bubble :deep(pre) { background: rgba(0,0,0,0.08); padding: 6px 10px; border-radius: 4px; margin: 4px 0; font-size: 11.5px; overflow-x: auto; }
.msg-bubble :deep(pre code) { background: none; padding: 0; }
.msg-bubble :deep(blockquote) { border-left: 2px solid currentColor; margin: 4px 0; padding: 2px 8px; opacity: 0.7; }

.system-msg { font-size: 11.5px; color: var(--muted-foreground); font-style: italic; }

/* ── Attachments ─────────────────────── */
.msg-attachment { margin-top: 4px; }
.msg-attachment:first-child { margin-top: 0; }

.msg-image {
  max-width: 240px; max-height: 280px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: transform var(--transition-fast), box-shadow var(--transition-fast);
  object-fit: cover;
}
.msg-image.is-image-loading {
  width: 180px;
  height: 120px;
}
.msg-image:hover {
  transform: scale(1.02);
  box-shadow: 0 2px 12px rgba(0,0,0,0.15);
}

.msg-file-card {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px;
  background: var(--page-canvas);
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-md);
  text-decoration: none;
  transition: background var(--transition-fast);
  max-width: 260px;
}
.chat-msg.mine .msg-file-card { background: rgba(255,255,255,0.12); border-color: rgba(255,255,255,0.2); }
.msg-file-card:hover { background: var(--surface-hover); }
.chat-msg.mine .msg-file-card:hover { background: rgba(255,255,255,0.2); }

.msg-file-icon { font-size: 24px; flex-shrink: 0; }
.msg-file-info { display: flex; flex-direction: column; min-width: 0; flex: 1; }
.msg-file-name { font-size: 12.5px; font-weight: 600; color: var(--foreground); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chat-msg.mine .msg-file-name { color: var(--primary-foreground); }
.msg-file-size { font-size: 10.5px; color: var(--muted-foreground); }
.chat-msg.mine .msg-file-size { color: rgba(255,255,255,0.6); }
.msg-file-dl { flex-shrink: 0; color: var(--muted-foreground); }
.chat-msg.mine .msg-file-dl { color: rgba(255,255,255,0.7); }

/* ── Member profile card ──────────────── */
.member-profile-backdrop {
  position: fixed; inset: 0; z-index: 10000;
  display: flex; align-items: center; justify-content: center;
  padding: 20px;
  background: rgba(15, 23, 42, 0.46);
  -webkit-backdrop-filter: blur(var(--glass-blur-lg)) saturate(var(--glass-saturate));
  backdrop-filter: blur(var(--glass-blur-lg)) saturate(var(--glass-saturate));
}
.member-profile-card {
  position: relative;
  width: min(380px, calc(100vw - 32px));
  overflow: hidden;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-xl);
  background: var(--glass-surface-strong);
  color: var(--foreground);
  box-shadow: var(--shadow-floating), var(--glass-highlight);
  -webkit-backdrop-filter: blur(var(--glass-blur-lg)) saturate(var(--glass-saturate));
  backdrop-filter: blur(var(--glass-blur-lg)) saturate(var(--glass-saturate));
}
.member-profile-close {
  position: absolute; top: 12px; right: 12px; z-index: 1;
  width: 32px; height: 32px; padding: 0;
  display: flex; align-items: center; justify-content: center;
  border: none; border-radius: 50%;
  background: color-mix(in srgb, var(--surface) 76%, transparent);
  color: var(--muted-foreground); cursor: pointer;
}
.member-profile-close:hover { background: var(--surface-hover); color: var(--foreground); }
.member-profile-hero {
  display: flex; align-items: center; gap: 16px;
  padding: 28px 26px 22px;
  background:
    radial-gradient(circle at 12% 15%, color-mix(in srgb, var(--primary) 18%, transparent), transparent 42%),
    var(--surface-hover);
  border-bottom: 1px solid var(--surface-border);
}
.member-profile-avatar {
  width: 72px; height: 72px; flex-shrink: 0;
  border-radius: 20px; object-fit: cover;
  box-shadow: 0 5px 18px rgba(15, 23, 42, 0.16);
}
.member-profile-avatar-fallback {
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-size: 22px; font-weight: 750;
}
.member-profile-identity { min-width: 0; }
.member-profile-identity h3 {
  margin: 0; max-width: 210px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-size: 18px; line-height: 1.35;
}
.member-profile-identity p {
  margin: 3px 0 10px; color: var(--muted-foreground); font-size: 12px;
}
.member-profile-badges { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.member-role-badge,
.member-online-badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 7px; border-radius: 999px;
  background: var(--surface); border: 1px solid var(--surface-border);
  color: var(--muted-foreground); font-size: 10.5px; font-weight: 600;
}
.member-online-badge i {
  width: 6px; height: 6px; border-radius: 50%; background: var(--muted-foreground); opacity: 0.55;
}
.member-online-badge.online { color: var(--success); }
.member-online-badge.online i { background: var(--success); opacity: 1; }
.member-profile-content { min-height: 112px; padding: 20px 26px 16px; }
.member-profile-section-title {
  margin-bottom: 7px; color: var(--muted-foreground);
  font-size: 11px; font-weight: 700; letter-spacing: 0.04em;
}
.member-profile-bio {
  margin: 0; color: var(--foreground);
  font-size: 13px; line-height: 1.65; white-space: pre-wrap; word-break: break-word;
}
.member-profile-contact {
  display: flex; flex-direction: column; gap: 6px;
}
.contact-row {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; color: var(--muted-foreground);
}
.contact-row svg { flex-shrink: 0; opacity: 0.5; }
.member-profile-loading {
  display: flex; align-items: center; gap: 7px;
  margin-top: 12px; color: var(--muted-foreground); font-size: 11px;
}
.member-profile-error {
  margin: 12px 0 0; color: var(--danger); font-size: 11px;
}
.member-profile-actions {
  min-height: 62px; padding: 12px 26px 18px;
  display: flex; justify-content: flex-end; align-items: center;
}
.member-profile-self { color: var(--muted-foreground); font-size: 12px; }
.member-profile-dm {
  min-height: 36px; padding: 0 15px;
  display: inline-flex; align-items: center; justify-content: center; gap: 7px;
  border: none; border-radius: var(--radius-md);
  background: var(--primary); color: var(--primary-foreground);
  font-size: 12px; font-weight: 650; cursor: pointer;
  transition: transform var(--motion-fast) var(--motion-ease-standard), background var(--motion-fast) var(--motion-ease-standard);
}
.member-profile-dm:hover:not(:disabled) { background: var(--primary-hover); transform: translateY(-1px); }
.member-profile-dm:disabled { opacity: 0.45; cursor: not-allowed; }
.profile-card-fade-enter-active,
.profile-card-fade-leave-active { transition: opacity var(--motion-base) var(--motion-ease-standard); }
.profile-card-fade-enter-active .member-profile-card,
.profile-card-fade-leave-active .member-profile-card {
  transition:
    transform var(--motion-slow) var(--motion-ease-spring),
    opacity var(--motion-base) var(--motion-ease-standard);
}
.profile-card-fade-enter-from,
.profile-card-fade-leave-to { opacity: 0; }
.profile-card-fade-enter-from .member-profile-card,
.profile-card-fade-leave-to .member-profile-card {
  opacity: 0;
  transform: translate3d(0, 8px, 0) scale(0.975);
}

/* ── Lightbox ────────────────────────── */
.lightbox-backdrop {
  position: fixed; inset: 0; z-index: 9999;
  background: rgba(0,0,0,0.85);
  -webkit-backdrop-filter: blur(8px);
  backdrop-filter: blur(8px);
  display: flex; align-items: center; justify-content: center;
  cursor: zoom-out;
}
.lightbox-fade-enter-active,
.lightbox-fade-leave-active {
  transition: opacity var(--motion-base) var(--motion-ease-standard);
}
.lightbox-fade-enter-active .lightbox-img,
.lightbox-fade-enter-active .lightbox-close {
  transition:
    opacity var(--motion-slow) var(--motion-ease-enter),
    transform var(--motion-slow) var(--motion-ease-enter);
}
.lightbox-fade-leave-active .lightbox-img,
.lightbox-fade-leave-active .lightbox-close {
  transition:
    opacity var(--motion-fast) var(--motion-ease-exit),
    transform var(--motion-fast) var(--motion-ease-exit);
}
.lightbox-fade-enter-from,
.lightbox-fade-leave-to,
.lightbox-fade-enter-from .lightbox-img,
.lightbox-fade-leave-to .lightbox-img,
.lightbox-fade-enter-from .lightbox-close,
.lightbox-fade-leave-to .lightbox-close {
  opacity: 0;
}
.lightbox-fade-enter-from .lightbox-img,
.lightbox-fade-leave-to .lightbox-img {
  transform: scale(0.975);
}
.lightbox-img {
  max-width: 90vw; max-height: 90vh;
  border-radius: var(--radius-lg);
  object-fit: contain;
  cursor: default;
}
.lightbox-img.is-image-loading {
  width: min(70vw, 720px);
  height: min(60vh, 520px);
}
.lightbox-close {
  position: fixed; top: 16px; right: 16px;
  width: 44px; height: 44px; border-radius: var(--radius-md);
  border: none; background: rgba(255,255,255,0.12);
  color: #fff; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: background var(--transition-fast);
}
.lightbox-close:hover { background: rgba(255,255,255,0.2); }

/* ── Typing ──────────────────────────── */
.chat-typing {
  display: flex; align-items: center; gap: 8px;
  padding: 4px 20px 0; font-size: 11.5px;
  color: var(--muted-foreground); flex-shrink: 0; height: 22px;
}
.typing-dots { display: flex; gap: 3px; align-items: center; }
.typing-dots span {
  width: 5px; height: 5px; border-radius: 50%;
  background: var(--muted-foreground);
  animation: typingBounce 1.4s infinite both;
}
.typing-dots span:nth-child(2) { animation-delay: 0.2s; }
.typing-dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes typingBounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.3; }
  30% { transform: translateY(-4px); opacity: 1; }
}

/* ── Upload indicator ────────────────── */
.chat-uploading {
  display: flex; align-items: center; gap: 8px;
  padding: 4px 20px; font-size: 11.5px;
  color: var(--primary); flex-shrink: 0; height: 24px;
}

/* ── Input ──────────────────────────── */
.chat-input-area {
  position: relative;
  display: flex; align-items: flex-end; gap: 6px;
  padding: 10px 16px;
  border-top: 1px solid var(--surface-border);
  background: var(--glass-surface-soft);
  -webkit-backdrop-filter: blur(var(--glass-blur-sm));
  backdrop-filter: blur(var(--glass-blur-sm));
  flex-shrink: 0;
}
.chat-attach-btn {
  width: 38px; height: 38px;
  border-radius: var(--radius-md);
  border: 1px solid var(--surface-border);
  background: var(--glass-surface-soft);
  color: var(--muted-foreground);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  transition: all var(--transition-fast);
}
.chat-attach-btn:hover { background: var(--surface-hover); color: var(--foreground); border-color: var(--primary); }
.chat-attach-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.chat-input {
  flex: 1; resize: none;
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-md);
  padding: 8px 12px;
  font-size: 13px; font-family: var(--font-sans);
  background: var(--glass-surface-soft); color: var(--foreground);
  line-height: 1.45; outline: none;
  min-height: 38px; max-height: 120px;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}
.chat-input:focus {
  border-color: var(--primary);
  background: var(--glass-surface-strong);
  box-shadow: 0 0 0 3px var(--ring);
}
.chat-input::placeholder { color: var(--muted-foreground); }

.chat-send-btn {
  width: 38px; height: 38px; border-radius: var(--radius-md);
  border: none; background: var(--primary); color: var(--primary-foreground);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; transition: all var(--transition-fast);
}
.chat-send-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.chat-send-btn:not(:disabled):hover { background: var(--primary-hover); transform: scale(1.04); }
.chat-send-btn:not(:disabled):active { transform: scale(0.93); }
.chat-send-btn svg { transition: transform var(--motion-fast) var(--motion-ease-spring); }
.chat-send-btn:not(:disabled):hover svg { transform: translate3d(1px, -1px, 0); }

/* ── Mini spinner ───────────────────── */
.mini-spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--surface-border); border-top-color: var(--primary); border-radius: 50%; animation: spin 0.6s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* ── @mention / DM / mode toggle ────────────────────────────────────── */
.chat-mode-btn {
  margin-left: auto; width: 24px; height: 24px;
  border: none; background: transparent; color: var(--muted-foreground);
  cursor: pointer; border-radius: var(--radius-sm); display: flex; align-items: center; justify-content: center;
}
.chat-mode-btn:hover { background: var(--surface-hover); color: var(--foreground); }

.dm-chip {
  padding: 2px 8px; border-radius: 999px; font-size: 11px;
  border: 1px solid var(--surface-border); background: var(--surface);
  color: var(--muted-foreground); cursor: pointer;
  display: inline-flex; align-items: center; gap: 4px;
  transition:
    color var(--transition-fast),
    border-color var(--transition-fast),
    background-color var(--transition-fast),
    transform var(--motion-fast) var(--motion-ease-spring);
}
.dm-chip:hover, .dm-chip.active { border-color: var(--primary); color: var(--primary); transform: translateY(-1px); }
.dm-chip-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--muted-foreground); opacity: 0.4; }
.dm-chip-dot.online { background: var(--success); opacity: 1; }
.dm-chip-unread {
  min-width: 16px; height: 16px; padding: 0 4px;
  border-radius: 8px;
  background: var(--danger);
  color: #fff;
  font-size: 10px; font-weight: 700;
  line-height: 16px; text-align: center;
  animation: chipBadgePulse 2s ease-in-out infinite;
}
@keyframes chipBadgePulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.12); box-shadow: 0 0 6px var(--danger); }
}

.mention-tag {
  color: var(--primary); background: var(--primary-light);
  padding: 1px 3px; border-radius: 3px; font-weight: 600;
}

.mention-dropdown {
  position: absolute; bottom: calc(100% + 4px); left: 16px; right: 16px;
  max-height: 200px; overflow-y: auto;
  background: var(--glass-surface-strong); border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg); box-shadow: var(--shadow-menu), var(--glass-highlight);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  z-index: 20;
  transform-origin: center bottom;
  animation: mention-pop-in var(--motion-base) var(--motion-ease-enter) both;
}

@keyframes mention-pop-in {
  from { opacity: 0; transform: translate3d(0, 5px, 0) scale(0.98); }
  to { opacity: 1; transform: translate3d(0, 0, 0) scale(1); }
}
.mention-dropdown-header {
  position: sticky; top: 0; z-index: 1;
  display: flex; align-items: center; justify-content: space-between;
  padding: 7px 10px;
  border-bottom: 1px solid var(--surface-border);
  background: color-mix(in srgb, var(--surface) 94%, var(--primary));
  color: var(--muted-foreground);
  font-size: 10.5px;
}
.mention-item {
  display: flex; align-items: center; gap: 8px;
  width: 100%; padding: 8px 12px;
  border: none; background: transparent; color: var(--foreground);
  font-size: 13px; cursor: pointer; text-align: left;
  transition:
    background-color var(--transition-fast),
    transform var(--motion-fast) var(--motion-ease-spring);
}
.mention-item:hover, .mention-item.active { background: var(--surface-hover); transform: translate3d(2px, 0, 0); }
.mention-avatar {
  width: 26px; height: 26px; border-radius: 50%; flex-shrink: 0;
  display: inline-flex; align-items: center; justify-content: center;
  color: #fff; font-size: 9.5px; font-weight: 700;
}
.mention-member { min-width: 0; display: flex; flex-direction: column; align-items: flex-start; }
.mention-name { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
.mention-username { font-size: 11px; color: var(--muted-foreground); }
.mention-online-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--success); flex-shrink: 0; }
.mention-empty {
  padding: 18px 12px;
  color: var(--muted-foreground);
  font-size: 12px;
  text-align: center;
}

@keyframes chat-badge-in {
  from { opacity: 0; transform: translate3d(-4px, 0, 0) scale(0.9); }
  to { opacity: 1; transform: translate3d(0, 0, 0) scale(1); }
}
@keyframes online-beacon {
  0%, 100% { opacity: 0.72; transform: scale(0.92); }
  50% { opacity: 1; transform: scale(1.18); }
}
@keyframes chat-new-message-in {
  from { opacity: 0; transform: translate3d(0, 8px, 0) scale(0.96); }
  to { opacity: 1; transform: translate3d(0, 0, 0) scale(1); }
}
</style>
