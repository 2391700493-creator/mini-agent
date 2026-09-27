<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '../components/PageHeader.vue'
import ConnectionStatus from '../components/ConnectionStatus.vue'
import AppIcon from '../components/AppIcon.vue'
import { listTools, toggleTool, type Tool } from '../api/tools'

const tools = ref<Tool[]>([])
const loading = ref(true)
const error = ref('')
const notice = ref('')
const pending = ref<string | null>(null)
const reason = (e: unknown) => e instanceof Error ? e.message : '操作未完成，请重试。'
async function load() {
  loading.value = true
  error.value = ''
  try { tools.value = await listTools() }
  catch (e) { error.value = reason(e) }
  finally { loading.value = false }
}
async function toggle(tool: Tool) {
  if (pending.value) return
  pending.value = tool.id
  error.value = ''
  notice.value = ''
  try {
    const updated = await toggleTool(tool.id, !tool.enabled)
    tools.value = tools.value.map(item => item.id === updated.id ? updated : item)
    notice.value = `已${updated.enabled ? '启用' : '停用'}「${updated.name}」。`
  } catch (e) { error.value = reason(e) }
  finally { pending.value = null }
}
onMounted(load)
</script>

<template>
  <div class="module-page tools-page">
    <PageHeader title="本地工具" description="选择 Agent 可以执行的操作，并了解每项能力的边界。" />
    <aside class="tool-note"><AppIcon name="info" /><p>系统内置工具可启用或停用，用途与参数由系统维护。Shell 和文件读写仅能操作授权目录。</p></aside>
    <p v-if="notice" class="model-notice" role="status">{{ notice }}</p>
    <div v-if="error" class="model-feedback" role="alert"><p>{{ error }}</p><button class="button button-ghost" :disabled="loading || !!pending" @click="load">重新加载</button></div>
    <p v-if="loading" class="model-loading" role="status">正在加载工具…</p>
    <section v-else-if="tools.length" aria-label="内置工具">
      <div class="model-list-heading"><h2>内置工具 <span>{{ tools.length }}</span></h2><span class="muted">已启用 {{ tools.filter(tool => tool.enabled).length }} 项</span></div>
      <div class="management-list resource-grid">
      <article v-for="tool in tools" :key="tool.id" class="tool-card management-row tool-row resource-card" :class="{ 'is-enabled': tool.enabled }" :aria-label="tool.name">
        <div class="tool-heading"><h3><RouterLink class="resource-main-link" :to="`/tools/${tool.id}`">{{ tool.name }}</RouterLink></h3><span class="subtle-tag">{{ tool.is_builtin ? '系统内置' : '自定义' }}</span></div>
        <div class="tool-row-summary">
          <p class="tool-description">{{ tool.description }}</p>
          <p v-if="!tool.available" class="tool-unavailable">{{ tool.unavailable_reason }}</p>
        </div>
        <div class="tool-card-bottom">
          <button class="tool-switch" role="switch" :aria-checked="tool.enabled" :aria-label="`${tool.name}启用状态`" :disabled="!!pending" @click="toggle(tool)"><span class="switch-track" :class="{ 'is-on': tool.enabled }" aria-hidden="true"><span /></span><span>{{ pending === tool.id ? '保存中…' : tool.enabled ? '已启用' : '已停用' }}</span></button>
          <RouterLink :to="`/tools/${tool.id}`" class="text-link">查看详情 <AppIcon name="arrow" /></RouterLink>
        </div>
      </article>
      </div>
    </section>
    <p v-else-if="!error" class="model-loading">暂无工具，请检查数据库迁移。</p>
    <footer class="page-footer"><span class="footer-note">启停状态保存在本机，下次调用时生效。</span><ConnectionStatus /></footer>
  </div>
</template>
