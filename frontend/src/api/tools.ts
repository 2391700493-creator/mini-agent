import { request } from './client'

export interface Parameter {
  description: string
  type?: string
  anyOf?: { type: string }[]
  enum?: string[]
  default?: unknown
  minimum?: number
  maximum?: number
  maxLength?: number
}
export interface Tool {
  id: string
  name: string
  description: string
  limitations: string[]
  input_schema: { properties: Record<string, Parameter>; required?: string[] }
  enabled: boolean
  is_builtin: boolean
  available: boolean
  unavailable_reason: string | null
  defaults: Record<string, string>
}
export const listTools = () => request<Tool[]>('/tools')
export const getTool = (id: string) => request<Tool>(`/tools/${encodeURIComponent(id)}`)
export const toggleTool = (id: string, enabled: boolean) => request<Tool>(`/tools/${encodeURIComponent(id)}`, {
  method: 'PATCH', body: JSON.stringify({ enabled }),
})
