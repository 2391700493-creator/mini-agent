import { request } from './client'

export interface Capability { id: string; name: string; description: string; enabled: boolean; unavailable_reason: string | null }
export interface AgentOptions {
  models: { id: string; name: string; model_id: string; is_default: boolean; context_length: number; max_output_tokens: number }[]
  tools: Capability[]; skills: Capability[]; mcp_servers: Capability[]
  skill_issues: { directory: string; message: string }[]
}
export interface AgentSummary {
  id: string; name: string; description: string; model_id: string; model_name: string; model_identifier: string
  max_rounds: number; is_default: boolean; updated_at: string
  max_runtime_seconds?: number; max_tool_calls?: number; max_total_tokens?: number | null
  auto_compress: boolean; compression_trigger_ratio: number; compression_keep_recent_turns: number; compression_summary_target_tokens: number
  tool_count: number; skill_count: number; mcp_server_count: number
  is_ready?: boolean; unavailable_reason?: string | null
}
export interface AgentDetail extends AgentSummary {
  system_prompt: string; prompt_version: number; tools: Capability[]; skills: Capability[]; mcp_servers: Capability[]
}
export interface AgentSave {
  name: string; description: string; system_prompt: string; model_id: string; max_rounds: number
  max_runtime_seconds: number; max_tool_calls: number; max_total_tokens: number | null
  auto_compress: boolean; compression_trigger_ratio: number; compression_keep_recent_turns: number; compression_summary_target_tokens: number
  tool_ids: string[]; skill_ids: string[]; mcp_server_ids: string[]
}
export const listAgents = () => request<AgentSummary[]>('/agents')
export const agentOptions = () => request<AgentOptions>('/agents/options', {}, 15000)
export const getAgent = (id: string) => request<AgentDetail>(`/agents/${encodeURIComponent(id)}`, {}, 15000)
export const saveAgent = (data: AgentSave, id?: string) => request<AgentDetail>(id ? `/agents/${encodeURIComponent(id)}` : '/agents', { method: id ? 'PUT' : 'POST', body: JSON.stringify(data) }, 15000)
export const setDefaultAgent = (id: string) => request<AgentSummary>(`/agents/${encodeURIComponent(id)}/default`, { method: 'PUT', body: '{}' })
export const deleteAgent = (id: string, replacementId?: string) => request<void>(`/agents/${encodeURIComponent(id)}`, { method: 'DELETE', body: JSON.stringify({ replacement_id: replacementId || null }) })
