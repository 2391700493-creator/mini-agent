import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'
import ChatPage from '../pages/ChatPage.vue'
import AgentsPage from '../pages/AgentsPage.vue'
import AgentFormPage from '../pages/AgentFormPage.vue'
import McpPage from '../pages/McpPage.vue'
import McpFormPage from '../pages/McpFormPage.vue'
import ModulePage from '../pages/ModulePage.vue'
import ModelsPage from '../pages/ModelsPage.vue'
import ModelFormPage from '../pages/ModelFormPage.vue'
import ToolsPage from '../pages/ToolsPage.vue'
import SkillsPage from '../pages/SkillsPage.vue'
import SkillFormPage from '../pages/SkillFormPage.vue'
import ToolDetailPage from '../pages/ToolDetailPage.vue'
import { modules } from './modules'

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  const router = createRouter({
    history,
    routes: [
      { path: '/automations', name: 'automations', component: () => import('../pages/AutomationsPage.vue'), meta: { title: '定时任务' } },
      { path: '/agents/new', name: 'agent-new', component: AgentFormPage, meta: { title: '新建 Agent' } },
      { path: '/agents/:id/edit', name: 'agent-edit', component: AgentFormPage, meta: { title: '编辑 Agent' } },
      { path: '/mcp/new', name: 'mcp-new', component: McpFormPage, meta: { title: '新增 MCP Server' } },
      { path: '/mcp/:id/edit', name: 'mcp-edit', component: McpFormPage, meta: { title: '编辑 MCP Server' } },
      { path: '/', redirect: '/chat' },
      { path: '/skills/:id/edit', name: 'skill-edit', component: SkillFormPage, meta: { title: '编辑 Skill' } },
      { path: '/tools/:id', name: 'tool-detail', component: ToolDetailPage, meta: { title: '工具详情' } },
      { path: '/models/new', name: 'model-new', component: ModelFormPage, meta: { title: '添加模型' } },
      { path: '/models/:id/edit', name: 'model-edit', component: ModelFormPage, meta: { title: '编辑模型' } },
      { path: '/runs/:id', name: 'run-detail', component: () => import('../pages/RunDetailPage.vue'), meta: { title: '运行详情' } },
      ...modules.map((module) => ({
        path: module.path,
        name: module.name,
        component: module.name === 'chat' ? ChatPage : module.name === 'agents' ? AgentsPage : module.name === 'mcp' ? McpPage : module.name === 'models' ? ModelsPage : module.name === 'tools' ? ToolsPage : module.name === 'skills' ? SkillsPage : module.name === 'runs' ? () => import('../pages/RunsPage.vue') : module.name === 'evaluations' ? () => import('../pages/EvaluationsPage.vue') : ModulePage,
        props: { module },
        meta: { title: module.title },
      })),
      { path: '/:pathMatch(.*)*', redirect: '/chat' },
    ],
  })
  router.afterEach((to) => { document.title = `${to.meta.title ?? '工作空间'} · Mini-Agent` })
  return router
}
