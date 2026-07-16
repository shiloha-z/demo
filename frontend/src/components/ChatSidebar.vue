<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, computed, watch } from 'vue'
import { useWebSocketStore } from '../stores/websocket'
import { useAuthStore } from '../stores/auth'
import { useProjectStore } from '../stores/project'
import api from '../api'
import { renderMarkdown } from '../utils/markdown'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{
  'update:visible': [value: boolean]
  'unreadCount': [count: number]
}>()

const ws = useWebSocketStore()
const auth = useAuthStore()
const projectStore = useProjectStore()

interface ChatMsg {
  id: number
  user_id: number
  username: string
  message: string
  project_id?: number
  created_at: string
  system?: boolean
  file_url?: string
  file_name?: string
  file_type?: string
  file_size?: number
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
const fileInput = ref<HTMLInputElement>()
const uploading = ref(false)
const lightboxImage = ref<string | null>(null)

let unsubChat: (() => void) | null = null
let unsubOnline: (() => void) | null = null
let unsubOffline: (() => void) | null = null
let unsubTyping: (() => void) | null = null
let typingTimer: ReturnType<typeof setTimeout> | null = null

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
    const showMeta = msg.user_id !== lastUserId || msg.system
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

// ── Lifecycle ──────────────────────────────────────────────────
onMounted(async () => {
  setupWS()
  if (projectStore.currentProject) {
    joinProjectRoom(projectStore.currentProject.id)
  }
  document.addEventListener('paste', onGlobalPaste)
})

onUnmounted(() => {
  unsubChat?.()
  unsubOnline?.()
  unsubOffline?.()
  unsubTyping?.()
  document.removeEventListener('paste', onGlobalPaste)
})

// Watch for project changes — switch chat room when user selects a different project
watch(() => projectStore.currentProject?.id, (newId, oldId) => {
  if (newId && newId !== oldId) {
    joinProjectRoom(newId)
  } else if (!newId) {
    // No project selected — clear chat
    messages.value = []
    onlineUsers.value = []
  }
})

async function joinProjectRoom(projectId: number) {
  // Tell the server which project we're viewing
  try {
    ws.send(JSON.stringify({ type: 'join_project', project_id: projectId }))
  } catch { /* ignore */ }
  messages.value = []
  await loadMessages()
  await loadOnlineUsers()
}

function setupWS() {
  unsubChat = ws.on('chat_message', (data: ChatMsg & { system?: boolean }) => {
    // Only process messages for the current project
    const currentPid = projectStore.currentProject?.id
    if (currentPid == null || data.project_id !== currentPid) return
    // Dedup: message may already be in the list from optimistic send
    if (!messages.value.some(m => m.id === data.id)) {
      messages.value.push(data)
      if (!props.visible && data.user_id !== auth.userId) {
        emit('unreadCount', 1)
      }
      scrollToBottom()
    }
  })
  unsubOnline = ws.on('user_online', (data: { user_id: number; username: string; display_name: string; online_users: OnlineUser[] }) => {
    onlineUsers.value = data.online_users || []
  })
  unsubOffline = ws.on('user_offline', (data: { user_id: number; online_users: OnlineUser[] }) => {
    onlineUsers.value = data.online_users || []
    typingUsers.value.delete(data.user_id)
  })
  unsubTyping = ws.on('user_typing', (data: { user_id: number; username: string; display_name: string; project_id?: number; typing: boolean }) => {
    // Only process typing for the current project
    const currentPid = projectStore.currentProject?.id
    if (currentPid == null || data.project_id !== currentPid) return
    if (data.user_id === auth.userId) return
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
async function loadMessages(beforeId?: number) {
  const pid = projectStore.currentProject?.id
  if (pid == null) return
  loading.value = true
  try {
    const params: Record<string, any> = { project_id: pid, limit: 50 }
    if (beforeId) params.before_id = beforeId
    const { data } = await api.get('/chat/messages', { params })
    const arr: ChatMsg[] = Array.isArray(data) ? data : []
    if (beforeId && arr.length === 0) {
      hasMore.value = false
    } else if (!beforeId) {
      messages.value = arr
      hasMore.value = arr.length >= 50
      await nextTick()
      scrollToBottom()
    } else {
      messages.value = [...arr, ...messages.value]
      hasMore.value = arr.length >= 50
    }
  } catch { /* ignore */ }
  finally { loading.value = false }
}

async function loadOnlineUsers() {
  try {
    const pid = projectStore.currentProject?.id
    const params: Record<string, any> = {}
    if (pid != null) params.project_id = pid
    const { data } = await api.get('/chat/online', { params })
    onlineUsers.value = data.online_users || []
  } catch { /* ignore */ }
}

// ── Scroll ─────────────────────────────────────────────────────
function onScroll() {
  if (!scrollEl.value || loading.value || !hasMore.value) return
  if (scrollEl.value.scrollTop < 60) {
    const firstId = messages.value[0]?.id
    if (firstId) loadMessages(firstId)
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (scrollEl.value) {
      scrollEl.value.scrollTop = scrollEl.value.scrollHeight
    }
  })
}

// ── Send ───────────────────────────────────────────────────────
async function sendMessage() {
  const text = inputText.value.trim()
  if (!text && !pendingFiles.value.length) return
  if (sending.value) return

  sending.value = true
  try {
    // Upload pending files first
    for (const pf of pendingFiles.value) {
      await uploadAndSendFile(pf)
    }
    pendingFiles.value = []

    // Send text message
    if (text) {
      const pid = projectStore.currentProject?.id
      if (pid == null) return
      const form = new FormData()
      form.append('project_id', String(pid))
      form.append('message', text)
      const { data } = await api.post('/chat/messages', form)
      // Optimistically add message to local list so it appears immediately.
      // Dedup: the WebSocket broadcast will also deliver it, so skip duplicates.
      if (!messages.value.some(m => m.id === data.id)) {
        messages.value.push(data)
        scrollToBottom()
      }
      inputText.value = ''
      sendTyping(false)
    }
  } catch { /* ignore */ }
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

  for (const f of files) {
    await uploadAndSendFile(f)
  }
  input.value = ''
}

async function uploadAndSendFile(file: File) {
  uploading.value = true
  try {
    const pid = projectStore.currentProject?.id
    if (pid == null) return

    // Upload file
    const uploadForm = new FormData()
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
    await api.post('/chat/messages', msgForm)
    inputText.value = ''
  } catch { /* ignore */ }
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
    ws.send(JSON.stringify({ type: 'typing', typing: isTyping }))
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
  if (v) nextTick(() => scrollToBottom())
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
        <span>团队聊天</span>
        <template v-if="projectStore.currentProject">
          <span class="chat-header-sep">·</span>
          <span class="chat-header-project">{{ projectStore.currentProject.name }}</span>
        </template>
        <span class="chat-badge" v-if="onlineUsers.length > 0">{{ onlineUsers.length }} 在线</span>
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

    <!-- ── Online users ──────────────────── -->
    <div class="chat-online-bar" v-if="showOnlineUsers && onlineUsers.length > 0">
      <div v-for="u in onlineUsers" :key="u.user_id" class="online-user-chip" :title="u.display_name || u.username">
        <span class="online-dot" />
        {{ u.display_name || u.username }}
      </div>
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
          class="chat-msg"
          :class="{
            mine: msg.user_id === auth.userId && !msg.system,
            system: msg.system,
            consecutive: !msg.showMeta,
          }"
        >
          <!-- System message -->
          <template v-if="msg.system">
            <div class="system-msg">{{ msg.message }}</div>
          </template>

          <!-- Normal message -->
          <template v-else>
            <div class="msg-avatar" v-if="msg.showAvatar" :style="{ background: avatarColor(msg.username) }">
              {{ avatarInitials(msg.username) }}
            </div>
            <div class="msg-avatar-spacer" v-else />
            <div class="msg-body">
              <div class="msg-meta" v-if="msg.showMeta">
                <span class="msg-user" :style="{ color: avatarColor(msg.username) }">{{ msg.username }}</span>
                <span class="msg-time">{{ formatTime(msg.created_at) }}</span>
              </div>

              <!-- Text content -->
              <div class="msg-bubble" v-if="msg.message" v-html="renderMsg(msg.message)" />

              <!-- Image attachment -->
              <div class="msg-attachment" v-if="msg.file_type === 'image' && msg.file_url">
                <img
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
                    <span class="msg-file-size">{{ formatSize(msg.file_size) }}</span>
                  </div>
                  <svg class="msg-file-dl" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                </a>
              </div>
            </div>
          </template>
        </div>
      </template>
    </div>

    <!-- ── Typing indicator ──────────────── -->
    <div class="chat-typing" v-if="typingText">
      <span class="typing-dots"><span></span><span></span><span></span></span>
      {{ typingText }}
    </div>

    <!-- ── Upload indicator ──────────────── -->
    <div class="chat-uploading" v-if="uploading">
      <span class="mini-spinner"></span> 上传文件中...
    </div>

    <!-- ── Input ──────────────────────────── -->
    <div class="chat-input-area">
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
        v-model="inputText"
        class="chat-input"
        :placeholder="projectStore.currentProject ? '输入消息，Enter 发送，Shift+Enter 换行...' : '请先在左侧边栏选择一个项目'"
        rows="2"
        maxlength="2000"
        :disabled="!projectStore.currentProject"
        @keydown="handleKeydown"
        @input="onInput"
      />
      <button
        class="chat-send-btn"
        :disabled="(!inputText.trim() && pendingFiles.length === 0) || sending || !projectStore.currentProject"
        @click="sendMessage"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
      </button>
    </div>

    <!-- ── Lightbox ──────────────────────── -->
    <Teleport to="body">
      <div class="lightbox-backdrop" v-if="lightboxImage" @click="closeLightbox">
        <img :src="lightboxImage" class="lightbox-img" @click.stop />
        <button class="lightbox-close" @click="closeLightbox" title="关闭">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
    </Teleport>
  </aside>
</template>

<style scoped>
.chat-panel {
  width: 360px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border-left: 1px solid var(--surface-border);
  transition: width var(--transition-base), opacity var(--transition-base);
  overflow: hidden;
  position: relative;
}
.chat-panel:not(.open) {
  width: 0;
  border-left: none;
  opacity: 0;
}

/* ── Header ─────────────────────────── */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--surface-border);
  flex-shrink: 0;
}
.chat-header-left { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 700; color: var(--foreground); }
.chat-header-sep { font-weight: 400; color: var(--muted-foreground); font-size: 12px; }
.chat-header-project { font-size: 12px; color: var(--primary); max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chat-badge { font-size: 10.5px; font-weight: 600; color: var(--success); background: var(--success-light); padding: 1px 7px; border-radius: 999px; }
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
.online-user-chip { display: flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 500; color: var(--muted-foreground); background: var(--surface-hover); padding: 2px 8px; border-radius: 999px; }
.online-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--success); flex-shrink: 0; }

