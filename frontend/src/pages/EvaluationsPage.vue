<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '../components/PageHeader.vue'
import { createTask, evaluationOptions, getDataset, getTask, listDatasets, listTasks, removeCase, removeDataset, removeTask, retryFailed, reviewTaskCase, saveCase, saveDataset, startTask, stopTask, type HistoryMessage, type Dataset, type DatasetDetail, type EvaluationOptions, type EvaluationTask, type TaskCase, type TaskDetail, type TestCase } from '../api/evaluations'

const route = useRoute()
const caseAdvancedOpen = ref(false)
const caseEditorOpen = ref(false)
const taskAdvancedOpen = ref(false)
const taskFormOpen = ref(true)
const loaded = ref(false)
const datasets = ref<Dataset[]>([]); const tasks = ref<EvaluationTask[]>([]); const options = ref<EvaluationOptions>({ agents: [], models: [] })
const selectedDataset = ref<DatasetDetail | null>(null); const selectedTask = ref<TaskDetail | null>(null); const section = ref<'datasets' | 'tasks'>('datasets')
const loading = ref(false); const error = ref(''); const datasetForm = ref({ name: '', description: '' }); const caseForm = ref({ question: '', expected_answer: '', grading_criteria: '' }); const editingCase = ref<string | null>(null)
const history = ref<HistoryMessage[]>([]); const historyError = ref(''); const expectedToolsText = ref(''); const maxToolCalls = ref<number | null>(null); const maxDurationMs = ref<number | null>(null)
const taskForm = ref({ dataset_id: '', agent_id: '', scoring_model_id: '', passing_score: 60, tools_allowed: false }); let timer: number | undefined
const datasetMode = ref<'view' | 'new' | 'edit'>('view')
const pending = ref('')
const busy = computed(() => pending.value !== '')
const reviewDialog = ref<HTMLDialogElement | null>(null)
const deleteDialog = ref<HTMLDialogElement>()
const deleteCancel = ref<HTMLButtonElement>()
const deletion = ref<{ title: string; description: string; operation: () => Promise<void> } | null>(null)
let deleteTrigger: HTMLElement | null = null
async function askDelete(title: string, description: string, operation: () => Promise<void>) {
  if (busy.value) return
  deleteTrigger = document.activeElement as HTMLElement
  error.value = ''
  deletion.value = { title, description, operation }
  await nextTick(); deleteDialog.value?.showModal(); deleteCancel.value?.focus()
}
function cancelDelete() {
  if (busy.value) return
  deleteDialog.value?.close(); deletion.value = null
  if (deleteTrigger?.isConnected) deleteTrigger.focus()
  else document.getElementById('page-title')?.focus()
}
async function confirmDelete() {
  if (!deletion.value || busy.value) return
  await deletion.value.operation()
  if (!error.value) cancelDelete()
}
const review = ref<{ taskId: string; caseId: string; status: 'confirmed' | 'dismissed' } | null>(null)
const reviewNote = ref('')
const reviewError = ref('')
let reviewTrigger: HTMLElement | null = null
async function perform(action: string, operation: () => Promise<void>) {
  if (busy.value) return
  pending.value = action
  error.value = ''
  try { await operation() } catch (e) { error.value = msg(e) }
  finally { pending.value = '' }
}
function newDataset() {
  if (busy.value) return
  selectedDataset.value = null
  datasetForm.value = { name: '', description: '' }
  datasetMode.value = 'new'
  resetCase()
}
const msg = (e: unknown) => e instanceof Error ? e.message : '操作失败，请重试。'
const status: Record<string, string> = { pending: '待运行', running: '运行中', completed: '已完成', interrupted: '已中断', executing: '执行中', grading: '评分中', passed: '通过', failed: '未通过', execution_failed: '执行失败', grading_failed: '评分失败' }
const runnableDatasets = computed(() => datasets.value.filter(item => item.case_count > 0))
const canStart = computed(() => loaded.value && !loading.value && runnableDatasets.value.some(item => item.id === taskForm.value.dataset_id) && options.value.agents.some(item => item.id === taskForm.value.agent_id) && options.value.models.some(item => item.id === taskForm.value.scoring_model_id))
const selectedCaseCount = computed(() => datasets.value.find(item => item.id === taskForm.value.dataset_id)?.case_count ?? 0)
const hasRunning = computed(() => tasks.value.some(x => x.status === 'running'))
async function load() {
  loading.value = true; error.value = ''
  try {
    const [ds, ts, opts] = await Promise.all([listDatasets(), listTasks(), evaluationOptions()])
    datasets.value = Array.isArray(ds) ? ds : []
    tasks.value = Array.isArray(ts) ? ts : []
    options.value = { agents: Array.isArray(opts?.agents) ? opts.agents : [], models: Array.isArray(opts?.models) ? opts.models : [] }
    if (!runnableDatasets.value.some(item => item.id === taskForm.value.dataset_id)) taskForm.value.dataset_id = runnableDatasets.value[0]?.id ?? ''
    if (!options.value.agents.some(item => item.id === taskForm.value.agent_id)) taskForm.value.agent_id = options.value.agents[0]?.id ?? ''
    if (!options.value.models.some(item => item.id === taskForm.value.scoring_model_id)) taskForm.value.scoring_model_id = options.value.models[0]?.id ?? ''
    if (!loaded.value && typeof route.query.agent === 'string') {
      if (options.value.agents.some(item => item.id === route.query.agent)) {
        taskForm.value.agent_id = route.query.agent
        section.value = 'tasks'
      } else error.value = '这个 Agent 已不可用，请重新选择。'
    }
    loaded.value = true
  } catch (e) { error.value = msg(e) }
  finally { loading.value = false }
}
async function prepareTask(datasetId?: string) {
  if (busy.value) return
  if (datasetId) taskForm.value.dataset_id = datasetId
  selectedTask.value = null
  taskFormOpen.value = true
  section.value = 'tasks'
  await nextTick()
  document.getElementById('evaluation-agent')?.focus()
}
async function resumeTask() {
  if (!selectedTask.value || selectedTask.value.status !== 'pending') return
  const id = selectedTask.value.id
  await perform('start', async () => { await startTask(id); await load(); await pickTask(id) })
}
async function pickDataset(id: string) {
  try {
    selectedDataset.value = await getDataset(id)
    selectedTask.value = null
    taskFormOpen.value = true
    section.value = 'datasets'
    datasetMode.value = 'view'
    resetCase()
    caseEditorOpen.value = selectedDataset.value.cases.length === 0
  } catch (e) { error.value = msg(e) }
}
async function pickTask(id: string) {
  try { selectedTask.value = await getTask(id); selectedDataset.value = null; section.value = 'tasks'; taskFormOpen.value = false }
  catch (e) { error.value = msg(e) }
}
async function saveDatasetForm() {
  if (datasetMode.value === 'view') return
  const id = datasetMode.value === 'edit' ? selectedDataset.value?.id : undefined
  if (datasetMode.value === 'edit' && !id) return
  await perform('dataset', async () => {
    const item = await saveDataset({ ...datasetForm.value }, id)
    await load()
    await pickDataset(item.id)
  })
}
function editDataset() {
  if (!selectedDataset.value || busy.value) return
  datasetForm.value = { name: selectedDataset.value.name, description: selectedDataset.value.description }
  datasetMode.value = 'edit'
}
async function deleteDataset() {
  if (busy.value || !selectedDataset.value) return
  const id = selectedDataset.value.id
  await askDelete(`删除「${selectedDataset.value.name}」？`, '数据集和其中的测试用例将被永久删除。', () => perform('delete-dataset', async () => { await removeDataset(id); selectedDataset.value = null; datasetMode.value = 'view'; await load() }))
}
function resetCase() {
  caseEditorOpen.value = false
  editingCase.value = null
  caseForm.value = { question: '', expected_answer: '', grading_criteria: '' }
  caseAdvancedOpen.value = false
  history.value = []; historyError.value = ''; expectedToolsText.value = ''; maxToolCalls.value = null; maxDurationMs.value = null
}
function editCase(item: TestCase) {
  caseEditorOpen.value = true
  caseAdvancedOpen.value = !!(item.history?.length || item.process_rules?.expected_tool_ids?.length || item.process_rules?.max_tool_calls != null || item.process_rules?.max_duration_ms != null)
  editingCase.value = item.id
  caseForm.value = { question: item.question, expected_answer: item.expected_answer || '', grading_criteria: item.grading_criteria || '' }
  history.value = (item.history || []).map(message => ({ ...message }))
  historyError.value = ''
  expectedToolsText.value = item.process_rules?.expected_tool_ids?.join(', ') || ''
  maxToolCalls.value = item.process_rules?.max_tool_calls ?? null
  maxDurationMs.value = item.process_rules?.max_duration_ms ?? null
}
async function saveCaseForm() {
  if (!selectedDataset.value || busy.value) return
  const invalid = history.value.flatMap((message, index) => !['user', 'assistant'].includes(message.role) || !message.content.trim() ? [index + 1] : [])
  historyError.value = invalid.length ? `第 ${invalid.join('、')} 条历史消息缺少正文，请填写或移除。` : ''
  if (historyError.value) { caseAdvancedOpen.value = true; return }
  const id = selectedDataset.value.id
  await perform('case', async () => {
    await saveCase(id, { question: caseForm.value.question, expected_answer: caseForm.value.expected_answer || null, grading_criteria: caseForm.value.grading_criteria || null, history: history.value.map(message => ({ ...message })), process_rules: { expected_tool_ids: expectedToolsText.value.split(',').map(x => x.trim()).filter(Boolean), max_tool_calls: maxToolCalls.value, max_duration_ms: maxDurationMs.value } }, editingCase.value || undefined)
    await pickDataset(id)
    await load()
  })
}
async function deleteCase(item: TestCase) {
  if (busy.value || !selectedDataset.value) return
  const id = selectedDataset.value.id
  await askDelete('删除这条测试用例？', '此用例将从数据集中永久移除。', () => perform('delete-case', async () => { await removeCase(id, item.id); await pickDataset(id); await load() }))
}
async function createAndStart() {
  if (!canStart.value || busy.value) return
  await perform('start', async () => {
    const task = await createTask({ ...taskForm.value })
    try { await startTask(task.id) }
    catch (e) { await load(); await pickTask(task.id); throw e }
    await load(); await pickTask(task.id)
  })
}
async function refreshDetail() {
  if (busy.value || reviewDialog.value?.open || selectedTask.value?.status !== 'running') return
  const id = selectedTask.value.id
  try {
    const detail = await getTask(id)
    if (busy.value || selectedTask.value?.id !== id) return
    selectedTask.value = detail
    tasks.value = tasks.value.map(task => task.id === id ? detail : task)
  }
  catch { /* 后续轮询重试，保留已展示的结果。 */ }
}
async function stopSelectedTask() {
  if (!selectedTask.value || selectedTask.value.status !== 'running') return
  const id = selectedTask.value.id
  await perform('stop', async () => { selectedTask.value = await stopTask(id); await load() })
}
async function retrySelectedTask() {
  if (!selectedTask.value) return
  const id = selectedTask.value.id
  await perform('retry', async () => { selectedTask.value = await retryFailed(id); await load() })
}
async function deleteSelectedTask() {
  if (busy.value || !selectedTask.value || selectedTask.value.status === 'running') return
  const id = selectedTask.value.id
  await askDelete('删除这项评测任务？', '这项任务及其评测结果将被永久删除。', () => perform('delete-task', async () => { await removeTask(id); selectedTask.value = null; taskFormOpen.value = true; await load() }))
}
async function reviewCase(item: TaskCase, value: 'confirmed' | 'dismissed') {
  if (!selectedTask.value || busy.value) return
  reviewTrigger = document.activeElement instanceof HTMLElement ? document.activeElement : null
  review.value = { taskId: selectedTask.value.id, caseId: item.id, status: value }
  reviewNote.value = item.review_note || ''; reviewError.value = ''
  await nextTick()
  reviewDialog.value?.showModal()
}
function closeReview() {
  if (busy.value) return
  reviewDialog.value?.close()
}
function restoreReviewFocus() { review.value = null; reviewTrigger?.focus() }
async function submitReview() {
  if (!review.value || busy.value) return
  const target = { ...review.value }
  pending.value = 'review'; reviewError.value = ''
  try {
    selectedTask.value = await reviewTaskCase(target.taskId, target.caseId, { review_status: target.status, review_note: reviewNote.value || null })
    reviewDialog.value?.close()
  } catch (e) { reviewError.value = msg(e) }
  finally { pending.value = '' }
}
watch(hasRunning, active => { if (timer) window.clearInterval(timer); if (active) timer = window.setInterval(() => void refreshDetail(), 1500) }, { immediate: true })
onMounted(load); onBeforeUnmount(() => { if (timer) window.clearInterval(timer) })
</script>

