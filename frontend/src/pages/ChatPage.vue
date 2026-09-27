<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChatStore } from '../stores/chat'
import type { RuntimeEvent, ToolProcess } from '../api/chat'
import AgentPicker from '../components/AgentPicker.vue'
import ContextToolbar from '../components/ContextToolbar.vue'
import ChatToolCard from '../components/ChatToolCard.vue'
import ChatCapabilities from '../components/ChatCapabilities.vue'
import MarkdownMessage from '../components/MarkdownMessage.vue'
import AppIcon from '../components/AppIcon.vue'
import ReplyActions from '../components/ReplyActions.vue'
import LoadingIndicator from '../components/LoadingIndicator.vue'
import PopoverTransition from '../components/PopoverTransition.vue'
import { MAX_DRAFT_LENGTH } from '../utils/textImport'
import { importAttachment, MAX_ATTACHMENTS_BYTES } from '../utils/attachmentImport'
import type { AttachmentInput } from '../api/chat'

const chat = useChatStore()
const route = useRoute()
const router = useRouter()
const composing = ref(false)
const transcript = ref<HTMLElement>()
const chatInput = ref<HTMLTextAreaElement>()
const plusButton = ref<HTMLButtonElement>()
const folderDialog = ref<HTMLDialogElement>()
const capabilities = ref<InstanceType<typeof ChatCapabilities>>()
const follow = ref(true)
const fileDragging = ref(false)
const composerMenu = ref(false)
const textFile = ref<HTMLInputElement>()
const importing = ref(false)
const importError = ref('')
const attachments = ref<Attachment[]>([])
const starters = [
  { label: '梳理一个想法', icon: 'chat' as const, prompt: '我有一个想法，想和你一起梳理。请先问我目标和现状，再帮我拆成具体步骤。' },
  { label: '打磨一段文字', icon: 'write' as const, prompt: '帮我打磨下面这段文字，保留原意，让表达更清晰、简洁：\n\n' },
  { label: '理解一个概念', icon: 'skill' as const, prompt: '我想理解一个概念。请用简单的语言和具体例子解释，并用一个问题检查我是否理解：\n\n' },
]
const empty = computed(() => !chat.current?.messages.length && !chat.loading && !chat.generating && !(chat.toolProcesses[chat.selected]?.length))
const readyAgents = computed(() => chat.agents.filter(agent => agent.is_ready !== false))
const currentAgent = computed(() => chat.agents.find(agent => agent.id === chat.current?.agent_id))
const chosen = computed(() => !!currentAgent.value && currentAgent.value.is_ready !== false)
const agentAvailability = computed(() => currentAgent.value?.unavailable_reason || '原 Agent 已删除或不可用，请选择可用 Agent 后继续。')
const recoveryLink = computed(() => agentAvailability.value.includes('提示词') && chat.current?.agent_id ? `/agents/${chat.current.agent_id}/edit` : '/models')
const recoveryLabel = computed(() => agentAvailability.value.includes('提示词') ? '编辑 Agent' : '检查模型')
const draft = computed({ get: () => chat.drafts[chat.selected] || '', set: value => { chat.drafts[chat.selected] = value } })
const canAttach = computed(() => !!chat.current && chosen.value && !chat.generating && !chat.busy[chat.selected] && !chat.loading && !importing.value)
const canOpenComposerMenu = computed(() => !!chat.current && !chat.generating && !chat.busy[chat.selected] && !chat.loading)
const messageContent = computed(() => draft.value)
const readyAttachments = computed(() => attachments.value.filter(item => item.status === 'ready' && item.payload))
const canSend = computed(() => !!chat.current && chosen.value && (!!messageContent.value.trim() || !!readyAttachments.value.length) && !chat.generating && !chat.busy[chat.selected] && !chat.loading && !importing.value)
type TimelinePart = { type: 'text'; id: string; content: string } | { type: 'tool'; id: string; process: ToolProcess }
type Attachment = { id: string; name: string; size: number; status: 'ready' | 'failed'; payload?: AttachmentInput; preview?: string; error?: string }
const date = (value: string) => new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
let importRevision = 0
let attachmentIndex = 0
let fileDragDepth = 0

