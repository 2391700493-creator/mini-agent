import { request } from './client'

export interface Memory {
  id: string; agent_id: string; content: string; source_conversation_id: string | null
  created_at: string; updated_at: string
}
export const listMemories = (agentId: string) => request<Memory[]>(`/agents/${encodeURIComponent(agentId)}/memories`)
export const saveMemory = (agentId: string, content: string, id?: string) => request<Memory>(id ? `/agents/${encodeURIComponent(agentId)}/memories/${encodeURIComponent(id)}` : `/agents/${encodeURIComponent(agentId)}/memories`, { method: id ? 'PUT' : 'POST', body: JSON.stringify({ content }) })
export const removeMemory = (agentId: string, id: string) => request<void>(`/agents/${encodeURIComponent(agentId)}/memories/${encodeURIComponent(id)}`, { method: 'DELETE' })
