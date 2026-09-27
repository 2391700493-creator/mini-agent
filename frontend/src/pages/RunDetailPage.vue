<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import { eventPayload, removeRun, runDetail, type RunDetail, type RunEvent, type RunEventPayload, type RunStatus } from '../api/runs'
import MarkdownMessage from '../components/MarkdownMessage.vue'
import DeleteDialog from '../components/DeleteDialog.vue'

type TimelineItem = { key: string; sequence: number; kind: string; title: string; status: string; meta: string; summary: string; event?: RunEvent; payloadEvents?: RunEvent[] }
const route = useRoute()
const run = ref<RunDetail | null>(null)
const loading = ref(true)
const error = ref('')
const payloads = ref<Record<number, RunEventPayload>>({})
const payloadLoading = ref<number | null>(null)
const deleting = ref(false)
const deleteOpen = ref(false)
const deleteError = ref('')
function askDelete() { if (!deleting.value) { deleteError.value = ''; deleteOpen.value = true } }
const statusLabel: Record<RunStatus, string> = { running: '运行中', success: '成功', partial: '部分完成', failed: '失败', cancelled: '已取消' }
const reason = (e: unknown) => e instanceof Error ? e.message : '运行详情加载失败，请重试。'
const duration = (value: number | null | undefined) => value == null ? '—' : value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(value < 10000 ? 1 : 0)} s`
const date = (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false })
const dataString = (event: RunEvent, key: string) => typeof event.data[key] === 'string' ? String(event.data[key]) : ''
const dataNumber = (event: RunEvent, key: string) => typeof event.data[key] === 'number' ? Number(event.data[key]) : null
const usageText = (event: RunEvent) => {
  const usage = event.data.usage as Record<string, unknown> | null
  if (!usage) return 'Token 未返回'
  const input = typeof usage.prompt_tokens === 'number' ? usage.prompt_tokens : '未知'
  const output = typeof usage.completion_tokens === 'number' ? usage.completion_tokens : '未知'
  const cached = typeof usage.cached_input_tokens === 'number' ? `，缓存命中 ${usage.cached_input_tokens}（已含在输入中）` : ''
  return `输入 ${input}，输出 ${output}${cached}`
}
const cost = computed(() => {
  if (!run.value || run.value.cost_status !== 'complete' || typeof run.value.cost !== 'number') return run.value?.cost_status === 'incomplete' ? '统计不完整' : '未知'
  return `${run.value.cost_currency || ''} ${run.value.cost.toFixed(6)}`.trim()
})
const timeline = computed<TimelineItem[]>(() => {
  if (!run.value) return []
  const events = run.value.events
  const terminal = run.value.status !== 'running'
  const items: TimelineItem[] = []
  const byCall = new Map<string, RunEvent>()
  for (const event of events) if (event.call_id && ['model_end', 'tool_result', 'compression_success', 'compression_failure'].includes(event.type)) byCall.set(event.call_id, event)
  for (const event of events) {
    if (event.type === 'run_start') items.push({ key: `start-${event.sequence}`, sequence: event.sequence, kind: 'agent', title: run.value.agent_name, status: 'completed', meta: 'Agent 开始', summary: '已载入运行配置并开始处理请求。', event })
    if (event.type === 'model_start' && event.call_id) {
      const end = byCall.get(event.call_id)
      const status = end ? dataString(end, 'status') || 'failed' : terminal ? 'failed' : 'running'
      const purpose = dataString(event, 'purpose') === 'context_compression' ? '上下文压缩' : `第 ${event.round ?? '—'} 轮`
      const failure = end ? dataString(end, 'failure_reason') : terminal ? '运行中断，模型请求未正常结束。' : '正在等待模型返回。'
      items.push({ key: event.call_id, sequence: event.sequence, kind: 'model', title: dataString(event, 'model_name') || run.value.model_name || '模型请求', status, meta: `${purpose} · ${duration(end ? dataNumber(end, 'duration_ms') : null)}`, summary: status === 'completed' && end ? usageText(end) : failure, event: end || event })
    }
    if (event.type === 'tool_start' && event.call_id) {
      const end = byCall.get(event.call_id)
      const status = end ? dataString(end, 'status') || 'failed' : terminal ? 'failed' : 'running'
      const server = dataString(event, 'server_name')
      const rejected = end?.data.executed === false ? '请求在权限或参数校验阶段被拒绝，未计入工具执行次数。' : ''
      items.push({ key: event.call_id, sequence: event.sequence, kind: 'tool', title: dataString(event, 'display_name') || '工具', status, meta: `${server ? `${server} · ` : ''}${duration(end ? dataNumber(end, 'duration_ms') : null)}`, summary: end ? `${dataString(end, 'summary')}${rejected ? ` ${rejected}` : ''}` : terminal ? '运行中断，工具步骤未正常结束。' : dataString(event, 'input_summary'), event: end || event, payloadEvents: [event, end].filter((item): item is RunEvent => Boolean(item?.has_payload)) })
    }
    if (['compression_start', 'context_fallback'].includes(event.type)) {
      const outcome = event.type === 'compression_start' && event.call_id ? byCall.get(event.call_id) : undefined
      const contextStatus = outcome?.type === 'compression_failure' ? 'failed' : outcome ? 'completed' : event.type === 'context_fallback' ? 'completed' : terminal ? 'failed' : 'running'
      items.push({ key: `context-${event.sequence}`, sequence: event.sequence, kind: 'context', title: event.type === 'compression_start' ? '上下文压缩' : '上下文备用处理', status: contextStatus, meta: duration(dataNumber(outcome || event, 'duration_ms')), summary: `处理 ${dataNumber(outcome || event, 'processed_message_count') ?? 0} 条历史消息。`, event: outcome || event })
    }
    if (event.type === 'run_error') items.push({ key: `error-${event.sequence}`, sequence: event.sequence, kind: 'error', title: '运行错误', status: 'failed', meta: '', summary: dataString(event, 'reason') || '运行失败。', event })
  }
  const output = [...events].reverse().find(event => event.type === 'text_delta')
  if (output) items.push({ key: 'answer', sequence: output.sequence, kind: 'answer', title: run.value.status === 'success' ? '最终回答' : '未完成回答', status: run.value.status === 'success' ? 'completed' : run.value.status, meta: '', summary: run.value.final_answer || '正文未可靠保存。', event: output })
  const end = events.find(event => event.type === 'run_end')
  if (end) items.push({ key: `end-${end.sequence}`, sequence: end.sequence, kind: 'end', title: '运行结束', status: dataString(end, 'status'), meta: duration(run.value.duration_ms), summary: dataString(end, 'reason') || run.value.end_reason || '运行已结束。', event: end })
  return items.sort((a, b) => a.sequence - b.sequence)
})
async function load() {
  loading.value = true; error.value = ''
  try { run.value = await runDetail(String(route.params.id)) }
  catch (e) { error.value = reason(e) }
  finally { loading.value = false }
}
async function loadPayload(event: RunEvent) {
  if (payloads.value[event.sequence] || payloadLoading.value !== null) return
  payloadLoading.value = event.sequence
  try { payloads.value[event.sequence] = await eventPayload(event.run_id, event.sequence) }
  catch (e) { error.value = reason(e) }
  finally { payloadLoading.value = null }
}
async function remove() {
  if (!run.value || deleting.value || !deleteOpen.value || run.value.status === 'running') return
  deleting.value = true
  deleteError.value = ''
  try { await removeRun(run.value.id); deleteOpen.value = false; window.history.back() }
  catch (e) { deleteError.value = reason(e) }
  finally { deleting.value = false }
}
onMounted(load)
</script>

<template>
  <div class="module-page run-detail-page">
    <RouterLink to="/runs" class="form-back"><AppIcon name="arrow" />返回运行记录</RouterLink>
    <p v-if="loading" class="model-loading" role="status">正在加载运行详情…</p>
    <div v-else-if="error && !run" class="model-feedback" role="alert"><p>{{ error }}</p><button class="button button-ghost" @click="load">重新加载</button></div>
    <template v-else-if="run">
      <header class="run-detail-header"><div><span class="run-status" :class="`is-${run.status}`"><span />{{ statusLabel[run.status] }}</span><h1 id="page-title" tabindex="-1">{{ run.agent_name }}</h1><p>{{ run.model_name || '模型快照缺失' }}<span v-if="run.model_identifier"> · {{ run.model_identifier }}</span></p></div><div><time :datetime="run.started_at">{{ date(run.started_at) }}</time><button v-if="run.status !== 'running'" class="button button-plain" :disabled="deleting" @click="askDelete">{{ deleting ? '正在删除…' : '删除记录' }}</button></div></header>
      <dl class="run-summary-grid">
        <div><dt>总耗时</dt><dd>{{ duration(run.duration_ms) }}</dd></div><div><dt>模型调用</dt><dd>{{ run.model_call_count }}</dd></div><div><dt>工具执行</dt><dd>{{ run.tool_call_count }}</dd></div>
        <div><dt>Token 用量</dt><dd>{{ run.usage_status === 'unknown' ? '未知' : `${run.total_tokens ?? '未知'}${run.usage_status === 'incomplete' ? ' · 统计不完整' : ''}` }}</dd></div><div><dt>成本</dt><dd>{{ cost }}</dd></div><div><dt>首个输出</dt><dd>{{ run.first_output_ms === null ? (run.status === 'running' ? '等待正文' : '无正文输出') : duration(run.first_output_ms) }}</dd></div><div><dt>结束原因</dt><dd>{{ run.end_reason || (run.status === 'running' ? '仍在运行' : '—') }}</dd></div>
      </dl>
      <section v-if="run.status === 'failed' || run.status === 'partial'" class="run-recovery" aria-label="下一步"><div><strong>这次运行没有完整完成</strong><p>先查看时间线中的失败步骤；若问题来自模型或能力配置，可回到 Agent 编辑页调整后再次发起对话。</p></div><RouterLink :to="`/agents/${run.agent_id}/edit`" class="button button-ghost">检查 Agent 配置</RouterLink></section>
      <section class="run-timeline" aria-labelledby="timeline-title"><div class="model-list-heading"><h2 id="timeline-title">时间线 <span>{{ timeline.length }}</span></h2><span class="muted">按真实事件顺序</span></div>
        <ol><li v-for="item in timeline" :key="item.key" :class="[`is-${item.status}`, `is-${item.kind}`]">
          <span class="timeline-marker" aria-hidden="true" /><article><header><div><span class="timeline-kind">{{ item.kind === 'model' ? '模型' : item.kind === 'tool' ? '工具' : item.kind === 'answer' ? '正文' : item.kind === 'error' ? '错误' : item.kind === 'context' ? '上下文' : '运行' }}</span><h3>{{ item.title }}</h3></div><span>{{ item.meta }}</span></header><MarkdownMessage v-if="item.kind === 'answer'" :content="item.summary" /><p v-else>{{ item.summary }}</p>
          <template v-for="payloadEvent in item.payloadEvents || []" :key="payloadEvent.sequence"><button v-if="!payloads[payloadEvent.sequence]" class="tool-process-more" :disabled="payloadLoading !== null" @click="loadPayload(payloadEvent)">{{ payloadLoading === payloadEvent.sequence ? '正在加载…' : payloadEvent.type === 'tool_start' ? '查看输入' : '查看结果' }}</button><pre v-else>{{ JSON.stringify(payloads[payloadEvent.sequence]?.payload, null, 2) }}</pre></template>
          </article>
        </li></ol>
      </section>
      <p v-if="error" class="chat-error" role="alert">{{ error }}</p>
    </template>
    <DeleteDialog v-model="deleteOpen" title="删除这条运行记录？" description="运行记录及其事件载荷将被删除，聊天消息会保留。" :busy="deleting" :error="deleteError" @confirm="remove" />
  </div>
</template>
