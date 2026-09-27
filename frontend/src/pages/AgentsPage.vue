<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createConversation, chooseAgent } from '../api/chat'
import PageHeader from '../components/PageHeader.vue'
import ConnectionStatus from '../components/ConnectionStatus.vue'
import AppIcon from '../components/AppIcon.vue'
import { deleteAgent, listAgents, setDefaultAgent, type AgentSummary } from '../api/agents'
import '../styles/agents.css'

const router = useRouter()
const startingAgent = ref('')
const agents = ref<AgentSummary[]>([])
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const deleting = ref<string | null>(null)
const replacement = ref('')
const deleteDialog = ref<HTMLDialogElement>()
const deletingAgent = computed(() => agents.value.find(agent => agent.id === deleting.value) ?? null)
const reason = (e: unknown) => e instanceof Error ? e.message : '操作未完成，请重试。'
const date = (value: string) => new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
async function startChat(agent: AgentSummary) {
  if (busy.value || agent.is_ready === false) return
  busy.value = true
  startingAgent.value = agent.id
  error.value = ''
  try {
    const conversation = await createConversation()
    await chooseAgent(conversation.id, agent.id)
    await router.push({ path: '/chat', query: { session: conversation.id } })
  } catch (e) { error.value = reason(e) }
  finally { busy.value = false; startingAgent.value = '' }
}
async function load() {
  loading.value = true
  error.value = ''
  try { agents.value = await listAgents() }
  catch (e) { error.value = reason(e) }
  finally { loading.value = false }
}
async function makeDefault(agent: AgentSummary) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try { await setDefaultAgent(agent.id); notice.value = `已将「${agent.name}」设为默认 Agent。`; await load() }
  catch (e) { error.value = reason(e) }
  finally { busy.value = false }
}
async function confirmDelete(agent: AgentSummary) {
  deleting.value = agent.id
  replacement.value = ''
  error.value = ''
  await nextTick()
  deleteDialog.value?.showModal()
  document.querySelector<HTMLElement>('#replacement, #agent-delete-cancel')?.focus()
}
async function cancelDelete() {
  if (busy.value) return
  const id = deleting.value
  deleteDialog.value?.close()
  deleting.value = null
  await nextTick()
  document.getElementById(`delete-${id}`)?.focus()
}
async function remove(agent: AgentSummary) {
  if (busy.value || (agent.is_default && agents.value.length > 1 && !replacement.value)) return
  busy.value = true
  error.value = ''
  try {
    await deleteAgent(agent.id, replacement.value)
    notice.value = `已删除「${agent.name}」。`
    deleteDialog.value?.close()
    deleting.value = null
    await load()
    await nextTick()
    document.getElementById('page-title')?.focus()
  } catch (e) { error.value = reason(e) }
  finally { busy.value = false }
}
onMounted(load)
</script>

