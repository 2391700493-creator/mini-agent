import { request } from './client'

export interface McpTool { name: string; description: string; input_schema: Record<string, unknown> }
export interface McpServer {
  id: string; name: string; description: string; command: string; args: string[]
  env: Record<string, string>; enabled: boolean; testing: boolean
  status: 'untested' | 'success' | 'error' | 'stale'; message: string; diagnostic: string | null
  tested_at: string | null; last_success_at: string | null; tool_count: number | null; tools: McpTool[]
}
export const listMcp = () => request<McpServer[]>('/mcp')
export const getMcp = (id: string) => request<McpServer>(`/mcp/${encodeURIComponent(id)}`)
export const toggleMcp = (id: string, enabled: boolean) => request<McpServer>(`/mcp/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ enabled }) })
export const deleteMcp = (id: string) => request<void>(`/mcp/${encodeURIComponent(id)}`, { method: 'DELETE' })
export const testMcp = (id: string) => request<McpServer>(`/mcp/${encodeURIComponent(id)}/test`, { method: 'POST', body: '{}' }, 30000)
export const importMcpJson = (configuration: string, serverName?: string) => request<McpServer>('/mcp/import', { method: 'POST', body: JSON.stringify({ configuration, ...(serverName ? { server_name: serverName } : {}) }) })
export const updateMcpJson = (id: string, configuration: string) => request<McpServer>(`/mcp/${encodeURIComponent(id)}/import`, { method: 'PUT', body: JSON.stringify({ configuration }) })
