import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App.vue'
vi.mock('../src/api/workspace', () => ({ projects: async () => [] }))
import { createAppRouter } from '../src/router'
import * as api from '../src/api/chat'
import { useChatStore } from '../src/stores/chat'

vi.mock('../src/api/chat', () => ({ chatAgents: vi.fn(), conversations: vi.fn(), createConversation: vi.fn(), conversationDetail: vi.fn(), chooseAgent: vi.fn(), sendMessage: vi.fn(), regenerateReply: vi.fn(), stopGeneration: vi.fn(), subscribe: vi.fn(), updateConversation: vi.fn(), deleteConversation: vi.fn() }))
const stamp = '2026-09-12T01:00:00Z'
const summary: api.Conversation = { pinned: false, id: 'one', title: '新会话', agent_id: 'a', created_at: stamp, updated_at: stamp }
const user: api.ChatMessage = { id: 'u', conversation_id: 'one', sequence: 1, role: 'user', content: '你好', status: 'completed', created_at: stamp, agent_id: null, agent_name: null }
const reply: api.ChatMessage = { ...user, id: 'r', sequence: 2, role: 'assistant', content: '第一段', status: 'generating', agent_id: 'a', agent_name: '原助手' }
const generation: api.Generation = { id: 'g', conversation_id: 'one', status: 'generating', error: null, saved: true, message: null }
let snapshot: api.ConversationDetail
let wrapper: VueWrapper
let receive: (value: api.Generation) => void
let failed: () => void
let runtime: ((event: api.RuntimeEvent) => void) | undefined
let disconnect = vi.fn<() => void>()
// jsdom 尚未实现原生 dialog；这里只补齐开关状态，焦点隔离在浏览器验收。
HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
beforeEach(() => {
  vi.clearAllMocks()
  snapshot = { ...summary, messages: [], generation: null }
  vi.mocked(api.chatAgents).mockResolvedValue([{ id: 'a', name: '原助手', is_default: true }, { id: 'b', name: '新助手', is_default: false }])
  vi.mocked(api.conversations).mockResolvedValue([summary])
  vi.mocked(api.createConversation).mockResolvedValue({ ...summary, id: 'two' })
  vi.mocked(api.conversationDetail).mockImplementation(async id => structuredClone({ ...snapshot, id }))
  vi.mocked(api.sendMessage).mockImplementation(async () => { snapshot = { ...snapshot, messages: [user], generation }; return generation })
  vi.mocked(api.chooseAgent).mockImplementation(async (_, agentId) => ({ ...summary, agent_id: agentId }))
  vi.mocked(api.stopGeneration).mockResolvedValue({ ...generation, status: 'cancelled', error: '已停止生成', message: { ...reply, status: 'cancelled' } })
  vi.mocked(api.updateConversation).mockImplementation(async (id, data) => ({ ...summary, id, ...data }))
  vi.mocked(api.deleteConversation).mockResolvedValue(undefined)
  disconnect = vi.fn()
  vi.mocked(api.subscribe).mockImplementation((_id, _generation, cb, error, events) => { receive = cb; failed = error; runtime = events; return disconnect })
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (path: string) => new Response(JSON.stringify(path === '/api/health' ? { status: 'ok', database: 'connected', project: 'mini-agent' } : []))))
})
afterEach(() => { wrapper?.unmount(); vi.unstubAllGlobals(); document.body.innerHTML = '' })
async function open() {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/chat')
  wrapper = mount(App, { attachTo: document.body, global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return router
}
const button = (text: string) => wrapper.findAll('button').find(b => b.text() === text)!
async function send() { await wrapper.get('textarea').setValue('你好'); await wrapper.get('.chat-composer').trigger('submit'); await flushPromises() }

describe('聊天', () => {
  it('空会话展示问候，发送消息后隐藏且不作为聊天正文', async () => {
    await open()
    expect(wrapper.get('.chat-greeting').text()).toBe('我们要做些什么？')
    await send()
    expect(wrapper.find('.chat-greeting').exists()).toBe(false)
    expect(wrapper.findAll('.chat-message')).toHaveLength(1)
    expect(wrapper.get('.chat-message').text()).not.toContain('我们要做些什么？')
  })
  it('侧栏统一刷新会话列表，页面隐藏时暂停，恢复可见时更新', async () => {
    vi.useFakeTimers()
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
    try {
      await open()
      const calls = vi.mocked(api.conversations).mock.calls.length
      await vi.advanceTimersByTimeAsync(5000)
      expect(api.conversations).toHaveBeenCalledTimes(calls + 1)
      visibility.mockReturnValue('hidden')
      document.dispatchEvent(new Event('visibilitychange'))
      await vi.advanceTimersByTimeAsync(10000)
      expect(api.conversations).toHaveBeenCalledTimes(calls + 1)
      visibility.mockReturnValue('visible')
      document.dispatchEvent(new Event('visibilitychange'))
      await flushPromises()
      expect(api.conversations).toHaveBeenCalledTimes(calls + 2)
    } finally { visibility.mockRestore(); vi.useRealTimers() }
  })
  it('保存新会话后选中，恢复选择并把会话写入 URL', async () => {
    const router = await open()
    expect((wrapper.get('#chat-agent').element as HTMLSelectElement).value).toBe('a')
    expect(router.currentRoute.value.query.session).toBe('one')
    await wrapper.get('.new-conversation').trigger('click')
    await flushPromises()
    expect(api.createConversation).toHaveBeenCalledTimes(1)
    expect(router.currentRoute.value.query.session).toBe('two')
    expect(api.conversationDetail).toHaveBeenCalledWith('two')
  })
  it('反复新建返回已有空会话时去重列表并清空输入', async () => {
    await open()
    vi.mocked(api.createConversation).mockResolvedValue(summary)
    await wrapper.get('textarea').setValue('尚未发送的草稿')
    await wrapper.get('.new-conversation').trigger('click'); await flushPromises()
    await wrapper.get('.new-conversation').trigger('click'); await flushPromises()
    expect(wrapper.findAll('.conversation-row')).toHaveLength(1)
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('')
    expect(useChatStore().selected).toBe('one')
  })
  it('没有 Agent 时禁用发送并保留管理入口，删除的 Agent 要求重新选择', async () => {
    vi.mocked(api.chatAgents).mockResolvedValue([])
    await open()
    expect(button('发送').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.chat-setup a').attributes('href')).toBe('/agents')
    vi.mocked(api.chatAgents).mockResolvedValue([{ id: 'b', name: '新助手', is_default: true }])
    wrapper.unmount()
    await open()
    expect(wrapper.text()).toContain('原 Agent 已删除或不可用')
    await wrapper.get('#chat-agent').trigger('click'); await wrapper.get('#agent-option-b').trigger('click')
    expect(api.chooseAgent).toHaveBeenCalledWith('one', 'b')
  })
  it('空白、Shift Enter 和输入法组字不发送，普通 Enter 发送', async () => {
    await open()
    const input = wrapper.get('textarea')
    await input.setValue('   ')
    await input.trigger('keydown', { key: 'Enter' })
    await input.setValue('你好')
    await input.trigger('keydown', { key: 'Enter', shiftKey: true })
    await input.trigger('keydown', { key: 'Enter', isComposing: true })
    await input.trigger('compositionstart')
    await input.trigger('keydown', { key: 'Enter' })
    expect(api.sendMessage).not.toHaveBeenCalled()
    await input.trigger('compositionend')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(api.sendMessage).toHaveBeenCalledTimes(1)
    expect((input.element as HTMLTextAreaElement).value).toBe('')
    expect(wrapper.text()).toContain('正在思考')
    expect(wrapper.get('#chat-agent').attributes('disabled')).toBeDefined()
  })
  it('保存期间防重复，失败保留输入且重试使用相同请求标识', async () => {
    await open()
    let reject!: (reason: Error) => void
    vi.mocked(api.sendMessage).mockReturnValueOnce(new Promise((_resolve, fail) => { reject = fail }))
    await wrapper.get('textarea').setValue('你好')
    await wrapper.get('.chat-composer').trigger('submit')
    await wrapper.get('.chat-composer').trigger('submit')
    expect(api.sendMessage).toHaveBeenCalledTimes(1)
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('你好')
    reject(new Error('数据库暂不可用'))
    await flushPromises()
    expect(wrapper.text()).toContain('数据库暂不可用')
    expect(api.subscribe).not.toHaveBeenCalled()
    await wrapper.get('.chat-composer').trigger('submit')
    await flushPromises()
    expect(vi.mocked(api.sendMessage).mock.calls[0]![2]).toBe(vi.mocked(api.sendMessage).mock.calls[1]![2])
  })
  it('收到累积正文立即显示，重复快照不重复追加，完成后解锁', async () => {
    await open(); await send()
    receive({ ...generation, message: reply })
    await flushPromises()
    expect(wrapper.text()).toContain('正在生成')
    expect(wrapper.get('.assistant .chat-message-body').text()).toBe('第一段')
    receive({ ...generation, message: reply })
    receive({ ...generation, message: { ...reply, content: '第一段第二段' } })
    await flushPromises()
    expect(wrapper.findAll('.assistant')).toHaveLength(1)
    expect(wrapper.get('.assistant .chat-message-body').text()).toBe('第一段第二段')
    receive({ ...generation, status: 'completed', message: { ...reply, content: '第一段第二段', status: 'completed' } })
    await flushPromises()
    expect(wrapper.find('.chat-generation-state').exists()).toBe(false)
    expect(wrapper.get('#chat-agent').attributes('disabled')).toBeUndefined()
    expect(disconnect).toHaveBeenCalled()
  })
  it('停止立即断开订阅，保留部分正文并标记未完成', async () => {
    await open(); await send()
    receive({ ...generation, message: reply }); await flushPromises()
    await button('停止生成').trigger('click'); await flushPromises()
    expect(disconnect).toHaveBeenCalled()
    expect(api.stopGeneration).toHaveBeenCalledWith('one', 'g')
    expect(wrapper.text()).toContain('已停止 · 未完成')
    expect(wrapper.get('#chat-agent').attributes('disabled')).toBeUndefined()
  })
  it('刷新加载未完成状态，保存失败显示未保存正文和独立提示', async () => {
    snapshot = { ...snapshot, messages: [user, reply], generation: { ...generation, status: 'failed', saved: false, error: '回复保存失败，内容尚未可靠保存，请复制保留。', message: { ...reply, content: '尚未保存的完整正文', status: 'failed' } } }
    await open()
    expect(wrapper.text()).toContain('尚未保存的完整正文')
    expect(wrapper.text()).toContain('回复保存失败')
    expect(wrapper.text()).toContain('未完成')
    expect(wrapper.text()).not.toContain('回复已保存')
  })
  it('离开聊天只断开订阅，返回后读取后台完成结果', async () => {
    const router = await open(); await send()
    await router.push('/runs'); await flushPromises()
    expect(disconnect).toHaveBeenCalled()
    expect(api.stopGeneration).not.toHaveBeenCalled()
    const completed = { ...reply, status: 'completed' as const }
    snapshot.generation = { ...generation, status: 'completed', message: completed }
    snapshot.messages = [user, completed]
    await router.push('/chat'); await flushPromises()
    expect(wrapper.text()).toContain('第一段')
    expect(wrapper.find('.chat-generation-state').exists()).toBe(false)
  })
  it('页面关闭不取消后台运行，运行事件去重且不覆盖跨轮正文', async () => {
    await open(); await send()
    const event: api.RuntimeEvent = { run_id: 'run', sequence: 3, type: 'tool_start', round: 1, call_id: 'call', data: { tool_kind: 'skill', tool_name: 'load_skill' } }
    runtime?.(event); runtime?.(event)
    expect(useChatStore().runtimeEvents.one).toHaveLength(1)
    receive({ ...generation, message: { ...reply, content: '工具前文' } })
    runtime?.({ ...event, sequence: 4, type: 'tool_result', data: { status: 'completed' } })
    runtime?.({ ...event, sequence: 5, type: 'compression_success', call_id: null, round: null, data: { trigger_reason: 'estimated_threshold', estimated_tokens_before: 6400, estimated_tokens_after: 2800, processed_message_count: 6, retained_message_count: 4, duration_ms: 120, estimation: true } })
    receive({ ...generation, message: { ...reply, content: '工具前文工具后文' } })
    await flushPromises()
    expect(wrapper.get('.chat-message.assistant').text()).toContain('工具前文工具后文')
    expect(wrapper.get('.chat-context-details').text()).toContain('压缩成功')
    expect(wrapper.get('.chat-context-details').text()).toContain('约 6,400 Token → 约 2,800 Token')
    expect(wrapper.get('.chat-context-details').text()).toContain('处理 6 条消息 · 实际保留 4 条')
    window.dispatchEvent(new Event('pagehide'))
    expect(api.stopGeneration).not.toHaveBeenCalled()
  })
  it('发送尚未返回就离开页面，返回生成标识后仍在后台运行且不创建订阅', async () => {
    const router = await open()
    let complete: (value: api.Generation) => void = () => {}
    vi.mocked(api.sendMessage).mockImplementation(() => new Promise(resolve => { complete = resolve }))
    await wrapper.get('textarea').setValue('你好')
    await wrapper.get('.chat-composer').trigger('submit')
    await router.push('/runs'); await flushPromises()
    complete(generation); await flushPromises()
    expect(api.stopGeneration).not.toHaveBeenCalled()
    expect(api.subscribe).not.toHaveBeenCalled()
  })
  it('达到轮数上限保留未完成正文，允许继续发送', async () => {
    await open(); await send()
    receive({ ...generation, status: 'limit_reached', error: '已达到 Agent 最大执行轮数，任务未完成。', message: { ...reply, status: 'failed' } })
    await flushPromises()
    expect(wrapper.text()).toContain('最大执行轮数')
    expect(wrapper.text()).toContain('未完成')
    expect(wrapper.text()).not.toContain('回复已保存')
    expect(wrapper.get('textarea').attributes('disabled')).toBeUndefined()
  })
  it('断线提示可重载恢复，错误信息不变成聊天正文', async () => {
    await open(); await send()
    failed(); await flushPromises()
    expect(wrapper.get('.chat-error').text()).toContain('进度连接中断')
    expect(wrapper.findAll('.chat-message')).toHaveLength(1)
    await button('重新加载').trigger('click'); await flushPromises()
    expect(api.subscribe).toHaveBeenCalledTimes(2)
  })
})

describe('会话管理与输入体验', () => {
  it('会话操作弹窗支持取消并恢复焦点', async () => {
    await open()
    await wrapper.get('#conversation-actions-one').trigger('click'); await flushPromises(); await document.querySelector<HTMLButtonElement>('#conversation-menu-one button')!.click(); await flushPromises()
    expect(wrapper.get('.workspace-manager').attributes('open')).toBeDefined()
    await button('取消').trigger('click'); await flushPromises()
    expect(document.activeElement?.id).toBe('conversation-actions-one')
  })
  it('保存置顶与名称，失败保留输入', async () => {
    await open()
    await wrapper.get('#conversation-actions-one').trigger('click'); await flushPromises(); await document.querySelector<HTMLButtonElement>('#conversation-menu-one button')!.click(); await flushPromises()
    await wrapper.get('#conversation-title-one').setValue('我的计划')
    await wrapper.get('.workspace-manager input[type="checkbox"]').setValue(true)
    vi.mocked(api.updateConversation).mockRejectedValueOnce(new Error('数据库暂不可用'))
    await wrapper.get('.workspace-manager form').trigger('submit'); await flushPromises()
    expect(wrapper.text()).toContain('数据库暂不可用')
    expect((wrapper.get('#conversation-title-one').element as HTMLInputElement).value).toBe('我的计划')
    await wrapper.get('.workspace-manager form').trigger('submit'); await flushPromises()
    expect(api.updateConversation).toHaveBeenLastCalledWith('one', {title:'我的计划',pinned:true,project_id:null})
    expect(wrapper.get('.conversation-title').text()).toContain('我的计划')
  })
  it('删除需要确认，失败保留记录，删除后清理 URL', async () => {
    const router = await open()
    await wrapper.get('#conversation-actions-one').trigger('click'); await flushPromises(); await document.querySelector<HTMLButtonElement>('#conversation-menu-one button')!.click(); await flushPromises()
    await button('删除').trigger('click')
    expect(wrapper.text()).toContain('无法恢复')
    expect(api.deleteConversation).not.toHaveBeenCalled()
    vi.mocked(api.deleteConversation).mockRejectedValueOnce(new Error('请先停止'))
    await button('确认删除').trigger('click'); await flushPromises()
    expect(wrapper.findAll('.conversation-row')).toHaveLength(1)
    await button('确认删除').trigger('click'); await flushPromises()
    expect(wrapper.findAll('.conversation-row')).toHaveLength(0)
    expect(router.currentRoute.value.query.session).toBeUndefined()
  })
  it('主侧栏包含历史列表，移除二级会话栏，分区独立折叠', async () => {
    await open()
    expect(wrapper.find('.chat-layout .conversation-panel').exists()).toBe(false)
    expect(wrapper.get('.sidebar .conversation-row').isVisible()).toBe(true)
    await wrapper.get('[aria-controls="project-list"]').trigger('click')
    expect(wrapper.find('#project-list').exists()).toBe(false)
    expect(wrapper.get('#history-list').isVisible()).toBe(true)
    await wrapper.get('[aria-controls="history-list"]').trigger('click')
    expect(wrapper.find('#history-list').exists()).toBe(false)
  })
  it('输入框使用静态提示，不会覆盖正在输入的内容', async () => {
    await open()
    expect(wrapper.get('textarea').attributes('placeholder')).toBe('描述你想完成的任务，或添加本地文件…')
    await wrapper.get('textarea').setValue('我的问题')
    await flushPromises()
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('我的问题')
  })
})

describe('聊天开始引导', () => {
  it('搜索仅筛选会话标题，清除后恢复会话且保留当前草稿', async () => {
    await open()
    await wrapper.get('textarea').setValue('保留我的草稿')
    await wrapper.get('input[type="search"]').setValue('找不到')
    expect(wrapper.findAll('.conversation-row')).toHaveLength(0)
    expect(wrapper.text()).toContain('没有匹配的对话')
    await wrapper.get('input[type="search"]').setValue('')
    expect(wrapper.findAll('.conversation-row')).toHaveLength(1)
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('保留我的草稿')
  })
  it('任务示例追加至草稿、恢复输入焦点且不发送', async () => {
    await open()
    await wrapper.get('textarea').setValue('已有内容')
    await button('打磨一段文字').trigger('click')
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toContain('已有内容\n\n帮我打磨')
    expect(document.activeElement?.id).toBe('chat-input')
    expect(api.sendMessage).not.toHaveBeenCalled()
  })
  it('已配置 Agent 且没有会话时自动准备空会话', async () => {
    vi.mocked(api.conversations).mockResolvedValue([])
    await open()
    expect(api.createConversation).toHaveBeenCalledTimes(1)
    expect(useChatStore().selected).toBe('two')
    expect(wrapper.get('textarea').attributes('disabled')).toBeUndefined()
  })
})

describe('导入草稿与会话隔离', () => {
  it('添加内容菜单提供能力入口并支持 Escape', async () => {
    await open()
    const plus = wrapper.get('.composer-plus')
    await plus.trigger('click')
    expect(wrapper.get('[role="menu"]')).toBeTruthy()
    expect(document.activeElement?.textContent).toContain('从电脑添加文件')
    expect(wrapper.get('[role="menu"]').text()).toContain('任务技能')
    expect(wrapper.get('[role="menu"]').text()).toContain('连接外部工具')
    expect(button('能力')).toBeUndefined()
    await wrapper.get('[role="menu"]').trigger('keydown', { key: 'Escape' })
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)
    expect(document.activeElement).toBe(plus.element)
  })
  it('文本附件显示为 Chip，正文与附件分开提交', async () => {
    await open()
    await wrapper.get('textarea').setValue('已有草稿')
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [{ name: '笔记.md', size: 6, arrayBuffer: async () => new TextEncoder().encode('材料').buffer }] })
    await input.trigger('change'); await flushPromises()
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('已有草稿')
    expect(wrapper.get('.attachment-chip').text()).toContain('笔记.md')
    expect(wrapper.get('.attachment-chip').text()).toContain('6 B')
    expect(wrapper.text()).not.toContain('文件：笔记.md')
    expect(api.sendMessage).not.toHaveBeenCalled()
    await wrapper.get('.chat-composer').trigger('submit'); await flushPromises()
    expect(api.sendMessage).toHaveBeenCalledWith('one', '已有草稿', expect.any(String), [{ name: '笔记.md', mime_type: 'text/markdown', data: '5p2Q5paZ' }])
  })
  it('读取期间切换会话，结果不能写入另一会话', async () => {
    await open()
    let finish!: (value: ArrayBuffer) => void
    const pendingFile = new Promise<ArrayBuffer>(resolve => { finish = resolve })
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [{ name: '笔记.md', size: 6, arrayBuffer: () => pendingFile }] })
    await input.trigger('change')
    await wrapper.get('.new-conversation').trigger('click'); await flushPromises()
    await wrapper.get('textarea').setValue('新会话草稿')
    finish(new TextEncoder().encode('旧材料').buffer)
    await flushPromises()
    expect(useChatStore().selected).toBe('two')
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('新会话草稿')
    expect(wrapper.text()).not.toContain('文本加入草稿')
  })
})

