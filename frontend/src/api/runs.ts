import { request } from './client'

export type RunStatus = 'running' | 'success' | 'partial' | 'failed' | 'cancelled'
export interface RunSummary {
  id: string; conversation_id: string; status: RunStatus
  agent_id: string; agent_name: string; model_id: string | null; model_name: string | null; model_identifier: string | null
  started_at: string; ended_at: string | null; duration_ms: number | null
  model_call_count: number; tool_call_count: number
  input_tokens: number | null; output_tokens: number | null; total_tokens: number | null; cached_input_tokens: number | null
  cost?: number | null; cost_currency?: string | null; cost_status?: 'complete' | 'incomplete' | 'unknown'
  usage_status: 'complete' | 'incomplete' | 'unknown'; first_output_ms: number | null
  end_reason: string | null; error_summary: string | null
}
export interface RunAgentOption { id: string; name: string }
export interface RunModelOption { id: string | null; name: string }
export interface RunMetrics { total: number; success_rate: number | null; p95_duration_ms: number | null; first_output_ms: number | null; total_tokens: number | null; tool_error_rate: number | null; total_cost: number | null; cost_currency: string | null; incomplete_cost_runs: number }
export interface RunPage { items: RunSummary[]; total: number; page: number; page_size: number; agents: RunAgentOption[]; models?: RunModelOption[]; metrics?: RunMetrics }
export interface RunEvent {
  run_id: string; sequence: number; type: string; round: number | null; call_id: string | null
  occurred_at: string; data: Record<string, unknown>; has_payload: boolean
}
export interface RunDetail extends RunSummary { events: RunEvent[]; final_answer: string | null }
export interface RunEventPayload { run_id: string; sequence: number; payload: Record<string, unknown> }

export function listRuns(params: { page: number; pageSize: number; status?: RunStatus; agentId?: string; modelId?: string; source?: 'chat' | 'evaluation'; startedAfter?: string; startedBefore?: string }) {
  const query = new URLSearchParams({ page: String(params.page), page_size: String(params.pageSize) })
  if (params.status) query.set('status', params.status)
  if (params.agentId) query.set('agent_id', params.agentId)
  if (params.modelId) query.set('model_id', params.modelId)
  if (params.source) query.set('source', params.source)
  if (params.startedAfter) query.set('started_after', params.startedAfter)
  if (params.startedBefore) query.set('started_before', params.startedBefore)
  return request<RunPage>(`/runs?${query}`)
}
export const runDetail = (id: string) => request<RunDetail>(`/runs/${encodeURIComponent(id)}`)
export const eventPayload = (id: string, sequence: number) => request<RunEventPayload>(`/runs/${encodeURIComponent(id)}/events/${sequence}/payload`)
export const removeRun = (id: string) => request<void>(`/runs/${encodeURIComponent(id)}`, { method: 'DELETE' })