<template>
  <div class="module-page evaluations-page">
    <PageHeader title="Agent 评测" description="用一组问题检查 Agent 的回答，找到需要改进的地方。" />
    <div class="evaluation-tabs"><button :disabled="busy" :class="{ active: section === 'datasets' }" :aria-pressed="section === 'datasets'" @click="section = 'datasets'">数据集</button><button :disabled="busy" :class="{ active: section === 'tasks' }" :aria-pressed="section === 'tasks'" @click="section = 'tasks'">评测任务</button></div>
    <div v-if="error && !deletion" class="model-feedback" role="alert"><p>{{ error }}</p><button class="button button-ghost" :disabled="loading || busy" @click="load">重新加载</button></div>
    <p v-if="loading" role="status">正在加载评测…</p>
    <div v-if="loaded && section === 'datasets'" class="evaluation-layout">
      <aside class="evaluation-list"><button class="button button-ghost" :disabled="busy" @click="newDataset">新建数据集</button><button :disabled="busy" v-for="item in datasets" :key="item.id" class="evaluation-list-item" :class="{ active: selectedDataset?.id === item.id }" :aria-pressed="selectedDataset?.id === item.id" @click="pickDataset(item.id)"><strong>{{ item.name }}</strong><span>{{ item.case_count }} 条用例</span></button><p v-if="!datasets.length && !loading" class="muted">还没有测试问题。</p></aside>
      <div class="evaluation-detail">
        <form v-if="datasetMode !== 'view'" class="evaluation-form evaluation-card" @submit.prevent="saveDatasetForm">
          <h2>{{ datasetMode === 'edit' ? '编辑数据集' : '新建数据集' }}</h2>
          <label>名称<input v-model="datasetForm.name" :disabled="busy" required maxlength="100" /></label>
          <label>说明<textarea v-model="datasetForm.description" :disabled="busy" maxlength="5000" /></label>
          <div><button class="button button-primary" :disabled="busy">{{ pending === 'dataset' ? '正在保存…' : '保存数据集' }}</button><button type="button" class="button button-plain" :disabled="busy" @click="datasetMode = 'view'">取消</button></div>
        </form>
        <section v-else-if="!selectedDataset" class="evaluation-intro">
          <h2>先选一组测试问题</h2>
          <p>数据集就是一组问题和判断标准。先查看用例，再交给 Agent 回答并评分。</p>
          <button v-if="runnableDatasets.length" class="button button-primary" :disabled="busy" @click="pickDataset(runnableDatasets[0]!.id)">查看{{ runnableDatasets[0]!.name }}</button>
          <button v-else class="button button-primary" :disabled="busy" @click="newDataset">新建数据集</button>
          <p class="field-hint">基础能力示例用于熟悉流程；实际效果需要用你的任务验证。</p>
        </section>
        <template v-if="selectedDataset && datasetMode === 'view'"><section class="evaluation-card"><div class="evaluation-card-head"><div><h2>{{ selectedDataset.name }}</h2><p>{{ selectedDataset.description || '暂无说明' }}</p></div><div class="model-actions"><button :disabled="busy || !selectedDataset.cases.length" class="button button-primary" @click="prepareTask(selectedDataset.id)">用这组问题评测</button><button :disabled="busy" class="button button-ghost" @click="editDataset">编辑信息</button><button :disabled="busy" class="button button-plain" @click="deleteDataset">删除数据集</button></div></div><div v-for="item in selectedDataset.cases" :key="item.id" class="evaluation-case"><strong>用例 {{ item.position }}</strong><p>{{ item.question }}</p><small>期望：{{ item.expected_answer || '—' }}　要求：{{ item.grading_criteria || '—' }}</small><div><button :disabled="busy" class="button button-plain" @click="editCase(item)">编辑</button><button :disabled="busy" class="button button-plain" @click="deleteCase(item)">删除</button></div></div><button class="button button-ghost" :disabled="busy" @click="resetCase(); caseEditorOpen = true">添加用例</button></section><form v-if="caseEditorOpen" class="evaluation-card evaluation-form" @submit.prevent="saveCaseForm"><h2>{{ editingCase ? '编辑用例' : '添加用例' }}</h2><label>用户问题<textarea :disabled="busy" v-model="caseForm.question" required /></label><label>期望答案<textarea :disabled="busy" v-model="caseForm.expected_answer" placeholder="例如：只回答 3" /></label><label>评分要求<textarea :disabled="busy" v-model="caseForm.grading_criteria" placeholder="例如：结果正确，只输出数字，不附加解释。" /></label><p class="field-hint">期望答案和评分要求至少填写一项。</p><details class="evaluation-advanced" :open="caseAdvancedOpen" @toggle="caseAdvancedOpen = ($event.currentTarget as HTMLDetailsElement).open"><summary>历史消息与过程检查（选填）</summary><div class="evaluation-form"><fieldset class="evaluation-history" :disabled="busy"><legend>历史消息</legend>
          <div v-for="(message, index) in history" :key="index" class="evaluation-history-row">
            <label>第 {{ index + 1 }} 条角色<select :disabled="busy" v-model="message.role"><option value="user">用户</option><option value="assistant">助手</option></select></label>
            <label>消息正文<textarea :disabled="busy" v-model="message.content" :aria-invalid="!!historyError && !message.content.trim()" aria-describedby="history-error" /></label>
            <button :disabled="busy" type="button" class="button button-plain" @click="history.splice(index, 1)">移除第 {{ index + 1 }} 条</button>
          </div>
          <p v-if="historyError" id="history-error" class="field-error" role="alert">{{ historyError }}</p>
          <button :disabled="busy" type="button" class="button button-ghost" @click="history.push({ role: 'user', content: '' })">添加历史消息</button>
        </fieldset><label>期望工具<input :disabled="busy" v-model="expectedToolsText" placeholder="local__current_time, mcp__…" /></label><label>最多工具调用<input :disabled="busy" v-model.number="maxToolCalls" type="number" min="0" /></label><label>最长耗时（ms）<input :disabled="busy" v-model.number="maxDurationMs" type="number" min="1" /></label><p class="field-hint">历史消息按顺序发送；工具标识可从运行详情查看，用英文逗号分隔。</p></div></details><div><button class="button button-primary" :disabled="busy">{{ pending === 'case' ? '正在保存…' : '保存用例' }}</button><button :disabled="busy" type="button" class="button button-plain" @click="resetCase">取消</button></div></form></template>
      </div>
    </div>
    <div v-else-if="loaded" class="evaluation-layout">
      <aside class="evaluation-list"><button class="button button-ghost" :disabled="busy" @click="prepareTask()">新建评测</button><button :disabled="busy" v-for="item in tasks" :key="item.id" class="evaluation-list-item" :class="{ active: selectedTask?.id === item.id }" :aria-pressed="selectedTask?.id === item.id" @click="pickTask(item.id)"><strong>{{ item.agent_name }}</strong><span>{{ item.dataset_name }} · {{ status[item.status] }}</span></button><p v-if="!tasks.length" class="muted">暂无评测任务。</p></aside>
      <div class="evaluation-detail">
        <div v-if="!options.models.length || !options.agents.length || !runnableDatasets.length" class="evaluation-prerequisites">
          <p v-if="!options.models.length">先配置一个模型，用于回答问题和评分。 <RouterLink class="text-link" to="/models/new">添加模型 →</RouterLink></p>
          <p v-else-if="!options.agents.length">先创建要测试的 Agent。 <RouterLink class="text-link" to="/agents/new">创建 Agent →</RouterLink></p>
          <p v-else>数据集至少需要一条用例。 <button class="button button-plain" @click="section = 'datasets'">添加测试问题 →</button></p>
        </div>
        <form v-if="taskFormOpen && options.agents.length && options.models.length" class="evaluation-card evaluation-form" @submit.prevent="createAndStart"><h2>开始一次评测</h2><label>待评测 Agent<select id="evaluation-agent" :disabled="busy" v-model="taskForm.agent_id" required><option v-for="agent in options.agents" :key="agent.id" :value="agent.id">{{ agent.name }}</option></select></label><label>数据集<select :disabled="busy" v-model="taskForm.dataset_id" required><option v-for="dataset in runnableDatasets" :key="dataset.id" :value="dataset.id">{{ dataset.name }}（{{ dataset.case_count }}）</option></select></label><label>评分模型<span class="field-hint">负责按标准打分，可与 Agent 使用同一个模型；评分供参考。</span><select :disabled="busy" v-model="taskForm.scoring_model_id" required><option v-for="model in options.models" :key="model.id" :value="model.id">{{ model.name }}</option></select></label><details class="evaluation-advanced" :open="taskAdvancedOpen" @toggle="taskAdvancedOpen = ($event.currentTarget as HTMLDetailsElement).open"><summary>评分设置 · {{ taskForm.passing_score }} 分通过</summary><label>通过分数<input :disabled="busy" v-model.number="taskForm.passing_score" type="number" min="0" max="100" required /></label></details><label class="evaluation-check"><input :disabled="busy" v-model="taskForm.tools_allowed" type="checkbox" />允许目标 Agent 使用已绑定且启用的工具与 MCP</label><p class="field-hint">工具默认关闭，Skills 仍按需加载。开启工具后可能读写文件或调用外部服务。</p><p class="field-hint">将逐条回答 {{ selectedCaseCount }} 个问题并评分，会产生模型调用费用。</p><button class="button button-primary" :disabled="busy || !canStart">{{ pending === 'start' ? '正在启动…' : '开始评测' }}</button></form>
        <section v-if="selectedTask" class="evaluation-card"><div class="evaluation-card-head"><div><h2>{{ selectedTask.agent_name }} · {{ selectedTask.dataset_name }}</h2><p>{{ status[selectedTask.status] }} · 评分模型：{{ selectedTask.scoring_model_name }} · 通过线 {{ selectedTask.passing_score }}</p></div><div><button :disabled="busy" v-if="selectedTask.status === 'running'" class="button button-ghost" @click="stopSelectedTask">{{ pending === 'stop' ? '正在停止…' : '停止评测' }}</button><button :disabled="busy" v-else-if="selectedTask.status === 'pending'" class="button button-primary" @click="resumeTask">{{ pending === 'start' ? '正在启动…' : '继续启动' }}</button><button :disabled="busy" v-else-if="selectedTask.stats.failed + selectedTask.stats.execution_failed + selectedTask.stats.grading_failed > 0" class="button button-ghost" @click="retrySelectedTask">{{ pending === 'retry' ? '正在重跑…' : '仅重跑失败项' }}</button><button :disabled="busy" class="button button-ghost" @click="pickTask(selectedTask!.id)">刷新</button><button :disabled="busy" v-if="selectedTask.status !== 'running'" class="button button-plain" @click="deleteSelectedTask">删除</button></div></div><p class="field-hint">模型评分供参考。展开未通过的用例查看原因，再调整 Agent 并新建评测验证。</p><RouterLink class="text-link" :to="`/agents/${selectedTask.agent_id}/edit`">调整 Agent →</RouterLink><div class="evaluation-stats"><span>总数 {{ selectedTask.stats.total }}</span><span>已完成 {{ selectedTask.stats.completed }}</span><span>通过 {{ selectedTask.stats.passed }}</span><span>未通过 {{ selectedTask.stats.failed }}</span><span>执行失败 {{ selectedTask.stats.execution_failed }}</span><span>评分失败 {{ selectedTask.stats.grading_failed }}</span><span>平均分 {{ selectedTask.stats.average_score === null ? '暂无评分' : selectedTask.stats.average_score.toFixed(1) }}</span></div><details v-for="item in selectedTask.cases" :key="item.id" class="evaluation-result"><summary><span>用例 {{ item.position }}</span><span :class="`evaluation-status is-${item.status}`">{{ status[item.status] }}</span><span>{{ item.score === null ? '—' : `${item.score} 分` }}</span></summary><dl><dt>问题</dt><dd>{{ item.question }}</dd><dt>期望答案</dt><dd>{{ item.expected_answer || '—' }}</dd><dt>评分要求</dt><dd>{{ item.grading_criteria || '—' }}</dd><dt>过程规则</dt><dd>期望工具：{{ item.process_rules?.expected_tool_ids?.join('、') || '—' }}；最多工具调用：{{ item.process_rules?.max_tool_calls ?? '—' }}；最长耗时：{{ item.process_rules?.max_duration_ms ?? '—' }} ms</dd><dt>实际回答</dt><dd>{{ item.answer || '—' }}</dd><dt>评分理由</dt><dd>{{ item.reason || '—' }}</dd><dt>评分调用</dt><dd>{{ item.grading_attempts }} 次 · Token {{ item.scoring_total_tokens ?? '—' }}{{ item.scoring_usage_complete === false ? '（不完整）' : '' }}</dd><dt>错误原因</dt><dd>{{ item.error || '—' }}</dd><dt>问题分类 / 复核</dt><dd>{{ item.issue_category || '—' }} · {{ item.review_status === 'confirmed' ? '已确认' : item.review_status === 'dismissed' ? '已驳回' : '未复核' }} {{ item.review_note || '' }} <button :disabled="busy" v-if="['failed', 'execution_failed', 'grading_failed'].includes(item.status)" class="button button-plain" @click="reviewCase(item, 'confirmed')">确认</button><button :disabled="busy" v-if="['failed', 'execution_failed', 'grading_failed'].includes(item.status)" class="button button-plain" @click="reviewCase(item, 'dismissed')">驳回</button></dd><dt>Run</dt><dd><RouterLink v-if="item.run_id" :to="`/runs/${item.run_id}`" class="text-link">查看运行详情</RouterLink><span v-else>—</span></dd></dl></details></section>
      </div>
    </div>
    <dialog ref="deleteDialog" class="conversation-dialog evaluation-delete-dialog" aria-labelledby="evaluation-delete-title" aria-describedby="evaluation-delete-description" @cancel.prevent="cancelDelete">
      <template v-if="deletion">
        <h2 id="evaluation-delete-title">{{ deletion.title }}</h2><p id="evaluation-delete-description">{{ deletion.description }}</p>
        <p v-if="error" class="field-error" role="alert">{{ error }}</p>
        <div class="model-actions"><button ref="deleteCancel" class="button button-ghost" :disabled="busy" @click="cancelDelete">取消</button><button class="button button-primary" :disabled="busy" @click="confirmDelete">{{ busy ? '正在删除…' : '确认删除' }}</button></div>
      </template>
    </dialog>
    <dialog ref="reviewDialog" class="conversation-dialog" aria-labelledby="review-title" @cancel.prevent="closeReview" @close="restoreReviewFocus">
      <form class="evaluation-form" @submit.prevent="submitReview">
        <h2 id="review-title">{{ review?.status === 'confirmed' ? '确认问题' : '驳回问题' }}</h2>
        <label>复核备注（选填）<textarea v-model="reviewNote" :disabled="busy" autofocus /></label>
        <p v-if="reviewError" role="alert" class="field-error">{{ reviewError }}</p>
        <div><button type="button" class="button button-ghost" :disabled="busy" @click="closeReview">取消</button><button class="button button-primary" :disabled="busy">{{ pending === 'review' ? '正在提交…' : '提交复核' }}</button></div>
      </form>
    </dialog>
  </div>
</template>
