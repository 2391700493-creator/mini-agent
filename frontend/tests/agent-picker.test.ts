import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AgentPicker from '../src/components/AgentPicker.vue'
const agents = [
  { id: 'a', name: '文档助手', is_default: true },
  { id: 'b', name: '停用助手', is_default: false, is_ready: false },
  { id: 'c', name: '规划助手', is_default: false },
]
describe('聊天 Agent 选择', () => {
  it('键盘跳过不可用项，Enter 选择并恢复焦点，Escape 不修改选择', async () => {
    const view = mount(AgentPicker, { attachTo: document.body, props: { agents, modelValue: 'a' } })
    try {
      await view.get('#chat-agent').trigger('keydown', { key: 'ArrowDown' }); await flushPromises()
      expect(view.get('#chat-agent-options').attributes('aria-activedescendant')).toBe('agent-option-a')
      expect(view.get('#agent-option-a').attributes('aria-selected')).toBe('true')
      await view.get('#chat-agent-options').trigger('keydown', { key: 'ArrowDown' })
      expect(view.get('#chat-agent-options').attributes('aria-activedescendant')).toBe('agent-option-c')
      await view.get('#chat-agent-options').trigger('keydown', { key: 'Enter' })
      expect(view.emitted('update:modelValue')).toEqual([['c']])
      expect(document.activeElement?.id).toBe('chat-agent')
      await view.get('#chat-agent').trigger('click'); await flushPromises()
      await view.get('#chat-agent-options').trigger('keydown', { key: 'Escape' })
      expect(view.find('#chat-agent-options').exists()).toBe(false)
      expect(view.emitted('update:modelValue')).toHaveLength(1)
    } finally { view.unmount() }
  })
  it('点不可用项不提交，禁用时关闭菜单', async () => {
    const view = mount(AgentPicker, { props: { agents, modelValue: 'a' } })
    await view.get('#chat-agent').trigger('click'); await flushPromises()
    await view.get('#agent-option-b').trigger('click')
    expect(view.emitted('update:modelValue')).toBeUndefined()
    await view.setProps({ disabled: true })
    expect(view.find('#chat-agent-options').exists()).toBe(false)
    view.unmount()
  })
})
