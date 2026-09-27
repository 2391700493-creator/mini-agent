import { request } from './client'

export type ChatStatus = 'generating' | 'completed' | 'failed' | 'cancelled' | 'limit_reached'
export interface ChatAgent {
  id: string; name: string; is_default: boolean
  description?: string; is_ready?: boolean; unavailable_reason?: string | null
  tool_count?: number; skill_count?: number; mcp_server_count?: number
}
export interface Conversation { project_id?: string | null; folder?: string | null; archive_error?: string | null; pinned: boolean; id: string; title: string; agent_id: string | null; created_at: string; updated_at: string }
export interface AttachmentInput { name: string; mime_type: string; data: string }
export interface MessageAttachment { id: string; name: string; mime_type: string; size: number; width?: number | null; height?: number | null }
export type MessageFeedback = 'helpful' | 'unhelpful' | null
export interface ChatMessage {
  id: string; conversation_id: string; sequence: number; role: 'user' | 'assistant'; content: string
  attachments?: MessageAttachment[]
  status: ChatStatus; created_at: string; agent_id: string | null; agent_name: string | null
  feedback_rating?: MessageFeedback
}
export interface Generation {
  id: string; conversation_id: string; status: ChatStatus; error: string | null
  message: ChatMessage | null; saved: boolean
}
export interface RuntimeEvent {
  run_id: string; sequence: number; type: string; round: number | null; call_id: string | null
  occurred_at?: string
  data: {
    status?: string; reason?: string; tool_kind?: string; tool_name?: string; display_name?: string; server_name?: string
    summary?: string; content?: string; duration_ms?: number; code?: string; text_offset?: number; executed?: boolean
    input_summary?: string; model_name?: string; model_identifier?: string
    purpose?: 'agent_loop' | 'context_compression'; usage?: { prompt_tokens: number | null; completion_tokens: number | null; total_tokens: number | null; cached_input_tokens?: number | null } | null
    trigger_reason?: string; estimated_input_tokens?: number; estimated_tokens_before?: number; estimated_tokens_after?: number | null
    processed_message_count?: number; retained_message_count?: number; estimation?: boolean
    input?: Presentation; result?: Presentation
  }
}
export interface Presentation { value: unknown; truncated: boolean; notice?: string }
export type ToolProcessStatus = 'running' | 'completed' | 'failed' | 'cancelled' | 'unknown'
export interface ToolProcess {
  id: string; conversation_id: string; generation_id: string; run_id: string; call_id: string
  assistant_message_id: string | null
  sequence: number; text_offset: number; kind: string; name: string; server_name: string | null
  status: ToolProcessStatus; input: Presentation | null; result: Presentation | null
  summary: string; duration_ms: number | null
}
export interface ConversationDetail extends Conversation { messages: ChatMessage[]; generation: Generation | null; runtime_events?: RuntimeEvent[] }
const path = (id: string) => `/chat/conversations/${encodeURIComponent(id)}` as const
export const chatAgents = () => request<ChatAgent[]>('/chat/agents')
export const conversations = () => request<Conversation[]>('/chat/conversations')
export const createConversation = (data: { project_id?: string | null; folder?: string | null } = {}) => request<Conversation>('/chat/conversations', { method: 'POST', body: JSON.stringify(data) })
export const conversationDetail = (id: string) => request<ConversationDetail>(path(id))
export const chooseAgent = (id: string, agentId: string) => request<Conversation>(`${path(id)}/agent`, { method: 'PUT', body: JSON.stringify({ agent_id: agentId }) })
export const sendMessage = (id: string, content: string, requestId: string, attachments?: AttachmentInput[]) => request<Generation>(`${path(id)}/messages`, { method: 'POST', body: JSON.stringify({ content, request_id: requestId, ...(attachments?.length ? { attachments } : {}) }) }, 15000)
export const stopGeneration = (id: string, generationId: string) => request<Generation>(`${path(id)}/generations/${encodeURIComponent(generationId)}/stop`, { method: 'POST', body: '{}' }, 15000)
export function subscribe(id: string, generationId: string, receive: (value: Generation) => void, failed: () => void, runtime?: (event: RuntimeEvent) => void) {
  const source = new EventSource(`/api${path(id)}/generations/${encodeURIComponent(generationId)}/events`)
  source.onmessage = event => {
    try { receive(JSON.parse(event.data) as Generation) }
    catch { failed(); source.close() }
  }
  source.addEventListener('runtime', event => {
    try { runtime?.(JSON.parse((event as MessageEvent).data) as RuntimeEvent) }
    catch { failed(); source.close() }
  })
  source.onerror = failed
  return () => source.close()
}

export const updateConversation = (id: string, data: { title?: string; pinned?: boolean; project_id?: string | null; folder?: string | null }) => request<Conversation>(path(id), { method: 'PATCH', body: JSON.stringify(data) })
export const deleteConversation = (id: string) => request<void>(path(id), { method: 'DELETE' })

export const regenerateReply = (id: string, generationId: string, requestId: string) => request<Generation>(`${path(id)}/generations/${encodeURIComponent(generationId)}/retry`, { method: 'POST', body: JSON.stringify({ request_id: requestId }) }, 15000)
export const saveMessageFeedback = (id: string, messageId: string, rating: MessageFeedback) => request<ChatMessage>(`${path(id)}/messages/${encodeURIComponent(messageId)}/feedback`, { method: 'PATCH', body: JSON.stringify({ rating }) })
