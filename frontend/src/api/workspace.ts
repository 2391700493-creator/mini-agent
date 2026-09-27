import { request } from './client'
export interface Project { id: string; name: string }
export const projects = () => request<Project[]>('/workspace/projects')
export const saveProject = (name: string, id?: string) => request<Project>(`/workspace/projects${id ? `/${encodeURIComponent(id)}` : ''}`, { method: id ? 'PUT' : 'POST', body: JSON.stringify({ name }) })
export const deleteProject = (id: string) => request<void>(`/workspace/projects/${encodeURIComponent(id)}`, { method: 'DELETE' })
export const syncArchive = (id: string) => request<void>(`/workspace/archive/${encodeURIComponent(id)}`, { method: 'POST', body: '{}' })

export const chooseFolder = () => request<{ folder: string | null }>('/workspace/folders/choose', { method: 'POST', body: '{}' }, 125000)
