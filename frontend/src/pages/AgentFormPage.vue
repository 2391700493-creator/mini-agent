<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUnsavedChanges } from '../composables/useUnsavedChanges'
import AppIcon from '../components/AppIcon.vue'
import PageHeader from '../components/PageHeader.vue'
import ConnectionStatus from '../components/ConnectionStatus.vue'
import DeleteDialog from '../components/DeleteDialog.vue'
import { ApiError } from '../api/client'
import { agentOptions, getAgent, saveAgent, type AgentDetail, type AgentOptions, type Capability } from '../api/agents'
import { listMemories, removeMemory, saveMemory, type Memory } from '../api/memories'

const route = useRoute()
const router = useRouter()
const id = typeof route.params.id === 'string' ? route.params.id : undefined
const editing = !!id
const loading = ref(true)
const loaded = ref(false)
const saving = ref(false)
const refreshing = ref(false)
const advancedOpen = ref(false)
const capabilitiesOpen = ref(false)
const error = ref('')
const errors = ref<Record<string, string>>({})
const options = ref<AgentOptions>({ models: [], tools: [], skills: [], mcp_servers: [], skill_issues: [] })
const original = ref<AgentDetail | null>(null)
const memories = ref<Memory[]>([])
const memoryContent = ref('')
const editingMemoryId = ref<string | null>(null)
const savingMemory = ref(false)
const memoryDeleteOpen = ref(false)
const deletingMemory = ref<Memory | null>(null)
const memoryDeleteBusy = ref(false)
const memoryDeleteError = ref('')
const form = reactive({ name: '', description: '', system_prompt: '', model_id: '', max_rounds: '10', max_runtime_seconds: '300', max_tool_calls: '30', max_total_tokens: '', auto_compress: true, compression_trigger_percent: '80', compression_keep_recent_turns: '4', compression_summary_target_tokens: '1000', tool_ids: [] as string[], skill_ids: [] as string[], mcp_server_ids: [] as string[] })
const { markSaved } = useUnsavedChanges(() => JSON.stringify(form), loaded, saving)
const reason = (e: unknown) => e instanceof Error ? e.message : '操作失败，请重试。'
const definitions = [
  { key: 'tools', field: 'tool_ids', title: '本地工具', hint: '允许 Agent 使用的本地工具。', link: '/tools', label: '本地工具' },
  { key: 'skills', field: 'skill_ids', title: '任务技能', hint: '处理任务时可以参考的做事说明。', link: '/skills', label: '任务技能' },
  { key: 'mcp_servers', field: 'mcp_server_ids', title: '外部工具', hint: '为 Agent 提供外部工具的服务。', link: '/mcp', label: '外部工具' },
] as const
const groups = computed(() => definitions.map(group => {
  const items = new Map<string, Capability>(options.value[group.key].map(item => [item.id, item]))
  for (const item of original.value?.[group.key] ?? []) {
    if (!items.has(item.id)) items.set(item.id, { ...item, enabled: false, unavailable_reason: '文件缺失或无效，不可用' })
  }
  return { ...group, items: [...items.values()], originalIds: new Set(original.value?.[group.key].map(item => item.id) ?? []) }
}))
const promptChanged = computed(() => !!original.value && original.value.system_prompt !== form.system_prompt)
async function load() {
  loading.value = true
  error.value = ''
  try {
    // 先读详情再读最新选项，避免初始化 Skill 状态时交错请求。
    const agent = id ? await getAgent(id) : null
    const choices = await agentOptions()
    options.value = choices
    original.value = agent
    if (agent) {
      Object.assign(form, { name: agent.name, description: agent.description, system_prompt: agent.system_prompt, model_id: agent.model_id, max_rounds: String(agent.max_rounds), max_runtime_seconds: String(agent.max_runtime_seconds ?? 300), max_tool_calls: String(agent.max_tool_calls ?? 30), max_total_tokens: agent.max_total_tokens == null ? '' : String(agent.max_total_tokens), auto_compress: agent.auto_compress, compression_trigger_percent: String(Math.round(agent.compression_trigger_ratio * 100)), compression_keep_recent_turns: String(agent.compression_keep_recent_turns), compression_summary_target_tokens: String(agent.compression_summary_target_tokens), tool_ids: agent.tools.map(x => x.id), skill_ids: agent.skills.map(x => x.id), mcp_server_ids: agent.mcp_servers.map(x => x.id) })
      try { memories.value = await listMemories(agent.id) } catch { memories.value = [] }
    }
    else form.model_id = choices.models.find(item => item.id === route.query.model)?.id ?? choices.models.find(item => item.is_default)?.id ?? ''
    markSaved()
    loaded.value = true
  } catch (e) { error.value = reason(e) }
  finally { loading.value = false }
}
async function saveMemoryItem() {
  if (!id || !memoryContent.value.trim() || savingMemory.value) return
  savingMemory.value = true
  try { const saved = await saveMemory(id, memoryContent.value.trim(), editingMemoryId.value || undefined); memories.value = [saved, ...memories.value.filter(item => item.id !== saved.id)]; memoryContent.value = ''; editingMemoryId.value = null }
  catch (e) { error.value = reason(e) }
  finally { savingMemory.value = false }
}
function editMemory(item: Memory) { editingMemoryId.value = item.id; memoryContent.value = item.content }
function deleteMemory(item: Memory) {
  if (!id || memoryDeleteBusy.value) return
  deletingMemory.value = item; memoryDeleteError.value = ''; memoryDeleteOpen.value = true
}
async function confirmMemoryDelete() {
  const item = deletingMemory.value
  if (!id || !item || !memoryDeleteOpen.value || memoryDeleteBusy.value) return
  memoryDeleteBusy.value = true; memoryDeleteError.value = ''
  try {
    await removeMemory(id, item.id)
    memories.value = memories.value.filter(row => row.id !== item.id)
    if (editingMemoryId.value === item.id) { editingMemoryId.value = null; memoryContent.value = '' }
    memoryDeleteOpen.value = false
  } catch (e) { memoryDeleteError.value = reason(e) }
  finally { memoryDeleteBusy.value = false }
}
async function refreshOptions() {
  if (refreshing.value) return
  refreshing.value = true
  error.value = ''
  try {
    const refreshed = await agentOptions()
    for (const group of groups.value) {
      const present = new Set(refreshed[group.key].map(item => item.id))
      for (const item of group.items) {
        if (form[group.field].includes(item.id) && !present.has(item.id)) refreshed[group.key].push({ ...item, enabled: false, unavailable_reason: '已删除或失效，不可用' })
      }
    }
    options.value = refreshed
  }
  catch (e) { error.value = reason(e) }
  finally { refreshing.value = false }
}
async function focusError() {
  if (['tool_ids', 'skill_ids', 'mcp_server_ids'].some(key => errors.value[key])) capabilitiesOpen.value = true
  if (['max_rounds', 'max_runtime_seconds', 'max_tool_calls', 'max_total_tokens', 'compression_trigger_ratio', 'compression_keep_recent_turns', 'compression_summary_target_tokens'].some(key => errors.value[key])) advancedOpen.value = true
  await nextTick()
  document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()
}
async function submit() {
  if (saving.value || refreshing.value || !loaded.value) return
  errors.value = {}
  error.value = ''
  if (!form.name.trim()) errors.value.name = '请填写 Agent 名称。'
  if (!options.value.models.some(item => item.id === form.model_id)) errors.value.model_id = '请选择一个已配置的模型。'
  const rounds = Number(form.max_rounds)
  const runtimeSeconds = Number(form.max_runtime_seconds)
  const toolCalls = Number(form.max_tool_calls)
  const totalTokens = form.max_total_tokens.trim() ? Number(form.max_total_tokens) : null
  if (!form.max_rounds.trim() || !Number.isInteger(rounds) || rounds < 1 || rounds > 100) errors.value.max_rounds = '请输入 1 至 100 的正整数。'
  if (!Number.isInteger(runtimeSeconds) || runtimeSeconds < 1 || runtimeSeconds > 3600) errors.value.max_runtime_seconds = '请输入 1 至 3,600 秒的正整数。'
  if (!Number.isInteger(toolCalls) || toolCalls < 0 || toolCalls > 10000) errors.value.max_tool_calls = '请输入 0 至 10,000 的整数。'
  if (totalTokens !== null && (!Number.isInteger(totalTokens) || totalTokens < 1 || totalTokens > 100000000)) errors.value.max_total_tokens = '请输入 1 至 100,000,000 的正整数，或留空。'
  const trigger = Number(form.compression_trigger_percent)
  if (!form.compression_trigger_percent.trim() || !Number.isInteger(trigger) || trigger < 50 || trigger > 95) errors.value.compression_trigger_ratio = '请输入 50 至 95 的整数百分比。'
  const keep = Number(form.compression_keep_recent_turns)
  if (!form.compression_keep_recent_turns.trim() || !Number.isInteger(keep) || keep < 1 || keep > 50) errors.value.compression_keep_recent_turns = '请输入 1 至 50 的正整数。'
  const target = Number(form.compression_summary_target_tokens)
  if (!form.compression_summary_target_tokens.trim() || !Number.isInteger(target) || target < 128 || target > 32768) errors.value.compression_summary_target_tokens = '请输入 128 至 32,768 的正整数。'
  for (const group of groups.value) {
    if (form[group.field].some(key => !group.originalIds.has(key) && !group.items.some(item => item.id === key && item.enabled))) errors.value[group.field] = '新选能力已停用或失效，请取消选择后保存。'
  }
  if (errors.value.max_rounds || errors.value.max_runtime_seconds || errors.value.max_tool_calls || errors.value.max_total_tokens || errors.value.compression_trigger_ratio || errors.value.compression_keep_recent_turns || errors.value.compression_summary_target_tokens) advancedOpen.value = true
  if (Object.keys(errors.value).length) { await focusError(); return }
  saving.value = true
  try {
    await saveAgent({ name: form.name.trim(), description: form.description, system_prompt: form.system_prompt, model_id: form.model_id, max_rounds: rounds, max_runtime_seconds: runtimeSeconds, max_tool_calls: toolCalls, max_total_tokens: totalTokens, auto_compress: form.auto_compress, compression_trigger_ratio: trigger / 100, compression_keep_recent_turns: keep, compression_summary_target_tokens: target, tool_ids: form.tool_ids, skill_ids: form.skill_ids, mcp_server_ids: form.mcp_server_ids }, id)
    markSaved()
    await router.push('/agents')
  } catch (e) {
    error.value = reason(e)
    if (e instanceof ApiError) errors.value = e.fields
    saving.value = false
    await focusError()
  } finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <div class="module-page model-form-page agent-form-page">
    <RouterLink class="form-back" to="/agents">← 返回 Agent 管理</RouterLink>
    <PageHeader :title="editing ? '编辑 Agent' : '新建 Agent'" description="选择模型，写下任务要求，即可开始对话。" />
    <div v-if="error" class="model-feedback" role="alert"><p>{{ error }}</p><button v-if="!loaded" class="button button-ghost" :disabled="loading" @click="load">重新加载</button></div>
    <p v-if="loading" role="status">正在加载配置…</p>
    <form v-else-if="loaded" novalidate @submit.prevent="submit">
      <div v-if="!options.models.length" class="agent-model-notice" role="status"><p>暂无可用模型，请先添加模型，再保存 Agent。</p><RouterLink to="/models/new" class="button button-primary">前往模型连接</RouterLink></div>
      <div class="agent-editor-core">
      <section class="model-form-section agent-identity" aria-labelledby="agent-basic">
        <header class="form-section-heading"><span class="eyebrow">01</span><h2 id="agent-basic">任务与模型</h2><p class="form-section-note">为它命名，选择使用的模型。</p></header>
        <fieldset class="model-field-grid" :disabled="saving">
          <div class="model-field field-wide"><label for="name">名称 *</label><input id="name" v-model="form.name" maxlength="100" placeholder="例如：文档整理助手" :aria-invalid="!!errors.name" aria-describedby="name-error" /><p v-if="errors.name" id="name-error" class="field-error">{{ errors.name }}</p></div>
          <div class="model-field field-wide"><label for="model_id">使用模型 *</label><select id="model_id" v-model="form.model_id" :aria-invalid="!!errors.model_id" aria-describedby="model_id-error"><option disabled value="">请选择模型</option><option v-for="model in options.models" :key="model.id" :value="model.id">{{ model.name }} · {{ model.model_id }}{{ model.is_default ? '（默认模型）' : '' }}</option></select><p v-if="errors.model_id" id="model_id-error" class="field-error">{{ errors.model_id }}</p><RouterLink to="/models" class="agent-resource-link">管理模型 →</RouterLink></div>
          <div class="model-field field-wide"><label for="description">说明</label><textarea id="description" v-model="form.description" maxlength="2000" rows="2" placeholder="一句话描述用途（选填）" :aria-invalid="!!errors.description" aria-describedby="description-error" /><p v-if="errors.description" id="description-error" class="field-error">{{ errors.description }}</p></div>
        </fieldset>
      </section>

      <section class="model-form-section agent-instructions" aria-labelledby="agent-prompt">
        <header class="form-section-heading"><span class="eyebrow">02</span><h2 id="agent-prompt">任务要求</h2><p class="form-section-note">写清要做什么、怎样回答，以及需要遵守的限制。</p><p class="agent-version">{{ original?.prompt_version ? `当前版本 v${original.prompt_version}` : '首次保存生成 v1' }}</p></header>
        <div class="model-field"><label for="system_prompt">告诉它怎么做</label><textarea id="system_prompt" v-model="form.system_prompt" :disabled="saving" rows="9" maxlength="100000" placeholder="你将处理什么任务？应遵循哪些要求与限制？" :aria-invalid="!!errors.system_prompt" aria-describedby="prompt-hint system_prompt-error" /><p id="prompt-hint" class="field-hint">{{ form.system_prompt.length.toLocaleString() }} / 100,000 字符<span v-if="promptChanged"> · 保存后生成 v{{ original!.prompt_version + 1 }}</span></p><p v-if="errors.system_prompt" id="system_prompt-error" class="field-error">{{ errors.system_prompt }}</p></div>
      </section>
      </div>
      <details class="agent-advanced" :open="capabilitiesOpen" @toggle="capabilitiesOpen = ($event.currentTarget as HTMLDetailsElement).open">
        <summary><span>工具与技能</span><small>{{ form.tool_ids.length + form.skill_ids.length + form.mcp_server_ids.length }} 项已选</small></summary>
      <section class="model-form-section" aria-labelledby="agent-capabilities">
        <header class="form-section-heading"><h2 id="agent-capabilities">可用能力</h2><p class="form-section-note">只选择任务需要的能力。</p><button type="button" class="button button-ghost" :disabled="saving || refreshing" @click="refreshOptions">{{ refreshing ? '正在刷新…' : '刷新能力选项' }}</button></header>
        <div class="agent-capability-groups">
          <fieldset v-for="group in groups" :key="group.key" class="agent-capability-group" tabindex="-1" :aria-invalid="!!errors[group.field]" :disabled="saving || refreshing" :aria-describedby="`${group.field}-hint ${group.field}-error`">
            <legend>{{ group.title }} <span class="muted">{{ form[group.field].length }} 项已选</span></legend>
            <p :id="`${group.field}-hint`" class="field-hint"><RouterLink :to="group.link">管理{{ group.label }} →</RouterLink></p>
            <p v-if="!group.items.length" class="field-hint">暂无可选项，可前往管理页面添加或启用。</p>
            <div class="agent-capability-grid">
              <div v-for="item in group.items" :key="item.id" class="capability-tile" :class="{ 'is-selected': form[group.field].includes(item.id), 'is-unavailable': !item.enabled }">
                <label class="agent-capability-option">
                  <input v-model="form[group.field]" type="checkbox" :value="item.id" :disabled="!item.enabled && !group.originalIds.has(item.id) && !form[group.field].includes(item.id)" />
                  <span><strong>{{ item.name }}</strong><span class="agent-capability-description" :title="item.description">{{ item.description || '暂无用途说明' }}</span><span v-if="!item.enabled" class="agent-unavailable">{{ item.unavailable_reason || '已停用，不可用' }}</span></span>
                </label>
                <details v-if="item.description" class="capability-info"><summary :aria-label="`查看${item.name}说明`"><AppIcon name="info" /></summary><p>{{ item.description }}</p></details>
              </div>
            </div>
            <p v-if="errors[group.field]" :id="`${group.field}-error`" class="field-error" role="alert">{{ errors[group.field] }}</p>
          </fieldset>
          <div v-if="options.skill_issues.length" class="model-feedback" role="status"><p>部分 Skills 无法用于新增绑定：</p><p v-for="issue in options.skill_issues" :key="issue.directory">{{ issue.directory }}：{{ issue.message }}</p></div>
        </div>
      </section>
      </details>
      <details class="agent-advanced" :open="advancedOpen" @toggle="advancedOpen = ($event.currentTarget as HTMLDetailsElement).open">
        <summary><span>高级设置</span><small>轮数、预算、长对话压缩</small></summary>
      <section class="model-form-section" aria-labelledby="agent-context">
        <header class="form-section-heading"><h2 id="agent-context">运行与上下文容量</h2><p class="form-section-note">每次模型请求前按估算 Token 检查容量。压缩保留原始聊天记录，只更新发送给模型的摘要与边界。</p></header>
        <fieldset class="model-field-grid" :disabled="saving">
          <div class="model-field field-wide"><label for="max_rounds">最大执行轮数 *</label><input id="max_rounds" :value="form.max_rounds" @input="form.max_rounds = ($event.target as HTMLInputElement).value" type="number" min="1" max="100" step="1" :aria-invalid="!!errors.max_rounds" aria-describedby="rounds-hint max_rounds-error" /><p id="rounds-hint" class="field-hint">默认 10 轮，范围 1–100 的正整数。上下文压缩使用独立模型调用，不占用任务执行轮数。</p><p v-if="errors.max_rounds" id="max_rounds-error" class="field-error">{{ errors.max_rounds }}</p></div>
          <div class="model-field"><label for="max_runtime_seconds">最长运行时间（秒）*</label><input id="max_runtime_seconds" v-model="form.max_runtime_seconds" type="number" min="1" max="3600" step="1" :aria-invalid="!!errors.max_runtime_seconds" /><p class="field-hint">默认 300 秒，包含模型和工具等待时间。</p><p v-if="errors.max_runtime_seconds" class="field-error">{{ errors.max_runtime_seconds }}</p></div>
          <div class="model-field"><label for="max_tool_calls">最多工具调用次数 *</label><input id="max_tool_calls" v-model="form.max_tool_calls" type="number" min="0" max="10000" step="1" :aria-invalid="!!errors.max_tool_calls" /><p class="field-hint">默认 30 次；达到上限后停止本次运行。</p><p v-if="errors.max_tool_calls" class="field-error">{{ errors.max_tool_calls }}</p></div>
          <div class="model-field field-wide"><label for="max_total_tokens">本次 Token 预算</label><input id="max_total_tokens" v-model="form.max_total_tokens" type="number" min="1" max="100000000" step="1" :aria-invalid="!!errors.max_total_tokens" placeholder="留空表示不限制" /><p class="field-hint">按模型返回的 Token 用量累计；供应商未返回用量时以请求估算量保护。</p><p v-if="errors.max_total_tokens" class="field-error">{{ errors.max_total_tokens }}</p></div>
          <label class="agent-compression-switch"><input v-model="form.auto_compress" type="checkbox" /><span><strong>自动压缩</strong><span class="field-hint">接近可用输入容量时，用当前模型摘要较早的完整对话。关闭后超限会直接提示缩短内容或开启压缩。</span></span></label>
          <div class="model-field"><label for="compression_trigger_ratio">触发比例 *</label><div class="agent-percent-input"><input id="compression_trigger_ratio" :value="form.compression_trigger_percent" @input="form.compression_trigger_percent = ($event.target as HTMLInputElement).value" type="number" min="50" max="95" step="1" :aria-invalid="!!errors.compression_trigger_ratio" aria-describedby="trigger-hint compression_trigger_ratio-error" /><span>%</span></div><p id="trigger-hint" class="field-hint">默认 80%。基于可用输入容量触发，数值越低越早压缩。</p><p v-if="errors.compression_trigger_ratio" id="compression_trigger_ratio-error" class="field-error">{{ errors.compression_trigger_ratio }}</p></div>
          <div class="model-field"><label for="compression_keep_recent_turns">保留最近对话轮数 *</label><input id="compression_keep_recent_turns" :value="form.compression_keep_recent_turns" @input="form.compression_keep_recent_turns = ($event.target as HTMLInputElement).value" type="number" min="1" max="50" step="1" :aria-invalid="!!errors.compression_keep_recent_turns" aria-describedby="keep-hint compression_keep_recent_turns-error" /><p id="keep-hint" class="field-hint">默认 4 轮。每轮包含用户消息、对应回答及相关工具交互。</p><p v-if="errors.compression_keep_recent_turns" id="compression_keep_recent_turns-error" class="field-error">{{ errors.compression_keep_recent_turns }}</p></div>
          <div class="model-field field-wide"><label for="compression_summary_target_tokens">摘要目标长度 *</label><input id="compression_summary_target_tokens" :value="form.compression_summary_target_tokens" @input="form.compression_summary_target_tokens = ($event.target as HTMLInputElement).value" type="number" min="128" max="32768" step="1" :aria-invalid="!!errors.compression_summary_target_tokens" aria-describedby="summary-hint compression_summary_target_tokens-error" /><p id="summary-hint" class="field-hint">默认约 1000 Token。这是生成目标，实际长度可能不同；Runtime 会按所选模型的可用容量自动降低目标，避免小窗口被摘要占满。</p><p v-if="errors.compression_summary_target_tokens" id="compression_summary_target_tokens-error" class="field-error">{{ errors.compression_summary_target_tokens }}</p></div>
        </fieldset>
      </section>
      </details>
      <details v-if="id" class="agent-advanced"><summary><span>跨会话记忆</span><small>{{ memories.length }} 条</small></summary>
      <section class="model-form-section" aria-labelledby="agent-memory">
        <header class="form-section-heading"><span class="eyebrow">记忆</span><h2 id="agent-memory">跨会话记忆</h2><p class="form-section-note">只保存你明确确认的信息。运行时仅在当前问题相关时注入，可随时更正或删除。</p></header>
        <div v-for="item in memories" :key="item.id" class="evaluation-case"><p>{{ item.content }}</p><div><button type="button" class="button button-plain" @click="editMemory(item)">编辑</button><button type="button" class="button button-plain" @click="deleteMemory(item)">删除</button></div></div>
        <p v-if="!memories.length" class="field-hint">暂无已保存的记忆。</p>
        <div class="model-field"><label for="agent-memory-content">{{ editingMemoryId ? '编辑记忆' : '添加记忆' }}</label><textarea id="agent-memory-content" v-model="memoryContent" rows="3" maxlength="10000" placeholder="例如：偏好简洁中文回复。" /><div class="model-actions"><button type="button" class="button button-ghost" :disabled="savingMemory || !memoryContent.trim()" @click="saveMemoryItem">{{ savingMemory ? '正在保存…' : editingMemoryId ? '保存修改' : '记住这条' }}</button><button v-if="editingMemoryId" type="button" class="button button-plain" @click="editingMemoryId = null; memoryContent = ''">取消编辑</button></div></div>
      </section>
      </details>
      <div class="form-submit"><span class="muted">配置保存在本机。</span><div class="model-actions"><button type="button" class="button button-ghost" :disabled="saving" @click="router.push('/agents')">取消</button><button type="submit" class="button button-primary" :disabled="saving || refreshing || !options.models.length">{{ saving ? '正在保存…' : '保存 Agent' }}</button></div></div>
    </form>
    <footer class="page-footer"><span class="footer-note">配置完成后，可随时调整任务说明与能力。</span><ConnectionStatus /></footer>
    <DeleteDialog v-model="memoryDeleteOpen" title="删除这条跨会话记忆？" description="删除后不会再被召回。" :busy="memoryDeleteBusy" :error="memoryDeleteError" @confirm="confirmMemoryDelete" />
  </div>
</template>
