import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ConversationNavigation from '../src/components/ConversationNavigation.vue'
import { useChatStore } from '../src/stores/chat'
import type { Conversation } from '../src/api/chat'
import * as api from '../src/api/chat'
import * as workspace from '../src/api/workspace'

vi.mock('../src/api/workspace', () => ({ projects: vi.fn(async () => [] as workspace.Project[]) }))
vi.mock('../src/api/chat', () => ({ conversations: vi.fn(async () => [] as Conversation[]), updateConversation: vi.fn() }))
let wrapper: VueWrapper | undefined
const day = (offset: number, hour = 12) => new Date(2026, 8, 27 + offset, hour).toISOString()
afterEach(() => { wrapper?.unmount(); document.body.innerHTML = ''; vi.useRealTimers(); vi.mocked(workspace.projects).mockResolvedValue([]) })

async function open() {
  vi.useFakeTimers(); vi.setSystemTime(new Date(2026, 8, 27, 16))
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }] })
  await router.push('/chat')
  const pinia = createPinia()
  wrapper = mount(ConversationNavigation, { attachTo: document.body, global: { plugins: [pinia, router] } })
  await flushPromises()
  const chat = useChatStore(pinia)
  const entry = (id: string, offset: number, hour = 12, pinned = false): Conversation => ({ id, title: id, agent_id: 'agent', pinned, created_at: day(-20), updated_at: day(offset, hour) })
  chat.sessions = [entry('较早今天', 0, 8, true), entry('更早', -7), entry('一周边界', -6, 0), entry('昨天', -1, 23), entry('最新今天', 0, 15), entry('最近一周', -2)]
  await flushPromises()
  return wrapper
}

describe('历史对话时间分组', () => {
  it('按当地自然日分组并按最近会话倒序，置顶不改变时间顺序', async () => {
    const view = await open()
    expect(view.findAll('.history-period-toggle span').map(item => item.text())).toEqual(['今天', '昨天', '一周', '更早'])
    expect(view.findAll('#history-today .conversation-open').map(item => item.attributes('title'))).toEqual(['最新今天', '较早今天'])
    expect(view.findAll('#history-week .conversation-open').map(item => item.attributes('title'))).toEqual(['最近一周', '一周边界'])
    expect(view.get('#history-earlier .conversation-open').attributes('title')).toBe('更早')
  })
  it('各时间组及整个历史可独立折叠，筛选保留草稿与当前选择', async () => {
    const view = await open()
    const chat = useChatStore()
    chat.selected = '最新今天'; chat.drafts['最新今天'] = '未发送的文字'
    const today = view.get('[aria-controls="history-today"]')
    await today.trigger('click')
    expect(today.attributes('aria-expanded')).toBe('false')
    expect(view.find('#history-today').exists()).toBe(false)
    expect(view.get('#history-week').isVisible()).toBe(true)
    await today.trigger('click')
    await view.get('[aria-controls="history-list"]').trigger('click')
    expect(view.find('#history-list').exists()).toBe(false)
    await view.get('[aria-controls="history-list"]').trigger('click')
    await view.get('input[type="search"]').setValue('最新')
    expect(view.findAll('.history-period')).toHaveLength(1)
    expect(view.findAll('.conversation-row')).toHaveLength(1)
    expect(chat.selected).toBe('最新今天')
    expect(chat.drafts['最新今天']).toBe('未发送的文字')
  })
})


describe('对话拖入项目', () => {
  it('持久化归属并展开项目，保留当前会话与草稿，失败不移动', async () => {
    vi.mocked(workspace.projects).mockResolvedValue([{id:'p',name:'项目一'}])
    const view = await open(); const chat = useChatStore()
    chat.selected = '最新今天'; chat.drafts['最新今天'] = '保留的草稿'
    const entry = chat.sessions.find(item => item.id === '最新今天')!
    vi.mocked(api.updateConversation).mockResolvedValue({...entry, project_id:'p'})
    const dataTransfer = { types: ['application/x-mini-agent-conversation'], dropEffect:'', getData: () => entry.id }
    await view.get('.project-group').trigger('dragover', {dataTransfer})
    expect(view.get('.project-group').classes()).toContain('is-drop-target')
    await view.get('.project-group').trigger('drop', {dataTransfer}); await flushPromises()
    expect(api.updateConversation).toHaveBeenCalledWith(entry.id, {project_id:'p'})
    expect(view.get('.project-conversations .conversation-title').text()).toBe('最新今天')
    expect(chat.selected).toBe('最新今天'); expect(chat.drafts['最新今天']).toBe('保留的草稿')
    vi.mocked(api.updateConversation).mockRejectedValueOnce(new Error('保存失败'))
    await view.get('.project-group').trigger('drop', {dataTransfer:{...dataTransfer,getData:()=> '昨天'}}); await flushPromises()
    expect(chat.sessions.find(item => item.id === '昨天')?.project_id).toBeUndefined()
    expect(view.text()).toContain('保存失败')
  })
})
