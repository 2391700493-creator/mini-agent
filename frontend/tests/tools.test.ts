import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App.vue'
vi.mock('../src/api/chat', async importOriginal => ({ ...await importOriginal<typeof import('../src/api/chat')>(), conversations: async () => [] }))
vi.mock('../src/api/workspace', () => ({ projects: async () => [] }))
import { createAppRouter } from '../src/router'
import * as api from '../src/api/tools'

vi.mock('../src/api/tools', () => ({ listTools: vi.fn(), getTool: vi.fn(), toggleTool: vi.fn() }))
const tool: api.Tool = {
  id: 'current_time', name: '当前时间', description: '查询指定时区的当前日期和时间。',
  limitations: ['禁止使用 CST 等歧义缩写。'], enabled: true, is_builtin: true, available: true,
  unavailable_reason: null, defaults: { timezone: 'Asia/Shanghai' },
  input_schema: { properties: { timezone: { type: 'string', description: 'IANA 时区名称，省略使用默认时区。' } } },
}
let wrapper: VueWrapper
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.listTools).mockResolvedValue([structuredClone(tool)])
  vi.mocked(api.getTool).mockResolvedValue(structuredClone(tool))
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ok', database: 'connected', project: 'mini-agent' }))))
})
afterEach(() => { wrapper?.unmount(); document.body.innerHTML = ''; vi.unstubAllGlobals() })
async function open(path = '/tools') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  wrapper = mount(App, { attachTo: document.body, global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return router
}
describe('工具管理', () => {
  it('显示名称、用途摘要与启用状态，内置工具没有编辑和删除入口', async () => {
    await open()
    expect(wrapper.text()).toContain(tool.description)
    expect(wrapper.text()).toContain('系统内置')
    expect(wrapper.get('a[href="/tools/current_time"].text-link').text()).toContain('查看详情')
    expect(wrapper.get('[role="switch"]').attributes('aria-checked')).toBe('true')
    expect(wrapper.findAll('button').some(button => ['删除', '编辑'].includes(button.text()))).toBe(false)
  })
  it('等待启停保存成功再更新，保存中阻止重复点击', async () => {
    await open()
    let finish!: (value: api.Tool) => void
    vi.mocked(api.toggleTool).mockReturnValue(new Promise(resolve => { finish = resolve }))
    await wrapper.get('[role="switch"]').trigger('click')
    await wrapper.get('[role="switch"]').trigger('click')
    expect(api.toggleTool).toHaveBeenCalledTimes(1)
    expect(api.toggleTool).toHaveBeenCalledWith('current_time', false)
    expect(wrapper.get('[role="switch"]').attributes('disabled')).toBeDefined()
    finish({ ...tool, enabled: false })
    await flushPromises()
    expect(wrapper.get('[role="switch"]').attributes('aria-checked')).toBe('false')
    expect(wrapper.text()).toContain('已停用「当前时间」')
  })
  it('保存失败保留原状态并显示原因', async () => {
    vi.mocked(api.toggleTool).mockRejectedValue(new Error('本地工具正在执行，请稍后重试。'))
    await open()
    await wrapper.get('[role="switch"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="switch"]').attributes('aria-checked')).toBe('true')
    expect(wrapper.get('.model-feedback').text()).toContain('本地工具正在执行')
  })
  it('从列表进入详情，并可直接加载详情路由', async () => {
    const router = await open()
    await wrapper.get('.tool-card-bottom a').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/tools/current_time')
    expect(wrapper.get('h1').text()).toBe('当前时间')
    expect(wrapper.get('nav [aria-current="page"]').attributes('href')).toBe('/tools')
    expect(wrapper.text()).toContain('输入参数')
    expect(wrapper.text()).toContain('Asia/Shanghai')
    expect(wrapper.text()).toContain('禁止使用 CST')
    expect(wrapper.text()).toContain('POST /api/tools/current_time/execute')
    expect(wrapper.text()).toContain('尚未执行')
    wrapper.unmount()
    await open('/tools/current_time')
    expect(api.getTool).toHaveBeenCalledWith('current_time')
    expect(wrapper.get('h1').text()).toBe('当前时间')
  })
  it('详情可停用，返回列表后使用后端持久化状态', async () => {
    vi.mocked(api.toggleTool).mockResolvedValue({ ...tool, enabled: false })
    vi.mocked(api.listTools).mockResolvedValue([{ ...tool, enabled: false }])
    const router = await open('/tools/current_time')
    await wrapper.get('[role="switch"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="switch"]').attributes('aria-checked')).toBe('false')
    await wrapper.get('.form-back').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/tools')
    expect(wrapper.get('[role="switch"]').attributes('aria-checked')).toBe('false')
  })
  it('加载失败可重试，工具不存在时保留返回入口', async () => {
    vi.mocked(api.listTools).mockRejectedValueOnce(new Error('后端离线'))
    await open()
    expect(wrapper.get('.model-feedback').text()).toContain('后端离线')
    await wrapper.get('.model-feedback button').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.tool-card')).toHaveLength(1)
    wrapper.unmount()
    vi.mocked(api.getTool).mockRejectedValue(new Error('工具不存在。'))
    await open('/tools/missing')
    expect(wrapper.get('.model-feedback').text()).toContain('工具不存在')
    expect(wrapper.get('.form-back').attributes('href')).toBe('/tools')
  })
  it('环境不可用时明确展示原因，仍保留启停管理', async () => {
    vi.mocked(api.getTool).mockResolvedValue({ ...tool, available: false, unavailable_reason: '沙箱不可用' })
    await open('/tools/current_time')
    expect(wrapper.get('[role="alert"]').text()).toContain('沙箱不可用')
    expect(wrapper.find('[role="switch"]').exists()).toBe(true)
  })
})
