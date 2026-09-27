import { request } from './client'

export type CaseStatus = 'pending' | 'executing' | 'grading' | 'passed' | 'failed' | 'execution_failed' | 'grading_failed'
export type TaskStatus = 'pending' | 'running' | 'completed' | 'interrupted'
export interface Dataset { id: string; name: string; description: string; case_count: number; created_at: string; updated_at: string }
export interface ProcessRules { expected_tool_ids: string[]; max_tool_calls: number | null; max_duration_ms: number | null }
export interface HistoryMessage { role: 'user' | 'assistant'; content: string }
export interface TestCase { id: string; dataset_id: string; position: number; question: string; expected_answer: string | null; grading_criteria: string | null; history?: HistoryMessage[]; process_rules?: ProcessRules }
export interface DatasetDetail extends Dataset { cases: TestCase[] }
export interface TaskCase { id: string; position: number; question: string; expected_answer: string | null; grading_criteria: string | null; history?: HistoryMessage[]; process_rules?: ProcessRules; status: CaseStatus; run_id: string | null; answer: string | null; score: number | null; reason: string | null; error: string | null; grading_error_kind: string | null; scoring_duration_ms: number | null; scoring_total_tokens: number | null; scoring_cached_input_tokens?: number | null; scoring_usage_complete?: boolean; grading_attempts: number; issue_category?: string | null; review_status?: 'unreviewed' | 'confirmed' | 'dismissed'; review_note?: string | null }
export interface TaskStats { total: number; completed: number; passed: number; failed: number; execution_failed: number; grading_failed: number; average_score: number | null }
export interface EvaluationTask { id: string; dataset_id: string; dataset_name: string; agent_id: string; agent_name: string; scoring_model_id: string; scoring_model_name: string; passing_score: number; tools_allowed: boolean; status: TaskStatus; created_at: string; started_at: string | null; ended_at: string | null; stats: TaskStats }
export interface TaskDetail extends EvaluationTask { scoring_model_identifier: string; scoring_model_snapshot: Record<string, unknown>; agent_snapshot: Record<string, unknown>; cases: TaskCase[] }
export interface EvaluationOptions { agents: { id: string; name: string }[]; models: { id: string; name: string; model_id: string }[] }
export const listDatasets = () => request<Dataset[]>('/evaluations/datasets')
export const getDataset = (id: string) => request<DatasetDetail>(`/evaluations/datasets/${encodeURIComponent(id)}`)
export const saveDataset = (data: { name: string; description: string }, id?: string) => request<Dataset>(id ? `/evaluations/datasets/${encodeURIComponent(id)}` : '/evaluations/datasets', { method: id ? 'PUT' : 'POST', body: JSON.stringify(data) })
export const removeDataset = (id: string) => request<void>(`/evaluations/datasets/${encodeURIComponent(id)}`, { method: 'DELETE' })
export const saveCase = (datasetId: string, data: { question: string; expected_answer: string | null; grading_criteria: string | null; history?: HistoryMessage[]; process_rules?: ProcessRules }, id?: string) => request<TestCase>(id ? `/evaluations/datasets/${encodeURIComponent(datasetId)}/cases/${encodeURIComponent(id)}` : `/evaluations/datasets/${encodeURIComponent(datasetId)}/cases`, { method: id ? 'PUT' : 'POST', body: JSON.stringify(data) })
export const removeCase = (datasetId: string, id: string) => request<void>(`/evaluations/datasets/${encodeURIComponent(datasetId)}/cases/${encodeURIComponent(id)}`, { method: 'DELETE' })
export const evaluationOptions = () => request<EvaluationOptions>('/evaluations/options')
export const listTasks = () => request<EvaluationTask[]>('/evaluations/tasks')
export const getTask = (id: string) => request<TaskDetail>(`/evaluations/tasks/${encodeURIComponent(id)}`)
export const removeTask = (id: string) => request<void>(`/evaluations/tasks/${encodeURIComponent(id)}`, { method: 'DELETE' })
export const createTask = (data: { dataset_id: string; agent_id: string; scoring_model_id: string; passing_score: number; tools_allowed: boolean }) => request<EvaluationTask>('/evaluations/tasks', { method: 'POST', body: JSON.stringify(data) })
export const startTask = (id: string) => request<TaskDetail>(`/evaluations/tasks/${encodeURIComponent(id)}/start`, { method: 'POST', body: '{}' })
export const stopTask = (id: string) => request<TaskDetail>(`/evaluations/tasks/${encodeURIComponent(id)}/stop`, { method: 'POST', body: '{}' })
export const retryFailed = (id: string) => request<TaskDetail>(`/evaluations/tasks/${encodeURIComponent(id)}/retry-failed`, { method: 'POST', body: '{}' })
export const reviewTaskCase = (taskId: string, caseId: string, data: { review_status: 'unreviewed' | 'confirmed' | 'dismissed'; review_note?: string | null }) => request<TaskDetail>(`/evaluations/tasks/${encodeURIComponent(taskId)}/cases/${encodeURIComponent(caseId)}/review`, { method: 'PATCH', body: JSON.stringify(data) })