/* ── Messages ───────────────────────── */
.chat-messages { flex: 1; overflow-y: auto; padding: 8px 0; display: flex; flex-direction: column; }
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
.chat-msg { display: flex; align-items: flex-start; gap: 8px; padding: 2px 16px; }
.chat-msg.consecutive { padding-top: 1px; }
.chat-msg.mine { flex-direction: row-reverse; }
.chat-msg.system { justify-content: center; padding: 6px 16px; }

.msg-avatar {
  width: 32px; height: 32px; border-radius: var(--radius-md);
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; color: #fff; flex-shrink: 0; margin-top: 2px;
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
  background: var(--surface-hover); color: var(--foreground);
}
.chat-msg.mine .msg-bubble { background: var(--primary); color: var(--primary-foreground); }
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

/* ── Lightbox ────────────────────────── */
.lightbox-backdrop {
  position: fixed; inset: 0; z-index: 9999;
  background: rgba(0,0,0,0.85);
  display: flex; align-items: center; justify-content: center;
  cursor: zoom-out;
}
.lightbox-img {
  max-width: 90vw; max-height: 90vh;
  border-radius: var(--radius-lg);
  object-fit: contain;
  cursor: default;
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
  display: flex; align-items: flex-end; gap: 6px;
  padding: 10px 16px;
  border-top: 1px solid var(--surface-border);
  flex-shrink: 0;
}
.chat-attach-btn {
  width: 38px; height: 38px;
  border-radius: var(--radius-md);
  border: 1px solid var(--surface-border);
  background: var(--page-canvas);
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
  background: var(--page-canvas); color: var(--foreground);
  line-height: 1.45; outline: none;
  min-height: 38px; max-height: 120px;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}
.chat-input:focus { border-color: var(--primary); box-shadow: 0 0 0 2px oklch(0.55 0.2 260 / 0.12); }
.chat-input::placeholder { color: var(--muted-foreground); }

.chat-send-btn {
  width: 38px; height: 38px; border-radius: var(--radius-md);
  border: none; background: var(--primary); color: var(--primary-foreground);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; transition: all var(--transition-fast);
}
.chat-send-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.chat-send-btn:not(:disabled):hover { background: var(--primary-hover); transform: scale(1.04); }

/* ── Mini spinner ───────────────────── */
.mini-spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--surface-border); border-top-color: var(--primary); border-radius: 50%; animation: spin 0.6s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
