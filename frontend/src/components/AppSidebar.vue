<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { modules } from '../router/modules'
import AppIcon from './AppIcon.vue'
import ConversationNavigation from './ConversationNavigation.vue'
defineProps<{ collapsed?: boolean }>()
const route = useRoute()
const profileDialog = ref<HTMLDialogElement>()
const groups = [
  { name: '能力工坊', icon: 'tool' as const, items: modules.slice(2, 6) },
  { name: '观察评测', icon: 'history' as const, items: modules.slice(6) },
]
const openGroup = ref('')
watch(() => route.path, () => {
  if (profileDialog.value?.open) profileDialog.value.close()
  openGroup.value = groups.find(group => group.items.some(item => route.path === item.path || route.path.startsWith(`${item.path}/`)))?.name || ''
}, { immediate: true })
defineEmits<{ collapse: [] }>()
</script>

<template>
  <aside id="app-sidebar" class="sidebar">
    <div class="sidebar-header">
    <RouterLink to="/chat" class="brand" aria-label="Mini-Agent 首页">
      <span class="native-brand"><AppIcon name="agent" /></span><span class="brand-name">Mini-Agent</span>
    </RouterLink>
    <button :id="collapsed ? 'sidebar-expand' : 'sidebar-collapse'" class="sidebar-toggle" :class="{ 'sidebar-collapse': !collapsed }" :aria-label="collapsed ? '展开主导航' : '收起主导航'" :title="collapsed ? '展开主导航' : '收起主导航'" aria-controls="app-sidebar" :aria-expanded="!collapsed" @click="$emit('collapse')"><AppIcon name="chevron" /></button>
    </div>
    <ConversationNavigation>
    <template #navigation>
    <nav aria-label="主导航" class="navigation">
      <RouterLink to="/agents" class="nav-link nav-primary" active-class="is-active" :aria-current="route.path === '/agents' || route.path.startsWith('/agents/') ? 'page' : undefined" aria-label="Agent 管理" title="Agent 管理"><AppIcon name="agent" /><span class="nav-label">Agent 管理</span><span class="nav-tooltip" aria-hidden="true">Agent 管理</span></RouterLink>
      <div v-for="group in groups" :key="group.name" class="nav-group">
      <button class="nav-group-toggle" :class="{ 'is-current': group.items.some(item => route.path === item.path || route.path.startsWith(`${item.path}/`)) }" :aria-expanded="openGroup === group.name" :aria-controls="`nav-${group.icon}`" :title="group.name" :aria-label="group.name" @click="openGroup = openGroup === group.name ? '' : group.name"><AppIcon :name="group.icon" /><span>{{ group.name }}</span></button>
      <div v-show="openGroup === group.name" :id="`nav-${group.icon}`" class="nav-group-items">
      <RouterLink v-for="item in group.items" :key="item.path" :to="item.path" :aria-label="item.title" :aria-current="route.path === item.path || route.path.startsWith(`${item.path}/`) ? 'page' : undefined" :title="item.title" class="nav-link" :class="{ 'is-active': route.path.startsWith(`${item.path}/`) }" active-class="is-active">
        <AppIcon :name="item.icon" />
        <span class="nav-label">{{ item.title }}</span>
        <span class="nav-short-label" aria-hidden="true">{{ ({ chat: '聊天', agents: 'Agent', models: '模型', tools: '工具', mcp: '外接', skills: '技能', runs: '记录', evaluations: '评测' })[item.name] }}</span>
        <span class="nav-tooltip" aria-hidden="true">{{ item.title }}</span>
      </RouterLink>
      </div>
      </div>
    </nav>
    <RouterLink class="automation-nav nav-link" active-class="is-active" :aria-current="route.path === '/automations' ? 'page' : undefined" to="/automations" title="定时任务"><AppIcon name="clock" /><span class="nav-label">定时任务</span></RouterLink>
    </template>
    </ConversationNavigation>
    <div class="sidebar-account">
      <button class="account-trigger" aria-label="本地用户与使用指南" aria-haspopup="dialog" @click="profileDialog?.showModal()">
        <span class="account-avatar" aria-hidden="true"><AppIcon name="user" /></span>
        <span class="account-copy"><strong>本地用户</strong><span>个人工作空间</span></span>
        <span class="account-more" aria-hidden="true">···</span>
      </button>
    </div>
  <dialog ref="profileDialog" class="workspace-dialog" aria-labelledby="profile-title">
    <div class="dialog-heading"><h2 id="profile-title">你的工作空间</h2><button class="icon-button" aria-label="关闭工作空间" @click="profileDialog?.close()"><AppIcon name="close" /></button></div>
    <p class="dialog-intro">当前为本地使用，无需登录。会话和配置保存在这台电脑，发送消息时会调用你配置的模型服务。</p>
    <div class="workspace-guide">
      <RouterLink to="/models"><AppIcon name="model" /><span><strong>连接模型</strong><small>添加兼容接口，测试连接</small></span><AppIcon name="arrow" /></RouterLink>
      <RouterLink to="/agents"><AppIcon name="agent" /><span><strong>配置你的 Agent</strong><small>选择模型、指令与可用能力</small></span><AppIcon name="arrow" /></RouterLink>
    </div>
    <p class="dialog-footnote">使用提示：Enter 发送，Shift + Enter 换行。会话右侧的 ··· 可以置顶、改名和删除。</p>
    <p class="workspace-version">Mini-Agent · 本地工作空间</p>
  </dialog>
  </aside>
</template>
