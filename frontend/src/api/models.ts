import { request } from './client'

export interface ModelConfig {
  display_name: string
  model_id: string
  base_url: string
  context_length: number
  max_output_tokens: number
  temperature: number
  input_price: number | null
  output_price: number | null
  cached_input_price: number | null
  pricing_currency?: string
  price_unit_tokens?: number
}
export interface LanguageModel extends ModelConfig {
  id: string
  key_configured: boolean
  is_default: boolean
  updated_at: string
}
export interface ModelSave extends ModelConfig { api_key?: string }
export interface ConnectionResult {
  success: boolean
  code: string
  message: string
  suggestion: string
  reply: string | null
}
export const listModels = () => request<LanguageModel[]>('/models')
export const getModel = (id: string) => request<LanguageModel>(`/models/${encodeURIComponent(id)}`)
export const saveModel = (data: ModelSave, id?: string) => request<LanguageModel>(
  id ? `/models/${encodeURIComponent(id)}` : '/models',
  { method: id ? 'PUT' : 'POST', body: JSON.stringify(data) },
)
export const setDefaultModel = (id: string) => request<LanguageModel>(`/models/${encodeURIComponent(id)}/default`, { method: 'PUT' })
export const deleteModel = (id: string, replacementId?: string) => request<void>(`/models/${encodeURIComponent(id)}`, {
  method: 'DELETE', body: JSON.stringify({ replacement_id: replacementId || null }),
})
export const testModel = (id: string) => request<ConnectionResult>(`/models/${encodeURIComponent(id)}/test`, { method: 'POST' }, 25000)
