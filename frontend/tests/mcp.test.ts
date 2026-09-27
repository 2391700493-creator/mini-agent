import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App.vue'
vi.mock('../src/api/chat', async importOriginal => ({ ...await importOriginal<typeof import('../src/api/chat')>(), conversations: async () => [] }))
vi.mock('../src/api/workspace', () => ({ projects: async () => [] }))
import { createAppRouter } from '../src/router'
import * as api from '../src/api/mcp'

vi.mock('../src/api/mcp', () => ({ listMcp: vi.fn(), getMcp: vi.fn(), deleteMcp: vi.fn(), toggleMcp: vi.fn(), testMcp: vi.fn(), importMcpJson: vi.fn(), updateMcpJson: vi.fn() }))
HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
const server: api.McpServer = { id: 'one', name: '本机工具', description: '读取文件', command: 'node', args: ['server.js', '--stdio'], env: { TOKEN: '••••••••' }, enabled: false, testing: false, status: 'untested', message: '未测试', diagnostic: null, tested_at: null, last_success_at: null, tool_count: null, tools: [] }
let wrapper: VueWrapper
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.listMcp).mockResolvedValue([{ ...server }])
  vi.mocked(api.getMcp).mockResolvedValue({ ...server })
  vi.mocked(api.importMcpJson).mockResolvedValue({ ...server })
  vi.mocked(api.updateMcpJson).mockResolvedValue({ ...server })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ok', database: 'connected', project: 'mini-agent' }))))
})
afterEach(() => { wrapper?.unmount(); document.body.innerHTML = ''; vi.unstubAllGlobals() })
async function open(path = '/mcp') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  wrapper = mount(App, { attachTo: document.body, global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return router
}
function button(text: string) { return wrapper.findAll('button').find(item => item.text() === text)! }

describe('MCP 管理', () => {
  it('初始状态明确显示未测试、未知和停用', async () => {
    await open()
    expect(wrapper.get('.mcp-card').text()).toContain('未测试')
    expect(wrapper.get('.mcp-card').text()).toContain('未知')
    expect(wrapper.get('[role="switch"]').attributes('aria-checked')).toBe('false')
    expect(wrapper.get('.mcp-card').text()).toContain('server.js')
  })
  it('停用时可以测试，防止重复提交并显示工具参数', async () => {
    let finish!: (result: api.McpServer) => void
    vi.mocked(api.testMcp).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    await open()
    await button('测试连接').trigger('click')
    expect(button('正在测试…').attributes('disabled')).toBeDefined()
    await button('正在测试…').trigger('click')
    expect(api.testMcp).toHaveBeenCalledTimes(1)
    finish({ ...server, status: 'success', message: '连接成功，发现 1 个工具', tool_count: 1, tools: [{ name: 'read_file', description: '读取内容', input_schema: { type: 'object', properties: { path: { type: 'string', description: '文件路径' } }, required: ['path'] } }] })
    await flushPromises()
    expect(wrapper.text()).toContain('读取内容')
    expect(wrapper.text()).toContain('string · 必填')
    expect(wrapper.text()).toContain('文件路径')
    expect(wrapper.get('[role="switch"]').attributes('aria-checked')).toBe('false')
  })
  it('显示历史工具和配置变更提醒，不误报成功', async () => {
    vi.mocked(api.listMcp).mockResolvedValue([{ ...server, status: 'stale', message: '配置已变更，待重新测试', tool_count: 1, tools: [{ name: 'old', description: '历史说明', input_schema: { type: 'object' } }] }])
    await open()
    expect(wrapper.text()).toContain('配置已变更，待重新测试')
    expect(wrapper.text()).toContain('以下为历史发现结果')
  })
  it('删除需确认，取消恢复焦点，确认后更新列表', async () => {
    await open()
    await button('删除').trigger('click')
    await flushPromises()
    expect(api.deleteMcp).not.toHaveBeenCalled()
    expect(wrapper.get('dialog').element.tagName).toBe('DIALOG')
    await button('取消').trigger('click')
    expect(document.activeElement?.id).toBe('delete-one')
    await button('删除').trigger('click')
    await button('确认删除').trigger('click')
    await flushPromises()
    expect(api.deleteMcp).toHaveBeenCalledWith('one')
    expect(wrapper.find('.mcp-card').exists()).toBe(false)
  })
  it('启用仅更新启用状态，不发起测试', async () => {
    vi.mocked(api.toggleMcp).mockResolvedValue({ ...server, enabled: true })
    await open()
    await wrapper.get('[role="switch"]').trigger('click')
    await flushPromises()
    expect(api.toggleMcp).toHaveBeenCalledWith('one', true)
    expect(api.testMcp).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('未测试')
  })
  it('后端失败时显示错误并可重新加载', async () => {
    vi.mocked(api.listMcp).mockRejectedValueOnce(new Error('本地服务离线'))
    await open()
    expect(wrapper.get('.model-feedback').text()).toContain('本地服务离线')
    await button('重新加载').trigger('click')
    await flushPromises()
    expect(wrapper.find('.mcp-card').exists()).toBe(true)
  })
  it('编辑页预填单个 JSON，使用 null 保留环境变量', async () => {
    const router = await open('/mcp/one/edit')
    const editor = wrapper.get('#mcp-json')
    const parsed = JSON.parse((editor.element as HTMLTextAreaElement).value)
    expect(parsed.mcpServers['本机工具']).toEqual({ command: 'node', args: ['server.js', '--stdio'], description: '读取文件', env: { TOKEN: null } })
    expect((editor.element as HTMLTextAreaElement).value).not.toContain('••••••••')
    const changed = JSON.stringify({ mcpServers: { 新名称: { command: 'node', args: ['next.js'], env: { TOKEN: null } } } })
    await editor.setValue(changed)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(api.updateMcpJson).toHaveBeenCalledWith('one', changed)
    expect(router.currentRoute.value.path).toBe('/mcp')
  })
  it('新增页直接导入 JSON 并返回列表', async () => {
    const router = await open('/mcp/new')
    const configuration = JSON.stringify({ mcpServers: { 测试: { command: 'node', args: ['server.js'], env: {} } } })
    await wrapper.get('#mcp-json').setValue(configuration)
    await button('导入配置').trigger('click')
    await flushPromises()
    expect(api.importMcpJson).toHaveBeenCalledWith(configuration)
    expect(router.currentRoute.value.path).toBe('/mcp')
  })
  it('导入失败保留 JSON 并显示原因', async () => {
    vi.mocked(api.importMcpJson).mockRejectedValueOnce(new Error('JSON 配置无法解析。'))
    await open('/mcp/new')
    await wrapper.get('#mcp-json').setValue('{bad json')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('.model-feedback').text()).toContain('JSON 配置无法解析')
    expect((wrapper.get('#mcp-json').element as HTMLTextAreaElement).value).toBe('{bad json')
  })
})
