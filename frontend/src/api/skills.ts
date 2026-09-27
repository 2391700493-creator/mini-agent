import { request } from './client'

export interface Skill {
  id: string
  name: string
  description: string
  enabled: boolean
  updated_at: string
}
export interface SkillDetail extends Skill { instructions: string; revision: string }
export interface SkillList { items: Skill[]; issues: { directory: string; message: string }[] }
export type SkillSave = Pick<SkillDetail, 'name' | 'description' | 'instructions' | 'revision'>
export const listSkills = () => request<SkillList>('/skills')
export const refreshSkills = () => request<SkillList>('/skills/refresh', { method: 'POST', body: '{}' })
export const getSkill = (id: string) => request<SkillDetail>(`/skills/${encodeURIComponent(id)}`)
export const saveSkill = (id: string, data: SkillSave) => request<SkillDetail>(`/skills/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) })
export const toggleSkill = (id: string, enabled: boolean) => request<SkillDetail>(`/skills/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ enabled }) })
export const deleteSkill = (id: string) => request<void>(`/skills/${encodeURIComponent(id)}`, { method: 'DELETE' })
export const importSkill = (file: File) => request<SkillDetail>('/skills/import', { method: 'POST', body: file, headers: { 'Content-Type': 'application/zip' } }, 30000)