async function reload() {
  await chat.load(typeof route.query.session === 'string' ? route.query.session : undefined)
  if (!chat.current && readyAgents.value.length && !chat.error) await chat.create()
}
async function startWith(prompt: string) {
  if (!readyAgents.value.length || chat.generating || chat.loading || chat.creating || importing.value) return
  if (!chat.current) await chat.create()
  if (!chat.current || !chosen.value || chat.busy[chat.selected]) return
  const next = draft.value ? `${draft.value}\n\n${prompt}` : prompt
  if (next.length > MAX_DRAFT_LENGTH) { importError.value = '消息过长，请先精简输入。'; return }
  draft.value = next
  await nextTick()
  document.getElementById('chat-input')?.focus()
}
function attachmentId() { attachmentIndex += 1; return `attachment-${attachmentIndex}` }
function fileSize(size: number) { return size < 1024 ? `${size} B` : `${(size / 1024).toFixed(size < 10 * 1024 ? 1 : 0)} KiB` }
function removeAttachment(id: string) {
  attachments.value = attachments.value.filter(item => item.id !== id)
  importError.value = ''
}
function resetAttachments() {
  attachments.value = []
  importError.value = ''
}
function resizeInput() {
  const input = chatInput.value
  if (!input) return
  input.style.height = 'auto'
  input.style.height = `${Math.min(Math.max(input.scrollHeight, 32), 200)}px`
  input.style.overflowY = input.scrollHeight > 200 ? 'auto' : 'hidden'
}
async function addFiles(files: File[]) {
  if (!files.length || !canAttach.value) return
  const sessionId = chat.selected
  const revision = ++importRevision
  importing.value = true
  importError.value = ''
  try {
    for (const file of files) {
      const item: Attachment = { id: attachmentId(), name: file.name, size: file.size, status: 'ready' }
      try {
        if (attachments.value.filter(item => item.status === 'ready').length >= 4) throw new Error('每次最多添加 4 个附件。')
        if (attachments.value.filter(item => item.status === 'ready').reduce((sum, item) => sum + item.size, 0) + file.size > MAX_ATTACHMENTS_BYTES) throw new Error('附件合计最多 10 MiB，请分开发送。')
        const payload = await importAttachment(file)
        if (revision !== importRevision || sessionId !== chat.selected || !chat.current || chat.generating) return
        item.payload = payload
        if (payload.mime_type.startsWith('image/')) item.preview = `data:${payload.mime_type};base64,${payload.data}`
      } catch (cause) {
        item.status = 'failed'
        item.error = cause instanceof Error ? cause.message : '文件读取失败，请重试。'
        delete item.payload
      }
      if (revision !== importRevision || sessionId !== chat.selected) return
      attachments.value = [...attachments.value, item]
    }
    await nextTick()
    chatInput.value?.focus()
  } finally {
    if (revision === importRevision) importing.value = false
  }
}
async function addText(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  await addFiles(files)
}
function toggleComposerMenu() {
  if (composerMenu.value) { closeComposerMenu(true); return }
  composerMenu.value = true
  void nextTick(() => document.querySelector<HTMLButtonElement>('.composer-menu [role="menuitem"]:not(:disabled)')?.focus())
}
function closeComposerMenu(returnFocus = false) {
  if (!composerMenu.value) return
  composerMenu.value = false
  if (returnFocus) void nextTick(() => plusButton.value?.focus())
}
function composerMenuKey(event: KeyboardEvent) {
  if (event.key === 'Escape' || event.key === 'Tab') {
    if (event.key === 'Escape') event.preventDefault()
    closeComposerMenu(event.key === 'Escape')
    return
  }
  const buttons = Array.from((event.currentTarget as HTMLElement).querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)'))
  const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
  const next = { ArrowDown: (index + 1) % buttons.length, ArrowUp: (index + buttons.length - 1) % buttons.length, Home: 0, End: buttons.length - 1 }[event.key]
  if (next !== undefined) { event.preventDefault(); buttons[next]?.focus() }
}
function pickFiles() {
  closeComposerMenu()
  textFile.value?.click()
}
function goTo(path: string) {
  closeComposerMenu()
  void router.push(path)
}
function openCapabilities() {
  closeComposerMenu()
  void nextTick(() => capabilities.value?.open())
}
function openFolder() {
  closeComposerMenu()
  folderDialog.value?.showModal()
}
function closeFolder() {
  folderDialog.value?.close()
  plusButton.value?.focus()
}
async function selectAgent(id: string) {
  const cid = chat.selected
  await chat.changeAgent(id)
  await nextTick()
  if (chat.selected === cid && document.activeElement === document.body) document.getElementById('chat-agent')?.focus()
}
function clearComposer() {
  draft.value = ''
  resetAttachments()
  closeComposerMenu()
  void nextTick(() => { resizeInput(); chatInput.value?.focus() })
}
function dragEnter(event: DragEvent) {
  if (!event.dataTransfer?.types.includes('Files') || !canAttach.value) return
  fileDragDepth += 1
  fileDragging.value = true
}
function dragOver(event: DragEvent) {
  if (!event.dataTransfer?.types.includes('Files') || !canAttach.value) return
  event.preventDefault()
  event.dataTransfer.dropEffect = 'copy'
}
function dragLeave(event: DragEvent) {
  if (!event.dataTransfer?.types.includes('Files')) return
  fileDragDepth = Math.max(0, fileDragDepth - 1)
  if (!fileDragDepth) fileDragging.value = false
}
function dropFiles(event: DragEvent) {
  event.preventDefault()
  fileDragDepth = 0
  fileDragging.value = false
  void addFiles(Array.from(event.dataTransfer?.files || []))
}
function cancelFileDrag(event: KeyboardEvent) {
  if (event.key === 'Escape' && fileDragging.value) {
    fileDragDepth = 0
    fileDragging.value = false
  }
}
async function open(id: string) { follow.value = true; await chat.select(id) }
function outside(event: PointerEvent) {
  if (!(event.target as Element)?.closest('.composer-menu, .composer-plus')) closeComposerMenu()
}
function hideMenu() { closeComposerMenu() }
function enter(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || composing.value || event.keyCode === 229) return
  event.preventDefault()
  if (canSend.value) void send()
}
async function send() {
  if (!canSend.value) return
  follow.value = true
  const content = messageContent.value
  const sessionId = chat.selected
  const submitted = [...readyAttachments.value]
  const sent = await chat.send(content, submitted.map(item => item.payload!))
  if (!sent) return
  if (chat.selected !== sessionId) return
  if (draft.value === content) draft.value = ''
  attachments.value = attachments.value.filter(item => !submitted.includes(item))
  await nextTick()
  resizeInput()
}
function latestReply(id: string) {
  return chat.current?.generation?.message?.id === id
}
async function regenerate() {
  follow.value = true
  await chat.regenerate()
}
function scrolling() {
  const box = transcript.value
  if (box) follow.value = box.scrollHeight - box.scrollTop - box.clientHeight < 80
}
function timeline(content: string, processes: ToolProcess[]): TimelinePart[] {
  if (!processes.length) return content ? [{ type: 'text', id: 'text-0', content }] : []
  let offset = 0
  const parts: TimelinePart[] = []
  for (const process of [...processes].sort((a, b) => a.sequence - b.sequence)) {
    const boundary = Math.max(offset, Math.min(process.text_offset, content.length))
    if (boundary > offset) parts.push({ type: 'text', id: `text-${offset}`, content: content.slice(offset, boundary) })
    parts.push({ type: 'tool', id: process.id, process })
    offset = boundary
  }
  if (offset < content.length) parts.push({ type: 'text', id: `text-${offset}`, content: content.slice(offset) })
  return parts
}
function messageTimeline(id: string, content: string) {
  return timeline(content, (chat.toolProcesses[chat.selected] || []).filter(process => process.assistant_message_id === id))
}
const pendingTimeline = computed(() => {
  const generation = chat.current?.generation
  if (!generation || generation.message) return []
  return timeline('', (chat.toolProcesses[chat.selected] || []).filter(process => process.generation_id === generation.id))
})
const contextEvents = computed(() => (chat.runtimeEvents[chat.selected] || []).filter(event => ['compression_start', 'compression_success', 'compression_failure', 'context_fallback'].includes(event.type)))
const contextEventTitle = (event: RuntimeEvent) => ({ compression_start: '开始压缩', compression_success: '压缩成功', compression_failure: '压缩失败', context_fallback: '备用处理' }[event.type] || '容量处理')
const progressEvents = computed(() => (chat.runtimeEvents[chat.selected] || [])
  .filter(event => ['run_start', 'model_start', 'tool_start', 'tool_result', 'run_error', 'run_end'].includes(event.type))
  .slice(-4))
