<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import PageHeader from '../components/PageHeader.vue'
import ConnectionStatus from '../components/ConnectionStatus.vue'
import AppIcon from '../components/AppIcon.vue'
import { listRuns, type RunAgentOption, type RunMetrics, type RunModelOption, type RunStatus, type RunSummary } from '../api/runs'

const runs = ref<RunSummary[]>([])
const agents = ref<RunAgentOption[]>([])
const models = ref<RunModelOption[]>([])
const metrics = ref<RunMetrics | null>(null)
const total = ref(0)
const page = ref(1)
const pageSize = 20
const status = ref<RunStatus | ''>('')
const agentId = ref('')
const modelId = ref('')
const source = ref<'chat' | 'evaluation' | ''>('')
const startedAfter = ref('')
const startedBefore = ref('')
const loading = ref(true)
const error = ref('')
let revision = 0
const pages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const reason = (e: unknown) => e instanceof Error ? e.message : '运行记录加载失败，请重试。'
const statusLabel: Record<RunStatus, string> = { running: '运行中', success: '成功', partial: '部分完成', failed: '失败', cancelled: '已取消' }
const statusOptions: { value: RunStatus | ''; label: string }[] = [
  { value: '', label: '全部' },
  { value: 'running', label: '运行中' },
  { value: 'success', label: '成功' },
  { value: 'partial', label: '部分完成' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
]
const date = (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false })
const duration = (value: number | null) => value === null ? '—' : value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(value < 10000 ? 1 : 0)} s`
const tokens = (run: RunSummary) => run.usage_status === 'unknown' ? '未知' : `${run.total_tokens?.toLocaleString('zh-CN') ?? '未知'}${run.usage_status === 'incomplete' ? ' · 不完整' : ''}`
const cost = (run: RunSummary) => run.cost_status === 'complete' && typeof run.cost === 'number' ? `${run.cost_currency || ''} ${run.cost.toFixed(6)}`.trim() : run.cost_status === 'incomplete' ? '不完整' : '未知'
async function load() {
  const current = ++revision
  loading.value = true
  error.value = ''
  try {
    const result = await listRuns({ page: page.value, pageSize, status: status.value || undefined, agentId: agentId.value || undefined, modelId: modelId.value || undefined, source: source.value || undefined, startedAfter: startedAfter.value ? new Date(startedAfter.value).toISOString() : undefined, startedBefore: startedBefore.value ? new Date(startedBefore.value).toISOString() : undefined })
    if (current !== revision) return
    runs.value = Array.isArray(result?.items) ? result.items : []
    total.value = typeof result?.total === 'number' ? result.total : 0
    agents.value = Array.isArray(result?.agents) ? result.agents : []
    models.value = Array.isArray(result?.models) ? result.models : []
    metrics.value = result?.metrics || null
  } catch (e) { if (current === revision) error.value = reason(e) }
  finally { if (current === revision) loading.value = false }
}
watch([status, agentId, modelId, source, startedAfter, startedBefore], () => { page.value = 1; void load() })
onMounted(load)
</script>

<template>
  <div class="module-page runs-page">
    <PageHeader title="运行记录" description="查看每次 Agent 请求的结果、耗时和执行步骤。" />
    <div class="runs-toolbar" aria-label="运行筛选">
      <div class="runs-filter-head">
        <fieldset class="runs-status-filter">
          <legend>状态</legend>
          <div class="runs-status-options">
            <button v-for="option in statusOptions" :key="option.value || 'all'" type="button" class="runs-status-option" :class="{ 'is-active': status === option.value }" :aria-pressed="status === option.value" @click="status = option.value">{{ option.label }}</button>
          </div>
        </fieldset>
        <button class="button button-ghost runs-refresh" :disabled="loading" @click="load"><AppIcon name="refresh" />刷新</button>
      </div>
      <div class="runs-filter-grid">
        <label class="runs-select-filter"><span>Agent</span><select v-model="agentId"><option value="">全部 Agent</option><option v-for="agent in agents" :key="agent.id" :value="agent.id">{{ agent.name }}</option></select></label>
        <label class="runs-select-filter"><span>模型</span><select v-model="modelId"><option value="">全部模型</option><option v-for="model in models" :key="model.id || model.name" :value="model.id || ''">{{ model.name }}</option></select></label>
        <label class="runs-select-filter"><span>来源</span><select v-model="source"><option value="">全部来源</option><option value="chat">聊天</option><option value="evaluation">评测</option></select></label>
        <fieldset class="runs-date-filter">
          <legend>时间范围</legend>
          <div class="runs-date-range">
            <label><span>开始</span><input v-model="startedAfter" type="datetime-local" /></label>
            <span class="runs-date-separator" aria-hidden="true">至</span>
            <label><span>结束</span><input v-model="startedBefore" type="datetime-local" /></label>
          </div>
        </fieldset>
      </div>
    </div>
    <div v-if="error" class="model-feedback" role="alert"><p>{{ error }}</p><button class="button button-ghost" @click="load">重新加载</button></div>
    <p v-if="loading" class="model-loading" role="status">正在加载运行记录…</p>
    <section v-if="!loading && !error && metrics && metrics.total > 0" class="evaluation-stats" aria-label="运行指标">
      <span>当前页样本 {{ metrics.total }}</span><span>成功率 {{ metrics.success_rate === null ? '—' : `${metrics.success_rate}%` }}</span><span>P95 耗时 {{ duration(metrics.p95_duration_ms) }}</span><span>平均首字 {{ duration(metrics.first_output_ms) }}</span><span>Token {{ metrics.total_tokens?.toLocaleString('zh-CN') || '—' }}</span><span>工具错误率 {{ metrics.tool_error_rate === null ? '—' : `${metrics.tool_error_rate}%` }}</span><span>成本 {{ metrics.total_cost === null ? '—' : `${metrics.cost_currency || ''} ${metrics.total_cost.toFixed(6)}`.trim() }}</span><span>成本不完整 {{ metrics.incomplete_cost_runs }}</span>
    </section>
    <section v-if="!loading && !error && runs.length" aria-label="运行记录列表">
      <div class="model-list-heading"><h2>全部运行 <span>{{ total }}</span></h2><span class="muted">按开始时间倒序</span></div>
      <div class="runs-table-wrap">
        <table class="runs-table">
          <thead><tr><th>状态</th><th>Agent / 模型</th><th>开始时间</th><th>耗时</th><th>调用</th><th>Token</th><th>成本</th><th>错误摘要</th></tr></thead>
          <tbody><tr v-for="run in runs" :key="run.id">
            <td><RouterLink :to="`/runs/${run.id}`" class="run-status-link"><span class="run-status" :class="`is-${run.status}`"><span />{{ statusLabel[run.status] }}</span></RouterLink></td>
            <td><RouterLink :to="`/runs/${run.id}`" class="run-identity"><strong>{{ run.agent_name }}</strong><span>{{ run.model_name || '模型快照缺失' }}</span></RouterLink></td>
            <td><time :datetime="run.started_at">{{ date(run.started_at) }}</time></td>
            <td>{{ duration(run.duration_ms) }}</td>
            <td><span class="run-call-count">模型 {{ run.model_call_count }}</span><span class="run-call-count">工具 {{ run.tool_call_count }}</span></td>
            <td>{{ tokens(run) }}</td><td>{{ cost(run) }}</td>
            <td class="run-error-cell">{{ run.error_summary || '—' }}</td>
          </tr></tbody>
        </table>
      </div>
      <nav class="runs-pagination" aria-label="分页"><button class="button button-ghost" :disabled="page <= 1 || loading" @click="page--; load()">上一页</button><span>第 {{ page }} / {{ pages }} 页</span><button class="button button-ghost" :disabled="page >= pages || loading" @click="page++; load()">下一页</button></nav>
    </section>
    <section v-else-if="!loading && !error" class="runs-empty"><h2>暂无匹配记录</h2><p>调整筛选条件，或开始一次对话后回到这里查看执行过程。</p><RouterLink to="/chat" class="button button-primary">前往聊天 <AppIcon name="arrow" /></RouterLink></section>
    <footer class="page-footer"><span class="footer-note">打开记录查看完整执行过程。</span><ConnectionStatus /></footer>
  </div>
</template>
