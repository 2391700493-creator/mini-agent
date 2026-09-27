import { createPinia, setActivePinia } from 'pinia'
import { afterEach, expect, it, vi } from 'vitest'
import { useSystemStore } from '../src/stores/system'

afterEach(() => vi.unstubAllGlobals())

it('检查期间合并重复点击，避免并行健康请求', async () => {
  setActivePinia(createPinia())
  let finish!: (response: Response) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve })))
  const store = useSystemStore()
  const pending = store.checkConnection()
  expect(store.status).toBe('loading')
  await store.checkConnection()
  expect(fetch).toHaveBeenCalledTimes(1)
  finish(new Response(JSON.stringify({ status: 'ok', database: 'connected', project: 'mini-agent' })))
  await pending
  expect(store.status).toBe('ready')
})