function progressTitle(event: RuntimeEvent) {
  if (event.type === 'run_start') return '已接收任务'
  if (event.type === 'model_start') return `正在处理第 ${event.round ?? 1} 轮`
  if (event.type === 'tool_start') return `正在使用 ${event.data.display_name || '工具'}`
  if (event.type === 'tool_result') return event.data.status === 'completed' ? `${event.data.display_name || '工具'}已完成` : `${event.data.display_name || '工具'}未完成`
  if (event.type === 'run_error') return '任务未完成'
  if (event.type === 'run_end') return event.data.status === 'completed' ? '已完成任务' : '已结束任务'
  return '正在处理'
}
const estimateLabel = (value: number | null | undefined) => typeof value === 'number' ? `约 ${value.toLocaleString()} Token` : '—'
function latest() { follow.value = true; if (transcript.value) transcript.value.scrollTop = transcript.value.scrollHeight }
function preserveReadingPosition(event: MouseEvent) {
  const card = (event.target as Element)?.closest('.tool-process') as HTMLElement | null
  const box = transcript.value
  if (!card || !box || follow.value) return
  const before = card.getBoundingClientRect().top
  void nextTick(() => { if (transcript.value) transcript.value.scrollTop += card.getBoundingClientRect().top - before })
}
watch(() => chat.selected, id => {
  importRevision++; importing.value = false
  resetAttachments()
  closeComposerMenu()
  if (route.query.session !== (id || undefined)) void router.replace({ path: '/chat', query: id ? { session: id } : {} })
})
watch(() => chat.composerReset, () => { importRevision++; importing.value = false; resetAttachments(); closeComposerMenu() })
watch(draft, () => { void nextTick(resizeInput) })
watch(() => route.query.session, id => { if (typeof id === 'string' && id !== chat.selected) void open(id) })
watch(() => [chat.current?.messages.length, chat.current?.generation?.message?.content, chat.toolProcesses[chat.selected]?.map(item => `${item.id}:${item.status}:${item.summary}`).join('|'), chat.loading], async () => {
  await nextTick()
  if (follow.value && transcript.value) transcript.value.scrollTop = transcript.value.scrollHeight
})
onMounted(() => {
  void reload()
  document.addEventListener('pointerdown', outside)
  document.addEventListener('keydown', cancelFileDrag)
  window.addEventListener('scroll', hideMenu, true)
  void nextTick(resizeInput)
})
onUnmounted(() => {
  importRevision++
  chat.leave()
  document.removeEventListener('pointerdown', outside)
  document.removeEventListener('keydown', cancelFileDrag)
  window.removeEventListener('scroll', hideMenu, true)
})
</script>