<template>
  <div class="module-page agents-page">
    <div class="agent-page-header">
      <PageHeader title="Agent 管理" description="组合模型、指令与能力，为具体任务做好准备。" />
      <RouterLink to="/agents/new" class="button button-primary"><AppIcon name="add" />新建 Agent</RouterLink>
    </div>
    <p v-if="notice" class="model-notice" role="status">{{ notice }}</p>
    <div v-if="error" class="model-feedback" role="alert"><p>{{ error }}</p><button class="button button-ghost" :disabled="loading || busy" @click="load">重新加载</button></div>
    <p v-if="loading" class="model-loading" role="status">正在加载 Agent…</p>
    <div v-else-if="!agents.length && !error" class="resource-grid"><RouterLink class="resource-empty-card" to="/agents/new"><AppIcon name="agent" /><strong>新建第一个 Agent</strong><span>选择模型，写下任务要求。</span></RouterLink></div>
    <section v-else-if="agents.length" aria-label="已配置的 Agent">
      <div class="agent-list-heading"><h2>我的 Agent <span>{{ agents.length }}</span></h2><span>选择一个，开始工作。</span></div>
      <div class="agent-tile-grid">
        <article v-for="agent in agents" :key="agent.id" class="agent-tile" :aria-label="agent.name">
          <div class="agent-tile-identity">
            <header class="agent-tile-heading">
              <AppIcon name="agent" />
              <span v-if="agent.is_default" class="default-tag">默认 Agent</span>
            </header>
            <h3><RouterLink :to="`/agents/${agent.id}/edit`">{{ agent.name }}</RouterLink></h3>
            <p class="agent-tile-description" :title="agent.description || undefined">{{ agent.description || '尚未填写用途说明' }}</p>
          </div>
          <div class="agent-tile-configuration">
            <div class="agent-tile-model-row">
              <div class="agent-model"><span>使用模型</span><strong :title="agent.model_name">{{ agent.model_name }}</strong><small :title="agent.model_identifier">{{ agent.model_identifier }}</small></div>
              <span class="agent-tile-status" :class="{ 'is-unavailable': agent.is_ready === false }"><span class="status-dot" aria-hidden="true" />{{ agent.is_ready === false ? '需检查配置' : '可开始对话' }}</span>
            </div>
            <p v-if="agent.is_ready === false" class="agent-tile-unavailable">{{ agent.unavailable_reason || '配置不完整，请编辑后重试。' }}</p>
            <dl class="agent-counts"><div><dt>本地工具</dt><dd>{{ agent.tool_count }}</dd></div><div><dt>任务技能</dt><dd>{{ agent.skill_count }}</dd></div><div><dt>外部工具</dt><dd>{{ agent.mcp_server_count }}</dd></div></dl>
          </div>
          <footer class="agent-tile-footer">
            <div class="agent-tile-actions">
              <button class="button button-primary" :disabled="busy || agent.is_ready === false" @click="startChat(agent)">{{ startingAgent === agent.id ? '正在打开…' : '开始对话' }}<AppIcon name="arrow" /></button>
              <RouterLink :to="`/agents/${agent.id}/edit`" class="button button-plain">编辑</RouterLink>
              <RouterLink class="button button-plain" :to="{ path: '/evaluations', query: { agent: agent.id } }">评测</RouterLink>
            </div>
            <div class="agent-tile-maintenance">
              <time class="model-updated" :datetime="agent.updated_at">更新于 {{ date(agent.updated_at) }}</time>
              <button v-if="!agent.is_default" class="button button-plain" :disabled="busy || !!deleting" @click="makeDefault(agent)">设为默认</button>
              <button :id="`delete-${agent.id}`" class="button button-plain agent-delete-action" :disabled="busy" @click="confirmDelete(agent)">删除</button>
            </div>
          </footer>
        </article>
        <RouterLink class="agent-new-tile" to="/agents/new" aria-label="配置新的 Agent">
          <AppIcon name="add" />
          <div><h3>配置新的 Agent</h3><p>让不同任务拥有专属助手。</p></div>
          <ol class="agent-new-steps"><li><span>1</span>选择模型</li><li><span>2</span>写下任务要求</li><li><span>3</span>添加需要的能力</li></ol>
          <span class="agent-new-action">开始配置<AppIcon name="arrow" /></span>
        </RouterLink>
      </div>
      <p class="agent-list-note">能力数量包含已停用的绑定，当前状态可在编辑页查看。</p>
    </section>
    <dialog ref="deleteDialog" class="conversation-dialog agent-delete-dialog" aria-labelledby="agent-delete-title" aria-describedby="agent-delete-description" @cancel.prevent="cancelDelete">
      <template v-if="deletingAgent">
        <h2 id="agent-delete-title">删除「{{ deletingAgent.name }}」？</h2>
        <p id="agent-delete-description">{{ deletingAgent.is_default && agents.length > 1 ? '请先选择新的默认 Agent，切换与删除将一起完成。' : agents.length === 1 ? '这是最后一个 Agent。删除后将清除默认设置，页面回到空状态。' : '此 Agent 的配置与提示词版本将一起删除。' }}</p>
        <label v-if="deletingAgent.is_default && agents.length > 1" class="replacement-label" for="replacement">新的默认 Agent<select id="replacement" v-model="replacement" :disabled="busy"><option disabled value="">请选择 Agent</option><option v-for="other in agents.filter(item => item.id !== deletingAgent?.id)" :key="other.id" :value="other.id">{{ other.name }}</option></select></label>
        <p v-if="error" class="chat-error" role="alert">{{ error }}</p>
        <div class="model-actions"><button id="agent-delete-cancel" class="button button-ghost" :disabled="busy" @click="cancelDelete">取消</button><button class="button button-primary" :disabled="busy || (deletingAgent.is_default && agents.length > 1 && !replacement)" @click="remove(deletingAgent)">{{ busy ? '正在删除…' : '确认删除' }}</button></div>
      </template>
    </dialog>
    <footer class="page-footer"><ConnectionStatus /></footer>
  </div>
</template>
