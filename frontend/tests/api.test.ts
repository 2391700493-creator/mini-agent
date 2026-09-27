import { afterEach, describe, expect, it, vi } from 'vitest'
import { getHealth } from '../src/api/health'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('API 请求与异常处理', () => {
  it('数据库尚未迁移时给出明确提示', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 503 })))
    await expect(getHealth()).rejects.toThrow('数据库迁移')
  })

  it('代理连接失败时转换成可读错误', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 502 })))
    await expect(getHealth()).rejects.toThrow('确认后端已启动')
  })

  it('不会将无效响应误判为成功', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ok' }))))
    await expect(getHealth()).rejects.toThrow('本地服务返回异常')
  })

  it('HTML 回退页面不会被当成健康结果', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html></html>')))
    await expect(getHealth()).rejects.toThrow('确认后端已启动')
  })

  it('超过 5 秒主动终止请求并允许用户重试', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url: string, options: RequestInit) =>
      new Promise((_resolve, reject) => {
        options.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
      }),
    ))
    const failure = expect(getHealth()).rejects.toThrow('连接超时')
    await vi.advanceTimersByTimeAsync(5000)
    await failure
    expect(vi.getTimerCount()).toBe(0)
  })
})