<template>
  <div class="chat-page desktop-workbench" @dragenter="dragEnter" @dragover="dragOver" @dragleave="dragLeave" @drop="dropFiles">
    <h1 id="page-title" class="visually-hidden" tabindex="-1">聊天</h1>
    <div v-if="fileDragging" class="file-drop-overlay" aria-live="polite"><div><AppIcon name="attach" /><strong>松开即可添加文件</strong><span>支持图片、PDF 和文本，单个文件最大 5 MiB</span></div></div>
    <div v-if="chat.error" class="model-feedback" role="alert"><p>{{ chat.error }}</p><button class="button button-ghost" :disabled="chat.loading" @click="reload">重新加载</button></div>
    <header class="workbench-toolbar"><div><AppIcon name="chat" /><span>{{ chat.current?.title || '新建会话' }}</span></div></header>
    <div class="chat-layout unified-chat-layout">
      <section class="chat-workspace" aria-label="聊天区域">
        <div class="chat-body" :class="{ 'is-empty': empty }">
          <div v-if="!readyAgents.length && !chat.loading && !chat.error" class="chat-setup"><span>还没有可用 Agent。</span><RouterLink to="/agents">前往配置 →</RouterLink></div>
          <section v-else-if="chat.current && !chosen && !chat.loading" class="chat-recovery" role="status"><div><strong>当前 Agent 暂不能开始对话</strong><p>{{ agentAvailability }}</p></div><div class="chat-recovery-actions"><RouterLink :to="recoveryLink" class="button button-primary">{{ recoveryLabel }}</RouterLink><RouterLink to="/agents" class="button button-ghost">查看 Agent</RouterLink></div></section>
          <div v-if="!empty" ref="transcript" class="chat-transcript" tabindex="0" aria-label="聊天记录" :aria-busy="chat.loading" @scroll="scrolling" @click.capture="preserveReadingPosition">
            <p v-if="chat.loading" class="muted loading-status" role="status"><LoadingIndicator />正在加载会话…</p>
            <template v-if="chat.current && !chat.loading">
              <article v-for="message in chat.current.messages" :key="message.id" class="chat-message" :class="message.role" :aria-label="message.role === 'user' ? '你' : message.agent_name || 'Agent'">
                <div class="chat-message-meta"><span>{{ message.role === 'user' ? '你' : message.agent_name }}</span><time :datetime="message.created_at">{{ date(message.created_at) }}</time></div>
                <template v-if="message.role === 'assistant'">
                  <template v-for="part in messageTimeline(message.id, message.content)" :key="part.id">
                    <MarkdownMessage v-if="part.type === 'text'" class="chat-message-body" :content="part.content" />
                    <ChatToolCard v-else :process="part.process" />
                  </template>
                </template>
                <template v-else>
                  <div class="chat-message-body">{{ message.content }}</div>
                  <div v-if="message.attachments?.length" class="message-attachments" aria-label="消息附件">
                    <a v-for="item in message.attachments" :key="item.id" :href="`/api/chat/attachments/${encodeURIComponent(item.id)}`" :download="item.name" target="_blank" rel="noopener noreferrer">
                      <img v-if="item.mime_type.startsWith('image/')" :src="`/api/chat/attachments/${encodeURIComponent(item.id)}`" :alt="item.name" loading="lazy" />
                      <span><AppIcon name="attach" />{{ item.name }}<small>{{ fileSize(item.size) }}</small></span>
                    </a>
                  </div>
                </template>
                <span v-if="message.status === 'failed' || message.status === 'cancelled'" class="chat-incomplete">{{ message.status === 'cancelled' ? '已停止 · 未完成' : '未完成' }}</span>
                <ReplyActions v-if="message.role === 'assistant' && message.status !== 'generating'" :message="message" :can-regenerate="latestReply(message.id) && !chat.generating && !chat.busy[chat.selected] && chosen" @regenerate="regenerate" @feedback="message.feedback_rating = $event" />
              </article>
              <article v-if="pendingTimeline.length" class="chat-message assistant" :aria-label="chat.current.generation?.message?.agent_name || 'Agent'">
                <div class="chat-message-meta"><span>{{ chat.current.generation?.message?.agent_name || 'Agent' }}</span></div>
                <template v-for="part in pendingTimeline" :key="part.id"><ChatToolCard v-if="part.type === 'tool'" :process="part.process" /></template>
              </article>
              <details v-if="chat.generating && progressEvents.length" class="chat-execution-details"><summary>执行过程 · {{ progressTitle(progressEvents[progressEvents.length - 1]!) }}</summary>
              <ol class="chat-progress" aria-label="当前任务进度">
                <li v-for="event in progressEvents" :key="`${event.run_id}:${event.sequence}`" :class="{ 'is-active': event.type === 'model_start' || event.type === 'tool_start' }"><span aria-hidden="true" /><div><strong>{{ progressTitle(event) }}</strong><small v-if="event.data.summary || event.data.reason">{{ event.data.summary || event.data.reason }}</small></div></li>
              </ol></details>
              <details v-if="contextEvents.length" class="chat-context-details">
                <summary>上下文容量处理 · {{ contextEvents.length }} 条</summary>
                <div v-for="event in contextEvents" :key="`${event.run_id}:${event.sequence}`" class="chat-context-event">
                  <strong>{{ contextEventTitle(event) }}</strong>
                  <span>估算 {{ estimateLabel(event.data.estimated_tokens_before) }} → {{ estimateLabel(event.data.estimated_tokens_after) }}</span>
                  <span>处理 {{ event.data.processed_message_count ?? 0 }} 条消息 · 实际保留 {{ event.data.retained_message_count ?? 0 }} 条</span>
                  <span v-if="typeof event.data.duration_ms === 'number'">耗时 {{ event.data.duration_ms }} ms</span>
                </div>
                <p>以上为估算与安全统计，不包含历史正文或摘要内容。模型返回的实际 Token 用量单独记录。</p>
              </details>
            </template>
          </div>
          <button v-if="!follow && !empty" type="button" class="chat-latest" @click="latest">回到最新消息 ↓</button>
          <div v-if="chat.generating" class="chat-generation-state loading-status" role="status" aria-live="polite"><LoadingIndicator />{{ chat.current?.generation?.message?.content ? '正在生成' : '正在思考' }}</div>
          <div v-if="chat.errors[chat.selected]" class="chat-error" role="alert"><p>{{ chat.errors[chat.selected] }}</p><button class="button button-plain" :disabled="chat.loading" @click="reload">重新加载</button></div>
          <div v-if="chat.current?.generation?.error" class="chat-error" role="alert"><p>{{ chat.current.generation.error }}</p><button v-if="!chat.current.generation.message" type="button" class="button button-plain" :disabled="chat.generating || chat.busy[chat.selected] || !chosen" title="重新生成，不执行本地或 MCP 工具" @click="regenerate">重试回复</button></div>
          <div v-if="empty" class="chat-welcome">
            <p class="chat-greeting">我们要做些什么？</p>
          </div>
          <input ref="textFile" type="file" accept=".txt,.md,.csv,.json,.pdf,.png,.jpg,.jpeg,.webp,.gif" multiple hidden @change="addText" />
          <div class="chat-composer-shell">
          <form class="chat-composer" @submit.prevent="send">
            <label class="chat-input-label" for="chat-input">消息</label>
            <div v-if="attachments.length" class="composer-attachments" aria-label="待发送文件">
              <div v-for="item in attachments" :key="item.id" class="attachment-chip" :class="`is-${item.status}`">
                <img v-if="item.preview" class="attachment-thumbnail" :src="item.preview" alt="" /><AppIcon v-else name="attach" /><span class="attachment-chip-copy"><strong>{{ item.name }}</strong><small>{{ item.status === 'ready' ? fileSize(item.size) : item.error }}</small></span><button type="button" :aria-label="`移除文件：${item.name}`" @click="removeAttachment(item.id)"><AppIcon name="close" /></button>
              </div>
            </div>
            <textarea ref="chatInput" id="chat-input" v-model="draft" rows="1" maxlength="100000" placeholder="描述你想完成的任务，或添加本地文件…" :disabled="!chat.current || !chosen || chat.generating || chat.busy[chat.selected] || chat.loading" @input="resizeInput" @keydown="enter" @compositionstart="composing = true" @compositionend="composing = false" />
            <div class="chat-composer-actions">
              <div class="composer-menu-wrap">
                <button ref="plusButton" type="button" class="composer-plus" :disabled="!canOpenComposerMenu" aria-label="添加内容" :aria-expanded="composerMenu" aria-haspopup="menu" @click="toggleComposerMenu"><AppIcon name="add" /></button>
                <PopoverTransition>
                <div v-if="composerMenu" class="composer-menu" role="menu" aria-label="添加内容" @keydown="composerMenuKey">
                  <p>添加内容</p>
                  <button role="menuitem" type="button" :disabled="!canAttach" @click="pickFiles"><AppIcon name="attach" />{{ importing ? '正在读取文件…' : '从电脑添加文件' }}</button>
                  <button role="menuitem" type="button" @click="openFolder"><AppIcon name="folder" />工作目录</button>
                  <p>扩展能力</p>
                  <button role="menuitem" type="button" @click="goTo('/skills')"><AppIcon name="skill" />任务技能</button>
                  <button role="menuitem" type="button" @click="goTo('/mcp/new')"><AppIcon name="mcp" />连接外部工具</button>
                  <button role="menuitem" type="button" :disabled="!chosen" @click="openCapabilities"><AppIcon name="tool" />查看当前能力</button>
                </div>
                </PopoverTransition>
              </div>
              <AgentPicker :agents="chat.agents" :model-value="chosen ? chat.current?.agent_id : null" :disabled="!chat.current || chat.generating || !!chat.busy[chat.selected] || chat.loading" @update:model-value="selectAgent" />
              <button v-if="draft || attachments.length" type="button" class="composer-clear" aria-label="清空输入" title="清空输入" :disabled="chat.generating || !!chat.busy[chat.selected]" @click="clearComposer"><AppIcon name="close" /></button>

              <button v-if="chat.generating" type="button" class="button button-primary chat-send chat-stop" :disabled="chat.busy[chat.selected]" aria-label="停止生成" title="停止生成" @click="chat.stop"><span class="visually-hidden">停止生成</span><span class="stop-square" aria-hidden="true" /></button>
              <button v-else class="button button-primary chat-send" :disabled="!canSend" :aria-label="chat.busy[chat.selected] ? '正在保存…' : '发送'" :title="chat.busy[chat.selected] ? '正在保存…' : '发送'"><span class="visually-hidden">{{ chat.busy[chat.selected] ? '正在保存…' : '发送' }}</span><AppIcon name="send" /></button>
            </div>
          </form>
          </div>
          <p v-if="chat.current?.archive_error" class="chat-error" role="alert">{{ chat.current.archive_error }} <button class="button button-plain" @click="openFolder">查看并重试</button></p>
          <p v-if="importError" class="composer-notice chat-error" role="alert">{{ importError }}</p>
          <ChatCapabilities ref="capabilities" :agent-id="chat.current?.agent_id" />
          <div v-if="empty && readyAgents.length && !chat.error" class="chat-starters" aria-label="试着从这里开始">
            <button v-for="starter in starters" :key="starter.label" type="button" :disabled="chat.creating || chat.loading || importing || !!chat.busy[chat.selected] || (!!chat.current && !chosen)" @click="startWith(starter.prompt)"><AppIcon :name="starter.icon" /><span>{{ starter.label }}</span><AppIcon name="chevron" class="starter-chevron" /></button>
          </div>
        </div>
      </section>
    </div>

    <dialog ref="folderDialog" class="conversation-dialog folder-dialog" aria-labelledby="folder-dialog-title" @cancel.prevent="closeFolder">
      <div class="dialog-heading"><h2 id="folder-dialog-title">对话工作目录</h2><button class="icon-button" type="button" aria-label="关闭工作目录" @click="closeFolder"><AppIcon name="close" /></button></div>
      <p class="dialog-intro">从已授权目录选择文件夹。发送消息后，目录固定。</p>
      <ContextToolbar />
      <div class="model-actions"><button class="button button-ghost" type="button" @click="closeFolder">完成</button></div>
    </dialog>
  </div>
</template>
