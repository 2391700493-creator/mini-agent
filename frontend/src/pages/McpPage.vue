<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import ResourceGuideCard from '../components/ResourceGuideCard.vue'
import PageHeader from '../components/PageHeader.vue'
import ConnectionStatus from '../components/ConnectionStatus.vue'
import { listMcp, testMcp, toggleMcp, deleteMcp, type McpServer } from '../api/mcp'

const items = ref<McpServer[]>([])
const loading = ref(true)
const error = ref('')
const pending = ref(new Set<string>())
const deleting = ref<McpServer | null>(null)
const deleteDialog = ref<HTMLDialogElement>()
let poll: ReturnType<typeof setTimeout> | undefined
let disposed = false
const reason = (e: unknown) => e instanceof Error ? e.message : '操作失败，请重试。'
const date = (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false })
const busy = (item: McpServer) => pending.value.has(item.id) || item.testing
function schedule() {
  clearTimeout(poll)
  if (!disposed && items.value.some(item => item.testing)) poll = setTimeout(() => load(false), 1500)
}
async function load(showLoading = true) {
  if (showLoading) loading.value = true
  error.value = ''
  try { items.value = await listMcp(); schedule() }
  catch (e) { error.value = reason(e) }
  finally { loading.value = false }
}
async function action(item: McpServer, kind: 'test' | 'toggle' | 'delete') {
  if (busy(item)) return
  pending.value.add(item.id)
  error.value = ''
  if (kind === 'test') item.testing = true
  try {
    if (kind === 'delete') {
      await deleteMcp(item.id)
      items.value = items.value.filter(value => value.id !== item.id)
      deleteDialog.value?.close()
      deleting.value = null
      await nextTick()
      document.getElementById('page-title')?.focus()
    } else {
      const result = await (kind === 'test' ? testMcp(item.id) : toggleMcp(item.id, !item.enabled))
      items.value = items.value.map(value => value.id === item.id ? result : value)
    }
  } catch (e) {
    error.value = reason(e)
    // 请求超时后从后端恢复实际测试状态，避免误认为进程已经结束。
    try { items.value = await listMcp() } catch { item.testing = false }
  } finally { pending.value.delete(item.id); schedule() }
}
async function confirmDelete(item: McpServer) {
  deleting.value = item
  error.value = ''
  await nextTick()
  deleteDialog.value?.showModal()
  document.querySelector<HTMLElement>('#mcp-delete-cancel')?.focus()
}
async function cancelDelete() {
  const id = deleting.value?.id
  if (id && pending.value.has(id)) return
  deleteDialog.value?.close()
  deleting.value = null
  await nextTick()
  document.getElementById(`delete-${id}`)?.focus()
}
function properties(schema: Record<string, unknown>) {
  const entries = schema.properties
  return entries && typeof entries === 'object' && !Array.isArray(entries) ? Object.entries(entries).map(([name, value]) => {
    const prop = value && typeof value === 'object' ? value as Record<string, unknown> : {}
    return { name, type: Array.isArray(prop.type) ? prop.type.join(' / ') : typeof prop.type === 'string' ? prop.type : '参见完整参数定义',
      required: Array.isArray(schema.required) && schema.required.includes(name), description: typeof prop.description === 'string' ? prop.description : '未提供说明' }
  }) : []
}
function parameterPreview(schema: Record<string, unknown>) {
  const entries = properties(schema)
  if (!entries.length) return '无需参数'
  const names = entries.slice(0, 3).map(item => item.name).join('、')
  return entries.length > 3 ? `${names} 等 ${entries.length} 个参数` : `${names} · ${entries.length} 个参数`
}
onMounted(() => load())
onUnmounted(() => { disposed = true; clearTimeout(poll) })
</script>

