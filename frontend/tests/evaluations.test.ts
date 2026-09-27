import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import EvaluationsPage from '../src/pages/EvaluationsPage.vue'
import * as api from '../src/api/evaluations'

vi.mock('../src/api/evaluations', () => ({
  createTask: vi.fn(), evaluationOptions: vi.fn(), getDataset: vi.fn(), getTask: vi.fn(),
  listDatasets: vi.fn(), listTasks: vi.fn(), removeCase: vi.fn(), removeDataset: vi.fn(),
  removeTask: vi.fn(), retryFailed: vi.fn(), reviewTaskCase: vi.fn(), saveCase: vi.fn(),
  saveDataset: vi.fn(), startTask: vi.fn(), stopTask: vi.fn(),
}))
const dataset: api.DatasetDetail = { id: 'dataset-1', name: '测试集', description: '已有说明', case_count: 1, created_at: '', updated_at: '', cases: [
  { id: 'case-1', dataset_id: 'dataset-1', position: 1, question: '问题', expected_answer: '答案', grading_criteria: '', history: [{ role: 'user', content: '第一行\n第二行' }] },
] }
const task: api.TaskDetail = {
  id: 'task-1', dataset_id: dataset.id, dataset_name: dataset.name, agent_id: 'agent', agent_name: '测试 Agent',
  scoring_model_id: 'model', scoring_model_name: '评分模型', passing_score: 60, tools_allowed: false,
  status: 'completed', created_at: '', started_at: null, ended_at: null,
  stats: { total: 1, completed: 1, passed: 0, failed: 1, execution_failed: 0, grading_failed: 0, average_score: 20 },
  scoring_model_identifier: '', scoring_model_snapshot: {}, agent_snapshot: {},
  cases: [{ id: 'result-1', position: 1, question: '问题', expected_answer: '答案', grading_criteria: null, status: 'failed', run_id: null, answer: '错误答案', score: 20, reason: null, error: null, grading_error_kind: null, scoring_duration_ms: null, scoring_total_tokens: null, grading_attempts: 1 }],
}
let wrapper: VueWrapper
function button(text: string) { return wrapper.findAll('button').find(item => item.text() === text)! }
async function openDataset() { await button('测试集1 条用例').trigger('click'); await flushPromises() }
beforeEach(async () => {
  vi.resetAllMocks()
  vi.mocked(api.listDatasets).mockResolvedValue([dataset])
  vi.mocked(api.listTasks).mockResolvedValue([task])
  vi.mocked(api.evaluationOptions).mockResolvedValue({ agents: [{ id: 'agent', name: '测试 Agent' }], models: [{ id: 'model', name: '评分模型', model_id: 'model' }] })
  vi.mocked(api.getDataset).mockResolvedValue(dataset)
  vi.mocked(api.getTask).mockResolvedValue(task)
  vi.mocked(api.saveDataset).mockResolvedValue(dataset)
  vi.mocked(api.reviewTaskCase).mockResolvedValue(task)
  HTMLDialogElement.prototype.showModal = function () { this.open = true }
  HTMLDialogElement.prototype.close = function () { this.open = false; this.dispatchEvent(new Event('close')) }
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/evaluations', component: EvaluationsPage }] })
  await router.push('/evaluations')
  wrapper = mount(EvaluationsPage, { attachTo: document.body, global: { plugins: [router], stubs: { RouterLink: true } } })
  await flushPromises()
})
afterEach(() => { wrapper?.unmount(); vi.restoreAllMocks(); document.body.innerHTML = '' })

