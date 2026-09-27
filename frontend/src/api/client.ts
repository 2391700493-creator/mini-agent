export class ApiError extends Error {
  constructor(message: string, public readonly status?: number, public readonly fields: Record<string, string> = {}) { super(message) }
}

export async function request<T>(path: `/${string}`, options: RequestInit = {}, timeout = 5000): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)
  try {
    const response = await fetch(`/api${path}`, {
      ...options,
      headers: { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers },
      signal: controller.signal,
    })
    if (!response.ok) {
      if (path.startsWith('/workspace') || path.startsWith('/chat') || path.startsWith('/agents') || path.startsWith('/models') || path.startsWith('/tools') || path.startsWith('/skills') || path.startsWith('/mcp')) {
        const body = await response.json().catch(() => null)
        if (typeof body?.detail === 'string') throw new ApiError(body.detail, response.status)
        if (body?.detail?.fields) throw new ApiError('请检查标记的字段。', response.status, body.detail.fields)
      }
      throw new ApiError(response.status === 503
        ? '服务暂未就绪，请检查数据库迁移后重试。'
        : '未能连接本地服务，请确认后端已启动。', response.status)
    }
    return (response.status === 204 ? undefined : await response.json()) as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new ApiError(controller.signal.aborted
      ? '连接超时，请检查本地服务后重试。'
      : '未能连接本地服务，请确认后端已启动。')
  } finally {
    clearTimeout(timer)
  }
}
