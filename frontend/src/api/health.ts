import { ApiError, request } from './client'

export interface HealthResponse {
  status: 'ok'
  database: 'connected'
  project: string
}

export async function getHealth(): Promise<HealthResponse> {
  const data = await request<HealthResponse>('/health')
  if (!data || data.status !== 'ok' || data.database !== 'connected' || data.project !== 'mini-agent') {
    throw new ApiError('本地服务返回异常，请检查后端版本后重试。')
  }
  return data
}
