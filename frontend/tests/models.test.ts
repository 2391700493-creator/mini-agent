import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App.vue'
vi.mock('../src/api/chat', async importOriginal => ({ ...await importOriginal<typeof import('../src/api/chat')>(), conversations: async () => [] }))
vi.mock('../src/api/workspace', () => ({ projects: async () => [] }))
import { createAppRouter } from '../src/router'
import * as api from '../src/api/models'
import { ApiError } from '../src/api/client'

vi.mock('../src/api/models', () => ({
  listModels: vi.fn(), getModel: vi.fn(), saveModel: vi.fn(),
  setDefaultModel: vi.fn(), deleteModel: vi.fn(), testModel: vi.fn(),
}))
const model: api.LanguageModel = {
  id: 'one', display_name: '日常模型', model_id: 'test-model', base_url: 'https://example.com/v1',
  context_length: 8192, max_output_tokens: 512, temperature: 1, input_price: null,
  output_price: 0, cached_input_price: 0.5, is_default: true, key_configured: true,
  updated_at: '2026-09-11T08:00:00Z',
}
let wrapper: VueWrapper
HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.listModels).mockResolvedValue([])
  vi.mocked(api.getModel).mockResolvedValue(model)
  vi.mocked(api.saveModel).mockResolvedValue(model)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ok', database: 'connected', project: 'mini-agent' }))))
})
afterEach(() => { wrapper?.unmount(); document.body.innerHTML = ''; vi.unstubAllGlobals() })
async function open(path = '/models') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  wrapper = mount(App, { attachTo: document.body, global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return router
}
function button(label: string) { return wrapper.findAll('button').find(item => item.text() === label)! }
async function fillRequired() {
  for (const [field, value] of Object.entries({ display_name: '我的模型', model_id: 'provider-model', base_url: 'https://example.com/v1', api_key: 'new-key', context_length: '8192', max_output_tokens: '512' })) {
    await wrapper.get(`#${field}`).setValue(value)
  }
}
describe('模型管理交互', () => {
  it('未保存修改可取消离开并拦截刷新，还原字段后不再提示', async () => {
    const router = await open('/models/new')
    const original = (wrapper.get('#display_name').element as HTMLInputElement).value
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await wrapper.get('#display_name').setValue('未保存的修改')
    await router.push('/models')
    expect(router.currentRoute.value.path).toBe('/models/new')
    expect(confirm).toHaveBeenCalledTimes(1)
    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
    await wrapper.get('#display_name').setValue(original)
    await router.push('/models')
    expect(router.currentRoute.value.path).toBe('/models')
    expect(confirm).toHaveBeenCalledTimes(1)
    confirm.mockRestore()
  })

  it('空状态提供添加入口，真实数据为空时不展示示例模型', async () => {
    await open()
    expect(wrapper.text()).toContain('添加第一个模型')
    expect(wrapper.findAll('.model-card')).toHaveLength(0)
  })
  it('新增使用默认限制且高级设置折叠，校验定位到字段', async () => {
    await open('/models/new')
    expect((wrapper.get('#context_length').element as HTMLInputElement).value).toBe('8192')
    expect(wrapper.findAll('details').every(item => !item.attributes('open'))).toBe(true)
    expect((wrapper.get('#input_price').element as HTMLInputElement).value).toBe('')
    expect(wrapper.text()).toContain('建议值 1')
    await wrapper.get('form').trigger('submit')
    expect(api.saveModel).not.toHaveBeenCalled()
    expect(wrapper.get('#api_key-error').text()).toContain('API Key')
    expect(document.activeElement?.id).toBe('base_url')
    await fillRequired()
    await wrapper.get('#max_output_tokens').setValue('9000')
    await wrapper.get('#input_price').setValue('-1')
    await wrapper.get('#base_url').setValue('https://example.com/v1/chat/completions')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('#max_output_tokens-error').text()).toContain('不得超过')
    expect(wrapper.get('#input_price-error').text()).toContain('不得为负数')
    expect(wrapper.get('#base_url-error').text()).toContain('移除')
    expect(api.saveModel).not.toHaveBeenCalled()
  })
  it('最少字段可测试连接，重试更新原配置且不重复新增', async () => {
    const router = await open('/models/new')
    vi.mocked(api.testModel).mockResolvedValue({ success: true, code: 'ok', message: '', suggestion: '', reply: 'ok' })
    for (const [field, value] of Object.entries({ model_id: 'my-model', base_url: 'https://example.com/v1', api_key: 'test-key' })) await wrapper.get(`#${field}`).setValue(value)
    await button('测试连接').trigger('click')
    await flushPromises()
    expect(api.saveModel).toHaveBeenLastCalledWith(expect.objectContaining({ display_name: 'my-model', context_length: 8192, max_output_tokens: 2048 }), undefined)
    expect(api.testModel).toHaveBeenCalledWith('one')
    expect(router.currentRoute.value.path).toBe('/models/new')
    expect(wrapper.text()).toContain('连接成功，配置已保存')
    await button('测试连接').trigger('click')
    await flushPromises()
    expect(api.saveModel).toHaveBeenLastCalledWith(expect.not.objectContaining({ api_key: expect.anything() }), 'one')
  })
  it('保存区分未知价格与零价格，并阻止重复提交', async () => {
    const router = await open('/models/new')
    await fillRequired()
    await wrapper.get('#output_price').setValue('0')
    let finish!: (m: api.LanguageModel) => void
    vi.mocked(api.saveModel).mockReturnValue(new Promise(resolve => { finish = resolve }))
    await wrapper.get('form').trigger('submit')
    await wrapper.get('form').trigger('submit')
    expect(api.saveModel).toHaveBeenCalledTimes(1)
    expect(api.saveModel).toHaveBeenCalledWith(expect.objectContaining({ input_price: null, output_price: 0, api_key: 'new-key' }), undefined)
    expect(button('正在保存…').attributes('disabled')).toBeDefined()
    finish(model)
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/models')
    expect(localStorage.length).toBe(0)
  })
  it('编辑时密钥为空，留空保存不提交 api_key，替换时提交新值', async () => {
    await open('/models/one/edit')
    expect((wrapper.get('#api_key').element as HTMLInputElement).value).toBe('')
    expect(wrapper.text()).toContain('已配置，留空则保留原密钥')
    await wrapper.get('#display_name').setValue('改名')
    await wrapper.get('form').trigger('submit')
    expect(api.saveModel).toHaveBeenCalledWith(expect.objectContaining({ display_name: '改名' }), 'one')
    expect(vi.mocked(api.saveModel).mock.calls[0]![0]).not.toHaveProperty('api_key')
    await flushPromises()
    wrapper.unmount()
    await open('/models/one/edit')
    await wrapper.get('#api_key').setValue('replacement-key')
    await wrapper.get('form').trigger('submit')
    expect(api.saveModel).toHaveBeenLastCalledWith(expect.objectContaining({ api_key: 'replacement-key' }), 'one')
  })
  it('后端字段校验显示在对应输入框旁', async () => {
    await open('/models/new')
    await fillRequired()
    vi.mocked(api.saveModel).mockRejectedValueOnce(new ApiError('请检查标记的字段。', 422, { model_id: '模型标识过长' }))
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('#model_id-error').text()).toBe('模型标识过长')
    expect(document.activeElement?.id).toBe('model_id')
  })
  it('列表展示字段，测试时禁止重复请求，成功展示实际回复', async () => {
    vi.mocked(api.listModels).mockResolvedValue([model])
    await open()
    expect(wrapper.text()).toContain(model.base_url)
    expect(wrapper.text()).toContain('8,192')
    expect(wrapper.text()).toContain('已配置')
    let finish!: (r: api.ConnectionResult) => void
    vi.mocked(api.testModel).mockReturnValue(new Promise(resolve => { finish = resolve }))
    await button('测试连接').trigger('click')
    expect(button('正在测试').attributes('disabled')).toBeDefined()
    await button('正在测试').trigger('click')
    expect(api.testModel).toHaveBeenCalledTimes(1)
    finish({ success: true, code: 'connected', message: '模型已连接', suggestion: '', reply: '这是实际响应' })
    await flushPromises()
    expect(wrapper.get('blockquote').text()).toBe('这是实际响应')
  })
  it('测试失败展示原因和建议，允许再次测试', async () => {
    vi.mocked(api.listModels).mockResolvedValue([model])
    vi.mocked(api.testModel).mockResolvedValue({ success: false, code: 'invalid_key', message: '密钥验证失败', suggestion: '检查密钥是否过期', reply: null })
    await open()
    await button('测试连接').trigger('click')
    await flushPromises()
    expect(wrapper.get('.model-test-result').text()).toContain('检查密钥是否过期')
    expect(button('测试连接').attributes('disabled')).toBeUndefined()
  })
  it('删除默认模型必须先选择替代项，取消不会请求后端', async () => {
    vi.mocked(api.listModels).mockResolvedValue([model, { ...model, id: 'two', is_default: false, display_name: '备选' }])
    await open()
    await wrapper.get('#delete-one').trigger('click')
    expect((wrapper.get('#delete-confirmation').element as HTMLDialogElement).open).toBe(true)
    expect(button('确认删除').attributes('disabled')).toBeDefined()
    await button('取消').trigger('click')
    expect(api.deleteModel).not.toHaveBeenCalled()
    expect(document.activeElement?.id).toBe('delete-one')
    expect((wrapper.get('#delete-confirmation').element as HTMLDialogElement).open).toBe(false)
    await wrapper.get('#delete-one').trigger('click')
    await wrapper.get('#replacement').setValue('two')
    vi.mocked(api.listModels).mockResolvedValue([{ ...model, id: 'two' }])
    await button('确认删除').trigger('click')
    await flushPromises()
    expect(api.deleteModel).toHaveBeenCalledWith('one', 'two')
    expect(wrapper.findAll('.default-tag')).toHaveLength(1)
  })
  it('删除最后一个模型后回到空状态', async () => {
    vi.mocked(api.listModels).mockResolvedValueOnce([model]).mockResolvedValue([])
    await open()
    await wrapper.get('#delete-one').trigger('click')
    expect(wrapper.text()).toContain('这是最后一个模型')
    await button('确认删除').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('添加第一个模型')
  })
  it('模型删除失败保留弹窗，Escape 取消恢复焦点', async () => {
    vi.mocked(api.listModels).mockResolvedValue([model])
    vi.mocked(api.deleteModel).mockRejectedValueOnce(new Error('模型仍被 Agent 使用'))
    await open()
    await wrapper.get('#delete-one').trigger('click')
    await button('确认删除').trigger('click'); await flushPromises()
    expect((wrapper.get('#delete-confirmation').element as HTMLDialogElement).open).toBe(true)
    expect(wrapper.get('#delete-confirmation [role="alert"]').text()).toContain('仍被 Agent 使用')
    expect(wrapper.findAll('.model-card')).toHaveLength(1)
    await wrapper.get('#delete-confirmation').trigger('cancel')
    expect(document.activeElement?.id).toBe('delete-one')
  })
  it('本地服务离线时可重新加载列表', async () => {
    vi.mocked(api.listModels).mockRejectedValueOnce(new Error('确认后端已启动')).mockResolvedValue([])
    await open()
    expect(wrapper.get('.model-feedback').text()).toContain('确认后端已启动')
    await button('重新加载').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('添加第一个模型')
  })
})
