import { request } from './client'
export interface AutomationInput { name: string; prompt: string; agent_id: string; frequency: 'daily' | 'weekdays' | 'weekly'; time: string; weekday: number; timezone: string; allow_tools: boolean; enabled: boolean }
export interface Automation extends Omit<AutomationInput, 'agent_id'> { id: string; agent_id: string | null; next_run_at: string; status: string; last_error: string | null; last_conversation_id: string | null; last_run_at: string | null }
export const listAutomations = () => request<Automation[]>('/automations')
export const saveAutomation = (data: AutomationInput, id?: string) => request<Automation>(`/automations${id ? `/${id}` : ''}`, { method: id ? 'PUT' : 'POST', body: JSON.stringify(data) })
export const toggleAutomation = (id: string, enabled: boolean) => request<Automation>(`/automations/${id}`, { method: 'PATCH', body: JSON.stringify({ enabled }) })
export const runAutomation = (id: string, stop = false) => request<Automation>(`/automations/${id}/${stop ? 'stop' : 'run'}`, { method: 'POST', body: '{}' }, 40000)
export const deleteAutomation = (id: string) => request<void>(`/automations/${id}`, { method: 'DELETE' })
