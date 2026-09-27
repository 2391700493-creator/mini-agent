import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App.vue'
vi.mock('../src/api/workspace', () => ({ projects: async () => [] }))
import { createAppRouter } from '../src/router'
import { modules } from '../src/router/modules'

let wrapper: VueWrapper | undefined
const healthy = () => new Response(JSON.stringify({ status: 'ok', database: 'connected', project: 'mini-agent' }))

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (path: string) => path === '/api/skills' ? new Response('{"items":[],"issues":[]}') : ['/api/models', '/api/tools', '/api/mcp', '/api/agents', '/api/chat/conversations', '/api/chat/agents'].includes(path) ? new Response('[]') : healthy()))
})

afterEach(() => {
  wrapper?.unmount()
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

async function openApp(path = '/') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()
  wrapper = mount(App, { attachTo: document.body, global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return { router, app: wrapper }
}

describe('工作空间导航', () => {
  it('键盘操作标记即时切换，鼠标操作恢复过渡，卸载后清理监听', async () => {
    const { app } = await openApp()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
    expect(document.documentElement.dataset.inputModality).toBe('keyboard')
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    expect(document.documentElement.dataset.inputModality).toBe('pointer')
    app.unmount()
    wrapper = undefined
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    expect(document.documentElement.dataset.inputModality).toBeUndefined()
  })
  it('收起主导航后切页仍保持收起，展开时恢复导航和焦点', async () => {
    const { router, app } = await openApp()
    await app.get('#sidebar-collapse').trigger('click')
    expect(app.get('.sidebar').isVisible()).toBe(true)
    expect(app.get('.app-shell').classes()).toContain('sidebar-collapsed')
    expect(app.findAll('nav a')).toHaveLength(7)
    expect(app.get('#sidebar-expand').attributes('aria-expanded')).toBe('false')
    expect(document.activeElement?.id).toBe('sidebar-expand')
    await router.push('/models'); await flushPromises()
    expect(app.get('.sidebar').isVisible()).toBe(true)
    expect(app.get('.app-shell').classes()).toContain('sidebar-collapsed')
    expect(app.findAll('nav a')).toHaveLength(7)
    await app.get('#sidebar-expand').trigger('click')
    expect(app.get('.sidebar').isVisible()).toBe(true)
    expect(app.findAll('nav a')).toHaveLength(7)
    expect(document.activeElement?.id).toBe('sidebar-collapse')
  })
  it('899px 窗口默认收起，手动展开后切页保留状态', async () => {
    vi.stubGlobal('innerWidth', 899)
    const { router, app } = await openApp('/models')
    expect(app.get('.app-shell').classes()).toContain('sidebar-collapsed')
    await app.get('#sidebar-expand').trigger('click')
    await router.push('/agents'); await flushPromises()
    expect(app.get('.app-shell').classes()).not.toContain('sidebar-collapsed')
    expect(app.get('#sidebar-collapse').attributes('aria-expanded')).toBe('true')
  })
  it('首页打开聊天，加载会话且不展示连接装饰', async () => {
    const { router, app } = await openApp()
    expect(router.currentRoute.value.path).toBe('/chat')
    expect(app.get('h1').text()).toBe('聊天')
    expect(app.find('.connection-block').exists()).toBe(false)
    expect(fetch).toHaveBeenCalledWith('/api/chat/conversations', expect.any(Object))
  })

  it.each(modules)('直接访问 $path 时显示对应模块', async (module) => {
    const { app } = await openApp(module.path)
    expect(app.get('h1').text()).toBe(module.title)
    if (module.name !== 'chat') expect(app.get('nav [aria-current="page"]').attributes('href')).toBe(module.path)
    if (module.name === 'chat') {
      expect(app.text()).toContain('新建对话')
      expect(app.text()).toContain('前往配置')
    } else if (module.name === 'agents') {
      expect(app.text()).toContain('新建第一个 Agent')
    } else if (module.name === 'models') {
      expect(app.text()).toContain('添加第一个模型')
    } else if (module.name === 'tools') {
      expect(app.text()).toContain('系统内置工具可启用或停用')
    } else if (module.name === 'mcp') {
      expect(app.text()).toContain('连接工具')
    } else if (module.name === 'skills') {
      expect(app.text()).toContain('导入 ZIP')
    } else if (module.name === 'runs') {
      expect(app.text()).toContain('每次 Agent 请求的结果')
    } else if (module.name === 'evaluations') {
      expect(app.text()).toContain('用一组问题检查 Agent 的回答')
    }
    expect(document.title).toBe(`${module.title} · Mini-Agent`)
  })

  it('八个菜单按指定顺序显示并能逐一切换', async () => {
    const { router, app } = await openApp()
    expect(app.findAll('.nav-group-toggle')).toHaveLength(2)
    expect(app.findAll('.nav-group-items').filter(item => item.isVisible())).toHaveLength(0)
    expect(app.get('.nav-primary').attributes('href')).toBe('/agents')
    expect(app.find('button[aria-label="工作空间"]').exists()).toBe(false)
    const links = app.findAll('nav a')
    expect(links.map(link => link.attributes('aria-label'))).toEqual([
      'Agent 管理', '模型连接', '本地工具', '外部工具', '任务技能', '运行记录', 'Agent 评测',
    ])
    for (const [index, link] of links.entries()) {
      await link.trigger('click')
      await flushPromises()
      expect(router.currentRoute.value.path).toBe(modules[index + 1]!.path)
      expect(app.get('h1').text()).toBe(modules[index + 1]!.title)
      expect(app.findAll('nav [aria-current="page"]')).toHaveLength(1)
    }
    expect(document.activeElement?.id).toBe('page-title')
  })

  it('未知路径安全回到聊天', async () => {
    const { router, app } = await openApp('/missing/path')
    expect(router.currentRoute.value.path).toBe('/chat')
    expect(app.get('h1').text()).toBe('聊天')
  })

  it('连接失败时保留导航和错误提示，并可通过按钮重试', async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError('offline'))
    const { app } = await openApp()
    expect(app.get('[role="alert"]').text()).toContain('确认后端已启动')
    expect(app.findAll('nav a')).toHaveLength(7)
    await app.findAll('button').find(button => button.text() === '重新加载')!.trigger('click')
    await flushPromises()
    expect(app.text()).toContain('新建对话')
    expect(app.find('[role="alert"]').exists()).toBe(false)
  })
})
