import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import * as api from '../api/chat'

const reason = (error: unknown) => error instanceof Error ? error.message : '操作未完成，请重试。'
export const useChatStore = defineStore('chat', () => {
  const runtimeEvents = ref<Record<string, api.RuntimeEvent[]>>({})
  const toolProcesses = ref<Record<string, api.ToolProcess[]>>({})
  const runTextLengths = new Map<string, number>()
  const seenRuntimeSequences = new Map<string, number>()
  const generationMessages = new Map<string, string>()
  const agents = ref<api.ChatAgent[]>([])
  const sessions = ref<api.Conversation[]>([])
  const details = ref<Record<string, api.ConversationDetail>>({})
  const sessionWidth = ref(160)
  const selected = ref('')
  const drafts = ref<Record<string, string>>({})
  const errors = ref<Record<string, string>>({})
  const busy = ref<Record<string, boolean>>({})
  const pendingRetry = new Map<string, { generationId: string; requestId: string }>()
  const pending = new Map<string, { content: string; attachmentKey: string; id: string }>()
  const loading = ref(false)
  const creating = ref(false)
  const composerReset = ref(0)
  const error = ref('')
  const current = computed(() => details.value[selected.value])
  const generating = computed(() => current.value?.generation?.status === 'generating')
  let disconnect: (() => void) | undefined
  let epoch = 0
  let streamEpoch = 0
  let listEpoch = 0
  let visible = false

  function detach() { ++streamEpoch; disconnect?.(); disconnect = undefined }
  function apply(value: api.Generation) {
    const detail = details.value[value.conversation_id]
    if (!detail) return
    detail.generation = value
    if (value.message) {
      const at = detail.messages.findIndex(m => m.id === value.message!.id)
      if (at < 0) detail.messages.push(value.message)
      else detail.messages[at] = value.message
      detail.messages.sort((a, b) => a.sequence - b.sequence)
      generationMessages.set(value.id, value.message.id)
      for (const process of toolProcesses.value[value.conversation_id] || []) {
        if (process.generation_id === value.id) process.assistant_message_id = value.message.id
      }
    }
    if (value.status !== 'generating') settleProcesses(value.conversation_id, value.id, value.status)
  }
  function settleProcesses(conversationId: string, generationId: string, status: api.ChatStatus) {
    const replacement: api.ToolProcessStatus = status === 'cancelled' ? 'cancelled' : 'unknown'
    for (const process of toolProcesses.value[conversationId] || []) {
      if (process.generation_id === generationId && process.status === 'running') process.status = replacement
    }
  }
  function receiveRuntime(conversationId: string, generationId: string, event: api.RuntimeEvent) {
    const runKey = `${conversationId}:${generationId}:${event.run_id}`
    const last = seenRuntimeSequences.get(runKey) || 0
    if (event.sequence <= last) return
    seenRuntimeSequences.set(runKey, event.sequence)
    if (event.type === 'text_delta') {
      runTextLengths.set(runKey, (runTextLengths.get(runKey) || 0) + (event.data.content?.length || 0))
      return
    }
    runtimeEvents.value[conversationId] = [...(runtimeEvents.value[conversationId] || []), event]
    if (event.type === 'run_end') { settleProcesses(conversationId, generationId, event.data.status as api.ChatStatus); return }
    if (!event.call_id || (event.type !== 'tool_start' && event.type !== 'tool_result')) return
    const all = toolProcesses.value[conversationId] || []
    const index = all.findIndex(item => item.run_id === event.run_id && item.call_id === event.call_id)
    if (event.type === 'tool_start') {
      if (index >= 0) return
      toolProcesses.value[conversationId] = [...all, {
        id: `${event.run_id}:${event.call_id}`, conversation_id: conversationId, generation_id: generationId,
        assistant_message_id: generationMessages.get(generationId) || null, run_id: event.run_id, call_id: event.call_id,
        sequence: event.sequence, text_offset: event.data.text_offset ?? runTextLengths.get(runKey) ?? 0, kind: event.data.tool_kind || 'unknown',
        name: event.data.display_name || '工具', server_name: event.data.server_name || null, status: 'running',
        input: event.data.input || (event.data.input_summary ? { value: event.data.input_summary, truncated: true, notice: '完整输入请在运行详情中按需查看。' } : null), result: null, summary: '正在执行', duration_ms: null,
      }]
      return
    }
    if (index < 0) return
    const process = all[index]!
    process.status = event.data.status === 'completed' ? 'completed' : event.data.status === 'cancelled' ? 'cancelled' : 'failed'
    process.result = event.data.result || null
    process.summary = event.data.summary || (process.status === 'completed' ? '工具执行完成。' : '工具未完成。')
    process.duration_ms = typeof event.data.duration_ms === 'number' ? event.data.duration_ms : null
  }
  function connect() {
    detach()
    const item = current.value
    if (!visible || item?.generation?.status !== 'generating') return
    const id = item.id
    const revision = streamEpoch
    disconnect = api.subscribe(id, item.generation.id, value => {
      if (selected.value !== id || revision !== streamEpoch) return
      errors.value[id] = ''
      apply(value)
      if (value.status !== 'generating') { detach(); void refreshList() }
    }, () => {
      if (selected.value !== id || revision !== streamEpoch) return
      settleProcesses(id, item.generation!.id, 'failed')
      errors.value[id] = '进度连接中断，已请求取消生成。正在重连确认最终状态。'
    }, event => {
      if (selected.value !== id || revision !== streamEpoch) return
      receiveRuntime(id, item.generation!.id, event)
    })
  }
  async function refreshList() {
    const revision = ++listEpoch
    try {
      const items = await api.conversations()
      if (revision === listEpoch) { sessions.value = items; for (const item of items) if (details.value[item.id]) Object.assign(details.value[item.id], item) }
    } catch (e) { if (revision === listEpoch) error.value = reason(e) }
  }
  async function select(id: string) {
    const revision = ++epoch
    selected.value = id
    detach()
    loading.value = true
    error.value = ''
    try {
      const detail = await api.conversationDetail(id)
      if (revision !== epoch) return
      details.value[id] = detail
      if (detail.generation) apply(detail.generation)
      runtimeEvents.value[id] = []
      toolProcesses.value[id] = []
      for (const event of detail.runtime_events || []) receiveRuntime(id, event.run_id, event)
      errors.value[id] = ''
      connect()
    } catch (e) { if (revision === epoch) error.value = reason(e) }
    finally { if (revision === epoch) loading.value = false }
  }
  async function load(id?: string) {
    visible = true
    error.value = ''
    loading.value = true
    try {
      const [items, choices] = await Promise.all([api.conversations(), api.chatAgents()])
      sessions.value = items
      agents.value = choices
      const target = id || selected.value || items[0]?.id
      if (target) await select(target)
    } catch (e) { error.value = reason(e) }
    finally { loading.value = false }
  }
  async function create(data: { project_id?: string | null; folder?: string | null } = {}) {
    if (creating.value) return
    creating.value = true
    error.value = ''
    try {
      const item = await api.createConversation(data)
      ++listEpoch
      sessions.value = sortSessions([item, ...sessions.value.filter(session => session.id !== item.id)])
      await select(item.id)
    } catch (e) { error.value = reason(e) }
    finally { creating.value = false }
  }
  async function changeAgent(agentId: string) {
    const id = selected.value
    if (!id || busy.value[id] || generating.value) return
    busy.value[id] = true
    errors.value[id] = ''
    try {
      const item = await api.chooseAgent(id, agentId)
      if (details.value[id]) details.value[id].agent_id = item.agent_id
    } catch (e) { errors.value[id] = reason(e) }
    finally { busy.value[id] = false }
  }
  async function send(contentOverride?: string, attachments: api.AttachmentInput[] = []) {
    const id = selected.value
    const draftContent = drafts.value[id] || ''
    const content = contentOverride ?? draftContent
    if ((!content.trim() && !attachments.length) || !id || busy.value[id] || generating.value || !agents.value.some(a => a.id === current.value?.agent_id && a.is_ready !== false)) return false
    busy.value[id] = true
    errors.value[id] = ''
    const prior = pending.get(id)
    const attachmentKey = JSON.stringify(attachments)
    const attempt = prior?.content === content && prior?.attachmentKey === attachmentKey ? prior : { content, attachmentKey, id: crypto.randomUUID() }
    pending.set(id, attempt)
    try {
      const generation = await (attachments.length ? api.sendMessage(id, content, attempt.id, attachments) : api.sendMessage(id, content, attempt.id))
      // 只有明确收到后端保存成功，才清空输入；响应丢失时复用请求标识避免重复消息。
      if (contentOverride === undefined && drafts.value[id] === draftContent) drafts.value[id] = ''
      pending.delete(id)
      apply(generation)
      if (!visible || selected.value !== id) {
        return
      }
      try {
        const detail = await api.conversationDetail(id)
        details.value[id] = detail
        if (detail.generation) apply(detail.generation)
        if (selected.value === id) connect()
        await refreshList()
      } catch (e) { errors.value[id] = `消息已保存，读取进度失败：${reason(e)}` }
      return true
    } catch (e) { errors.value[id] = reason(e); return false }
    finally { busy.value[id] = false }
  }
  async function regenerate() {
    const item = current.value
    if (!item?.generation || generating.value || busy.value[item.id]) return false
    const id = item.id
    const generationId = item.generation.id
    const prior = pendingRetry.get(id)
    const attempt = prior?.generationId === generationId ? prior : { generationId, requestId: crypto.randomUUID() }
    pendingRetry.set(id, attempt)
    busy.value[id] = true; errors.value[id] = ''
    try {
      const result = await api.regenerateReply(id, generationId, attempt.requestId)
      pendingRetry.delete(id)
      apply(result)
      details.value[id] = await api.conversationDetail(id)
      if (selected.value === id && visible) connect()
      await refreshList()
      return true
    } catch (cause) { errors.value[id] = reason(cause); return false }
    finally { busy.value[id] = false }
  }
  async function stop() {
    const item = current.value
    if (!item?.generation || busy.value[item.id]) return
    const id = item.id
    busy.value[id] = true
    detach()
    try { apply(await api.stopGeneration(id, item.generation.id)); errors.value[id] = ''; await refreshList() }
    catch (e) { errors.value[id] = `停止未确认：${reason(e)}`; if (selected.value === id) connect() }
    finally { busy.value[id] = false }
  }
  function sortSessions(items: api.Conversation[]) {
    return items.sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.updated_at.localeCompare(a.updated_at) || a.id.localeCompare(b.id))
  }
  async function update(id: string, data: { title?: string; pinned?: boolean; project_id?: string | null; folder?: string | null }) {
    if (busy.value[id]) return false
    busy.value[id] = true
    error.value = ''
    try {
      const item = await api.updateConversation(id, data)
      ++listEpoch
      sessions.value = sortSessions(sessions.value.map(row => row.id === id ? item : row))
      if (details.value[id]) Object.assign(details.value[id], item)
      return true
    } catch (e) { error.value = reason(e); return false }
    finally { busy.value[id] = false }
  }
  async function remove(id: string) {
    if (busy.value[id]) return false
    busy.value[id] = true
    error.value = ''
    try {
      await api.deleteConversation(id)
      ++listEpoch
      sessions.value = sessions.value.filter(row => row.id !== id)
      delete details.value[id]
      delete drafts.value[id]
      delete errors.value[id]
      pending.delete(id)
      if (selected.value === id) {
        ++epoch
        detach()
        selected.value = ''
        loading.value = false
        const next = sessions.value[0]
        if (next) await select(next.id)
      }
      return true
    } catch (e) { error.value = reason(e); return false }
    finally { busy.value[id] = false }
  }
  function clearNewComposer() { drafts.value[selected.value] = ''; composerReset.value++ }
  function leave() {
    visible = false; ++epoch; detach()
  }
  return { composerReset, clearNewComposer, runtimeEvents, toolProcesses, agents, sessions, sessionWidth, selected, drafts, errors, busy, loading, creating, error, current, generating,
    load, select, create, update, remove, changeAgent, send, regenerate, stop, leave, refreshList }
})
