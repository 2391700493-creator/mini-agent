import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReplyActions from '../src/components/ReplyActions.vue'
import { saveMessageFeedback, type ChatMessage } from '../src/api/chat'
vi.mock('../src/api/chat', () => ({ saveMessageFeedback: vi.fn() }))
const message: ChatMessage = { id: 'reply', conversation_id: 'conversation', sequence: 2, role: 'assistant', content: '回复内容\n**保留格式**', status: 'completed', created_at: '2026-09-27', agent_id: 'agent', agent_name: '助手', feedback_rating: null }
const writeText = vi.fn()
let view: VueWrapper
beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('navigator', { clipboard: { writeText } })
  writeText.mockResolvedValue(undefined)
  view = mount(ReplyActions, { attachTo: document.body, props: { message, canRegenerate: true } })
})
afterEach(() => { view.unmount(); vi.unstubAllGlobals() })
describe('回复图标操作', () => {
  it('复制与分享都只复制当前回复内容，并显示完成提示', async () => {
    expect(view.get('button[aria-label="复制"]').attributes('aria-pressed')).toBeUndefined()
    expect(view.get('button[aria-label="分享"]').attributes('aria-expanded')).toBeUndefined()
    await view.get('button[aria-label="复制"]').trigger('click'); await flushPromises()
    await view.get('button[aria-label="分享"]').trigger('click'); await flushPromises()
    expect(writeText.mock.calls).toEqual([[message.content], [message.content]])
    expect(view.findAll('button[aria-label="已复制"]')).toHaveLength(1)
  })
  it('成功保存反馈后关闭选项并恢复键盘焦点', async () => {
    vi.mocked(saveMessageFeedback).mockResolvedValue({ ...message, feedback_rating: 'helpful' })
    await view.get('button[aria-label="反馈"]').trigger('click')
    await view.get('.reply-feedback-picker button').trigger('click'); await flushPromises()
    expect(saveMessageFeedback).toHaveBeenCalledWith('conversation', 'reply', 'helpful')
    expect(view.emitted('feedback')).toEqual([['helpful']])
    expect(view.find('.reply-feedback-picker').exists()).toBe(false)
    expect(document.activeElement).toBe(view.get('button[aria-label="反馈"]').element)
  })
  it('保存失败不显示已保存状态，保留选项便于重试', async () => {
    vi.mocked(saveMessageFeedback).mockRejectedValue(new Error('反馈未保存，请重试。'))
    await view.get('button[aria-label="反馈"]').trigger('click')
    await view.get('.reply-feedback-picker button').trigger('click'); await flushPromises()
    expect(view.emitted('feedback')).toBeUndefined()
    expect(view.get('[role="alert"]').text()).toContain('反馈未保存')
    expect(view.get('.reply-feedback-picker button').attributes('disabled')).toBeUndefined()
  })
  it('旧回复保留操作图标但不能重新生成，Escape 关闭反馈', async () => {
    await view.setProps({ canRegenerate: false })
    expect(view.get('button[aria-label="重新生成"]').attributes('disabled')).toBeDefined()
    await view.get('button[aria-label="反馈"]').trigger('click')
    await view.get('.reply-feedback-picker button').trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(view.find('.reply-feedback-picker').exists()).toBe(false)
    expect(document.activeElement).toBe(view.get('button[aria-label="反馈"]').element)
  })
})
