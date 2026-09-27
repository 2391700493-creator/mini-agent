import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ContextToolbar from '../src/components/ContextToolbar.vue'
import { useChatStore } from '../src/stores/chat'
import * as api from '../src/api/chat'
import * as workspace from '../src/api/workspace'
vi.mock('../src/api/workspace', () => ({ chooseFolder: vi.fn() }))
vi.mock('../src/api/chat', () => ({ conversations: vi.fn(), chatAgents: vi.fn(), conversationDetail: vi.fn(), updateConversation: vi.fn() }))
const summary = { id: 'one', title: '新会话', agent_id: 'a', pinned: false, folder: 'original', created_at: '2026-09-27', updated_at: '2026-09-27' }
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.conversations).mockResolvedValue([summary])
  vi.mocked(api.chatAgents).mockResolvedValue([{id:'a',name:'助手',is_default:true}])
  vi.mocked(api.conversationDetail).mockImplementation(async id => ({...summary,id,messages:[],generation:null}))
  vi.mocked(api.updateConversation).mockImplementation(async (id, data) => ({...summary,id,...data}))
})
afterEach(() => document.body.innerHTML = '')
async function open() {
  const pinia = createPinia(); const chat = useChatStore(pinia)
  await chat.load('one')
  const view = mount(ContextToolbar, { attachTo: document.body, global: { plugins: [pinia] } })
  return { view, chat }
}
describe('系统文件夹选择', () => {
  it('取消不修改绑定，选择成功只绑定一个目录', async () => {
    const { view } = await open()
    try {
      vi.mocked(workspace.chooseFolder).mockResolvedValueOnce({folder:null}).mockResolvedValueOnce({folder:'outputs'})
      await view.get('.context-folder-chip').trigger('click'); await flushPromises()
      expect(api.updateConversation).not.toHaveBeenCalled()
      await view.get('.context-folder-chip').trigger('click'); await flushPromises()
      expect(api.updateConversation).toHaveBeenCalledWith('one', {folder:'outputs'})
      expect(view.get('.context-folder-chip').text()).toContain('outputs')
    } finally { view.unmount() }
  })
  it('等待系统选择时切换会话，不把目录写入其他会话', async () => {
    const { view, chat } = await open()
    try {
      let resolve!: (value: {folder:string}) => void
      vi.mocked(workspace.chooseFolder).mockReturnValue(new Promise(done => { resolve = done }))
      await view.get('.context-folder-chip').trigger('click')
      await chat.select('two')
      resolve({folder:'outputs'}); await flushPromises()
      expect(api.updateConversation).not.toHaveBeenCalled()
      expect(view.text()).toContain('对话已变化')
    } finally { view.unmount() }
  })
})