describe('首页批注与多模态输入', () => {
  it('首页只保留任务问候，重复说明与顶部附件入口已移除', async () => {
    await open()
    const welcome = wrapper.get('.chat-welcome').element
    expect(welcome.children[0]?.classList.contains('chat-greeting')).toBe(true)
    expect(welcome.children).toHaveLength(1)
    expect(wrapper.text()).not.toContain('你的本地 Agent 工作台')
    expect(wrapper.find('.workbench-local').exists()).toBe(false)
    expect(wrapper.find('.workbench-shortcuts').exists()).toBe(false)
    expect(wrapper.find('.workbench-storage-note').exists()).toBe(false)
    expect(wrapper.find('.chat-keyboard-hint').exists()).toBe(false)
    expect(wrapper.find('.chat-agent-picker > .app-icon').exists()).toBe(true)
  })
  it('仅图片也能发送，失败保留附件 Chip', async () => {
    await open()
    const file = new File([new Uint8Array([137, 80, 78, 71])], 'image.png', { type: 'image/png' })
    Object.defineProperty(file, 'arrayBuffer', { value: async () => new Uint8Array([137, 80, 78, 71]).buffer })
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change'); await flushPromises()
    expect(wrapper.find('.attachment-thumbnail').exists()).toBe(true)
    expect(wrapper.get('.chat-send').attributes('disabled')).toBeUndefined()
    vi.mocked(api.sendMessage).mockRejectedValue(new Error('模型不支持图片'))
    await wrapper.get('.chat-composer').trigger('submit'); await flushPromises()
    expect(wrapper.find('.attachment-chip').exists()).toBe(true)
    expect(api.sendMessage).toHaveBeenCalledWith('one', '', expect.any(String), [{ name: 'image.png', mime_type: 'image/png', data: 'iVBORw==' }])
  })
  it('已完成回复提供复制和重新生成，保留当前草稿', async () => {
    const completed = { ...reply, status: 'completed' as const }
    snapshot = { ...snapshot, messages: [user, completed], generation: { ...generation, status: 'completed', message: completed } }
    await open()
    await wrapper.get('textarea').setValue('下一问草稿')
    vi.mocked(api.regenerateReply).mockResolvedValue({ ...generation, id: 'new-run' })
    await button('重新生成').trigger('click'); await flushPromises()
    expect(api.regenerateReply).toHaveBeenCalledWith('one', 'g', expect.any(String))
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('下一问草稿')
    expect(wrapper.get('.chat-message-actions').text()).toContain('复制')
  })
})