<template>
  <div class="module-page mcp-page">
    <div class="models-header"><PageHeader title="外部工具" description="连接本机程序，发现 Agent 可用的外部工具。" />
      <div class="model-actions skills-toolbar"><button class="button button-ghost" :disabled="loading" @click="load()"><AppIcon name="refresh" />刷新</button><RouterLink class="button button-primary" to="/mcp/new"><AppIcon name="add" />连接工具</RouterLink></div>
    </div>
    <details class="skills-format"><summary>连接说明</summary><p class="skills-intro">本阶段支持本机 stdio Server。测试会启动所配置的程序并读取工具列表，不调用工具；请使用你信任的程序。启用状态独立保存，测试成功后仍保持原状态。</p></details>
    <div v-if="error" class="model-feedback" role="alert"><p>{{ error }}</p><button class="button button-ghost" :disabled="loading" @click="load()">重新加载</button></div>
    <p v-if="loading" class="model-loading" role="status">正在读取 MCP Server…</p>
    <section v-else-if="items.length" aria-label="MCP Server 列表">
      <div class="model-list-heading"><h2>本机工具 <span>{{ items.length }}</span></h2><span class="muted">已启用 {{ items.filter(item => item.enabled).length }} 项</span></div>
      <div class="mcp-server-grid resource-grid">
      <article v-for="item in items" :key="item.id" class="mcp-card resource-card" :class="{ 'is-enabled': item.enabled }" :aria-label="item.name" :aria-busy="busy(item)">
        <header class="mcp-card-header"><div><h3><RouterLink class="resource-main-link" :to="`/mcp/${item.id}/edit`">{{ item.name }}</RouterLink></h3><p>{{ item.description || '未填写说明' }}</p></div><button class="tool-switch" role="switch" :aria-checked="item.enabled" :aria-label="`${item.name}启用状态`" :disabled="busy(item) || !!deleting" @click="action(item, 'toggle')"><span class="switch-track" :class="{ 'is-on': item.enabled }" aria-hidden="true"><span /></span><span>{{ item.enabled ? '已启用' : '已停用' }}</span></button></header>
        <div class="mcp-card-groups">
          <details class="mcp-card-group"><summary>启动配置</summary><dl class="mcp-config-facts"><div><dt>命令</dt><dd><code>{{ item.command }}</code></dd></div><div><dt>参数</dt><dd><code>{{ item.args.length ? JSON.stringify(item.args) : '无' }}</code></dd></div></dl></details>
          <section class="mcp-card-group" aria-label="连接状态"><span class="mcp-group-label">连接状态</span><p class="mcp-test-summary" role="status">{{ item.testing ? '正在测试连接…' : item.message }}</p><dl class="mcp-test-meta"><div><dt>最近测试</dt><dd>{{ item.tested_at ? date(item.tested_at) : '暂无' }}</dd></div><div><dt>发现工具</dt><dd>{{ item.tool_count === null ? '未知' : `${item.tool_count} 个` }}</dd></div></dl></section>
        </div>
        <p v-if="item.diagnostic" class="mcp-diagnostic">{{ item.diagnostic }}</p>
        <details v-if="item.tools.length" class="mcp-tools"><summary>查看最近成功测试的工具（{{ item.tools.length }}）</summary><p v-if="item.status !== 'success'" class="field-hint">以下为历史发现结果，请重新测试以验证当前配置。</p>
          <div class="mcp-tool-grid">
            <section v-for="tool in item.tools" :key="tool.name" class="mcp-tool"><div class="mcp-tool-heading"><h4>{{ tool.name }}</h4><span>{{ properties(tool.input_schema).length }} 个参数</span></div><p class="mcp-tool-description">{{ tool.description || '未提供说明' }}</p><p class="mcp-tool-preview">{{ parameterPreview(tool.input_schema) }}</p>
              <details class="mcp-tool-details"><summary>查看参数详情</summary><dl class="mcp-parameters"><div v-for="prop in properties(tool.input_schema)" :key="prop.name"><dt><code>{{ prop.name }}</code> · {{ prop.type }} · {{ prop.required ? '必填' : '选填' }}</dt><dd>{{ prop.description }}</dd></div></dl>
                <details class="mcp-schema"><summary>完整参数定义</summary><pre>{{ JSON.stringify(tool.input_schema, null, 2) }}</pre></details>
              </details>
            </section>
          </div>
        </details>
        <footer class="mcp-card-actions"><div class="model-actions"><button class="button button-ghost" :disabled="busy(item) || !!deleting" @click="action(item, 'test')">{{ item.testing ? '正在测试…' : '测试连接' }}</button><RouterLink v-if="!busy(item)" class="button button-plain" :to="`/mcp/${item.id}/edit`">编辑</RouterLink><button v-else class="button button-plain" disabled>编辑</button></div><div class="resource-card-maintenance"><span class="model-updated">stdio · 本机启动</span><button :id="`delete-${item.id}`" class="button button-plain button-danger" :disabled="busy(item) || !!deleting" @click="confirmDelete(item)">删除</button></div></footer>
      </article>
      <ResourceGuideCard title="连接新的外部工具" description="接入任务需要的本机工具。" icon="mcp" :steps="['粘贴连接配置', '测试并查看工具列表', '按需启用并绑定 Agent']" action="连接工具" to="/mcp/new" />
      </div>
    </section>
    <div v-else-if="!error" class="resource-grid"><RouterLink class="resource-empty-card" to="/mcp/new"><AppIcon name="mcp" /><strong>连接第一个外部工具</strong><span>粘贴工具提供的连接配置。</span></RouterLink></div>
    <dialog ref="deleteDialog" class="conversation-dialog mcp-delete-dialog" aria-labelledby="mcp-delete-title" @cancel.prevent="cancelDelete">
      <template v-if="deleting">
        <h2 id="mcp-delete-title">删除「{{ deleting.name }}」？</h2>
        <p>配置、环境变量和测试记录将被删除。本机程序会保留。</p>
        <p v-if="error" class="chat-error" role="alert">{{ error }}</p>
        <div class="model-actions"><button id="mcp-delete-cancel" class="button button-ghost" :disabled="busy(deleting)" @click="cancelDelete">取消</button><button class="button button-primary" :disabled="busy(deleting)" @click="action(deleting, 'delete')">{{ busy(deleting) ? '正在删除…' : '确认删除' }}</button></div>
      </template>
    </dialog>
    <footer class="page-footer"><span class="footer-note">测试仅发现工具；停用后不提供给 Agent。</span><ConnectionStatus /></footer>
  </div>
</template>
