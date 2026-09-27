import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App.vue'
vi.mock('../src/api/chat', async importOriginal => ({ ...await importOriginal<typeof import('../src/api/chat')>(), conversations: async () => [] }))
vi.mock('../src/api/workspace', () => ({ projects: async () => [] }))
import { createAppRouter } from '../src/router'
import * as api from '../src/api/runs'

vi.mock('../src/api/runs', () => ({ listRuns: vi.fn(), runDetail: vi.fn(), eventPayload: vi.fn(), removeRun: vi.fn() }))
HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
const stamp = '2026-09-13T10:00:00Z'
const summary: api.RunSummary = {
  id: 'run-one', conversation_id: 'conversation', status: 'failed', agent_id: 'agent', agent_name: '研究助手',
  model_id: 'model', model_name: '本地模型', model_identifier: 'model-v1', started_at: stamp, ended_at: '2026-09-13T10:00:01Z', duration_ms: 1250,
  model_call_count: 2, tool_call_count: 1, input_tokens: 120, output_tokens: 20, total_tokens: 140, cached_input_tokens: 30,
  usage_status: 'incomplete', first_output_ms: 180, end_reason: '模型连接失败。', error_summary: '模型连接失败。',
}
const detail: api.RunDetail = {
  ...summary, final_answer: '已经生成的未完成内容。', events: [
    { run_id: 'run-one', sequence: 1, type: 'run_start', round: null, call_id: null, occurred_at: stamp, data: {}, has_payload: false },
    { run_id: 'run-one', sequence: 2, type: 'model_start', round: 1, call_id: 'model-call', occurred_at: stamp, data: { model_name: '本地模型', purpose: 'agent_loop' }, has_payload: false },
    { run_id: 'run-one', sequence: 3, type: 'model_end', round: 1, call_id: 'model-call', occurred_at: stamp, data: { status: 'failed', duration_ms: 900, failure_reason: '模型连接失败。', usage: null }, has_payload: false },
    { run_id: 'run-one', sequence: 4, type: 'tool_start', round: 1, call_id: 'tool-call', occurred_at: stamp, data: { display_name: '文件', server_name: null, input_summary: '{"path":"notes.txt"}' }, has_payload: true },
    { run_id: 'run-one', sequence: 5, type: 'tool_result', round: 1, call_id: 'tool-call', occurred_at: stamp, data: { status: 'failed', duration_ms: 20, summary: '文件不存在。', executed: true }, has_payload: true },
    { run_id: 'run-one', sequence: 6, type: 'text_delta', round: 1, call_id: 'model-call', occurred_at: stamp, data: { content_length: 10, has_visible_content: true }, has_payload: false },
    { run_id: 'run-one', sequence: 7, type: 'run_error', round: null, call_id: null, occurred_at: stamp, data: { reason: '模型连接失败。' }, has_payload: false },
    { run_id: 'run-one', sequence: 8, type: 'run_end', round: null, call_id: null, occurred_at: stamp, data: { status: 'failed', reason: '模型连接失败。' }, has_payload: false },
  ],
}
let wrapper: VueWrapper
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.listRuns).mockResolvedValue({ items: [summary], total: 1, page: 1, page_size: 20, agents: [{ id: 'agent', name: '研究助手' }] })
  vi.mocked(api.runDetail).mockResolvedValue(detail)
  vi.mocked(api.eventPayload).mockImplementation(async (_id, sequence) => ({ run_id: 'run-one', sequence, payload: sequence === 4 ? { input: { value: { path: 'notes.txt' } } } : { result: { value: { success: false } } } }))
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ok', database: 'connected', project: 'mini-agent' }))))
})
afterEach(() => { wrapper?.unmount(); vi.unstubAllGlobals(); document.body.innerHTML = '' })
async function open(path: string) {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  wrapper = mount(App, { attachTo: document.body, global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return router
}

describe('运行记录', () => {
  it('删除须弹窗确认，取消不调用 API，失败可重试', async () => {
    await open('/runs/run-one')
    const trigger = wrapper.findAll('button').find(item => item.text() === '删除记录')!
    ;(trigger.element as HTMLElement).focus()
    await trigger.trigger('click'); await flushPromises()
    const dialog = wrapper.get('dialog[aria-label="删除这条运行记录？"]')
    const cancel = () => dialog.findAll('button').find(item => item.text() === '取消')!
    expect(dialog.attributes('open')).toBeDefined()
    await cancel().trigger('click'); await flushPromises()
    expect(api.removeRun).not.toHaveBeenCalled()
    expect(document.activeElement).toBe(trigger.element)
    vi.mocked(api.removeRun).mockRejectedValueOnce(new Error('删除失败'))
    await trigger.trigger('click'); await flushPromises()
    await dialog.findAll('button').find(item => item.text() === '确认删除')!.trigger('click'); await flushPromises()
    expect(dialog.attributes('open')).toBeDefined()
    expect(dialog.get('[role="alert"]').text()).toBe('删除失败')
    vi.mocked(api.removeRun).mockResolvedValueOnce(undefined)
    const back = vi.spyOn(window.history, 'back').mockImplementation(() => {})
    await dialog.findAll('button').find(item => item.text() === '确认删除')!.trigger('click'); await flushPromises()
    expect(api.removeRun).toHaveBeenLastCalledWith('run-one')
    expect(dialog.attributes('open')).toBeUndefined()
    expect(back).toHaveBeenCalledOnce()
    back.mockRestore()
  })

  it('返回指标时仍展示运行列表与分页，加载期间不显示空状态', async () => {
    vi.mocked(api.listRuns).mockResolvedValue({ items: [summary], total: 21, page: 1, page_size: 20, agents: [], metrics: { total: 20, success_rate: 90, p95_duration_ms: 1000, first_output_ms: 100, total_tokens: 140, tool_error_rate: 0, total_cost: null, cost_currency: null, incomplete_cost_runs: 20 } })
    await open('/runs')
    expect(wrapper.find('[aria-label="运行指标"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="运行记录列表"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('第 1 / 2 页')
    vi.mocked(api.listRuns).mockImplementation(() => new Promise(() => {}))
    await wrapper.findAll('button').find(item => item.text() === '下一页')!.trigger('click')
    expect(wrapper.text()).toContain('正在加载运行记录')
    expect(wrapper.text()).not.toContain('暂无匹配记录')
  })

  it('列表展示摘要并按状态和 Agent 筛选', async () => {
    await open('/runs')
    expect(wrapper.text()).toContain('研究助手')
    expect(wrapper.text()).toContain('模型 2')
    expect(wrapper.text()).toContain('140 · 不完整')
    await wrapper.findAll('.runs-status-option').find(item => item.text() === '失败')!.trigger('click')
    await flushPromises()
    expect(api.listRuns).toHaveBeenLastCalledWith({ page: 1, pageSize: 20, status: 'failed', agentId: undefined })
  })
  it('详情按调用标识配对步骤并按需读取输入和结果', async () => {
    await open('/runs/run-one')
    expect(wrapper.text()).toContain('模型连接失败')
    expect(wrapper.text()).toContain('已经生成的未完成内容')
    expect(wrapper.text()).toContain('文件不存在')
    const buttons = wrapper.findAll('button').filter(button => button.text().startsWith('查看'))
    expect(buttons.map(button => button.text())).toEqual(['查看输入', '查看结果'])
    await buttons[0]!.trigger('click'); await flushPromises()
    expect(api.eventPayload).toHaveBeenCalledWith('run-one', 4)
    expect(wrapper.text()).toContain('notes.txt')
  })
})