describe('评测编辑与提交', () => {
  it.each(['dataset', 'case', 'task'] as const)('%s 删除使用居中弹窗，取消不发请求，确认后仅删除目标', async kind => {
    if (kind === 'task') {
      await button('评测任务').trigger('click')
      await wrapper.get('.evaluation-list-item').trigger('click'); await flushPromises()
    } else await openDataset()
    const trigger = kind === 'dataset' ? button('删除数据集') : button('删除')
    ;(trigger.element as HTMLButtonElement).focus()
    await trigger.trigger('click'); await flushPromises()
    const dialog = wrapper.get('.evaluation-delete-dialog')
    expect((dialog.element as HTMLDialogElement).open).toBe(true)
    expect(api.removeDataset).not.toHaveBeenCalled()
    expect(api.removeCase).not.toHaveBeenCalled()
    expect(api.removeTask).not.toHaveBeenCalled()
    await dialog.trigger('cancel'); await flushPromises()
    expect(document.activeElement).toBe(trigger.element)
    await trigger.trigger('click'); await flushPromises()
    await dialog.findAll('button')[1]!.trigger('click'); await flushPromises()
    if (kind === 'dataset') expect(api.removeDataset).toHaveBeenCalledWith('dataset-1')
    if (kind === 'case') expect(api.removeCase).toHaveBeenCalledWith('dataset-1', 'case-1')
    if (kind === 'task') expect(api.removeTask).toHaveBeenCalledWith('task-1')
    expect((dialog.element as HTMLDialogElement).open).toBe(false)
  })
  it('评测删除失败保留弹窗，重试成功才关闭', async () => {
    await openDataset()
    vi.mocked(api.removeDataset).mockRejectedValueOnce(new Error('暂时无法删除'))
    await button('删除数据集').trigger('click'); await flushPromises()
    await button('确认删除').trigger('click'); await flushPromises()
    const dialog = wrapper.get('.evaluation-delete-dialog')
    expect((dialog.element as HTMLDialogElement).open).toBe(true)
    expect(dialog.get('[role="alert"]').text()).toContain('暂时无法删除')
    await button('确认删除').trigger('click'); await flushPromises()
    expect((dialog.element as HTMLDialogElement).open).toBe(false)
  })
  it('查看、编辑、新建状态独立，编辑自动回填且新建不会覆盖旧数据集', async () => {
    await openDataset()
    expect(wrapper.text()).not.toContain('编辑数据集')
    await button('编辑信息').trigger('click')
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('测试集')
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('已有说明')
    await wrapper.get('input').setValue('修改后的名称')
    await wrapper.findAll('form')[0]!.trigger('submit'); await flushPromises()
    expect(api.saveDataset).toHaveBeenLastCalledWith({ name: '修改后的名称', description: '已有说明' }, dataset.id)
    await button('新建数据集').trigger('click')
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('')
    await wrapper.get('input').setValue('新数据集')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(api.saveDataset).toHaveBeenLastCalledWith({ name: '新数据集', description: '' }, undefined)
  })
  it('多行历史原样回填，混合有效与空消息时阻止保存', async () => {
    await openDataset(); await button('编辑').trigger('click')
    expect((wrapper.get('.evaluation-history textarea').element as HTMLTextAreaElement).value).toBe('第一行\n第二行')
    await button('添加历史消息').trigger('click')
    await wrapper.get('form').trigger('submit')
    expect(api.saveCase).not.toHaveBeenCalled()
    expect(wrapper.get('#history-error').text()).toContain('第 2 条')
    await wrapper.findAll('.evaluation-history textarea')[1]!.setValue('回复\n保留换行')
    await wrapper.findAll('.evaluation-history select')[1]!.setValue('assistant')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(api.saveCase).toHaveBeenCalledWith(dataset.id, expect.objectContaining({ history: [{ role: 'user', content: '第一行\n第二行' }, { role: 'assistant', content: '回复\n保留换行' }] }), 'case-1')
  })
  it('保存期间禁止重复提交，失败保留内容并恢复按钮', async () => {
    let reject!: (e: Error) => void
    vi.mocked(api.saveDataset).mockImplementation(() => new Promise((_resolve, rejectFn) => { reject = rejectFn }))
    await button('新建数据集').trigger('click'); await wrapper.get('input').setValue('待保存')
    await wrapper.get('form').trigger('submit'); await wrapper.get('form').trigger('submit')
    expect(api.saveDataset).toHaveBeenCalledTimes(1)
    expect(button('正在保存…').attributes('disabled')).toBeDefined()
    reject(new Error('连接失败')); await flushPromises()
    expect(button('保存数据集').attributes('disabled')).toBeUndefined()
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('待保存')
  })
  it('创建并启动期间只发起一次创建和启动请求', async () => {
    let finish!: (value: api.EvaluationTask) => void
    vi.mocked(api.createTask).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    vi.mocked(api.startTask).mockResolvedValue(task)
    await button('评测任务').trigger('click')
    await wrapper.get('form').trigger('submit'); await wrapper.get('form').trigger('submit')
    expect(api.createTask).toHaveBeenCalledTimes(1)
    expect(button('正在启动…').attributes('disabled')).toBeDefined()
    finish(task); await flushPromises()
    expect(api.startTask).toHaveBeenCalledTimes(1)
  })
  it('复核取消与 Esc 不提交，失败时保留备注，成功才关闭', async () => {
    await button('评测任务').trigger('click')
    await wrapper.get('.evaluation-list-item').trigger('click'); await flushPromises()
    const trigger = button('确认'); (trigger.element as HTMLButtonElement).focus()
    await trigger.trigger('click'); await flushPromises()
    await button('取消').trigger('click')
    expect(api.reviewTaskCase).not.toHaveBeenCalled()
    expect(document.activeElement).toBe(trigger.element)
    await trigger.trigger('click'); await flushPromises(); await wrapper.get('dialog[aria-labelledby="review-title"]').trigger('cancel')
    expect(api.reviewTaskCase).not.toHaveBeenCalled()
    await trigger.trigger('click'); await flushPromises()
    await wrapper.get('dialog[aria-labelledby="review-title"] textarea').setValue('人工复核说明')
    vi.mocked(api.reviewTaskCase).mockRejectedValueOnce(new Error('暂时失败'))
    await wrapper.get('dialog[aria-labelledby="review-title"] form').trigger('submit'); await flushPromises()
    expect((wrapper.get('dialog[aria-labelledby="review-title"]').element as HTMLDialogElement).open).toBe(true)
    expect((wrapper.get('dialog[aria-labelledby="review-title"] textarea').element as HTMLTextAreaElement).value).toBe('人工复核说明')
    await wrapper.get('dialog[aria-labelledby="review-title"] form').trigger('submit'); await flushPromises()
    expect(api.reviewTaskCase).toHaveBeenLastCalledWith('task-1', 'result-1', { review_status: 'confirmed', review_note: '人工复核说明' })
    expect((wrapper.get('dialog[aria-labelledby="review-title"]').element as HTMLDialogElement).open).toBe(false)
  })
  it('从数据集进入评测会保留选择，工具默认关闭且给出调用费用说明', async () => {
    await openDataset()
    await button('用这组问题评测').trigger('click'); await flushPromises()
    expect((wrapper.get('#evaluation-agent').element as HTMLSelectElement).value).toBe('agent')
    expect((wrapper.get('.evaluation-check input').element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.text()).toContain('会产生模型调用费用')
    expect(button('开始评测').attributes('disabled')).toBeUndefined()
  })
  it('空数据集无法启动，加载失败保留重试入口', async () => {
    vi.mocked(api.listDatasets).mockResolvedValue([{ ...dataset, case_count: 0 }])
    vi.mocked(api.listTasks).mockRejectedValueOnce(new Error('服务离线'))
    await wrapper.findAll('button')[0]!.trigger('click')
    // 通过显式重新加载触发失败，然后恢复。
    vi.mocked(api.getDataset).mockRejectedValueOnce(new Error('服务离线'))
    await openDataset()
    await button('重新加载').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('服务离线')
    await button('重新加载').trigger('click'); await flushPromises()
    await button('评测任务').trigger('click')
    expect(button('开始评测').attributes('disabled')).toBeDefined()
    await wrapper.find('form').trigger('submit')
    expect(api.createTask).not.toHaveBeenCalled()
  })
  it('启动失败后继续同一任务，不重复创建；查看结果时收起新建表单', async () => {
    const pendingTask = { ...task, status: 'pending' as const }
    vi.mocked(api.createTask).mockResolvedValue(pendingTask)
    vi.mocked(api.getTask).mockResolvedValue(pendingTask)
    vi.mocked(api.startTask).mockRejectedValueOnce(new Error('连接中断')).mockResolvedValue(task)
    await button('评测任务').trigger('click')
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(wrapper.text()).toContain('连接中断')
    expect(wrapper.text()).not.toContain('开始一次评测')
    expect(button('继续启动')).toBeDefined()
    await button('继续启动').trigger('click'); await flushPromises()
    expect(api.createTask).toHaveBeenCalledTimes(1)
    expect(api.startTask).toHaveBeenCalledTimes(2)
    expect(api.startTask).toHaveBeenLastCalledWith(task.id)
  })

})
