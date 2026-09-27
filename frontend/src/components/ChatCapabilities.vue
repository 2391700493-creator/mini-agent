<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { getAgent, type AgentDetail } from '../api/agents'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ agentId?: string | null }>()
const dialog = ref<HTMLDialogElement>()
const detail = ref<AgentDetail>()
const loading = ref(false)
const error = ref('')
let revision = 0
const groups = computed(() => detail.value ? [
  { label: '工具', items: detail.value.tools },
  { label: 'Skills · 任务说明', items: detail.value.skills },
  { label: 'MCP · 外部能力', items: detail.value.mcp_servers },
] : [])
watch(() => props.agentId, () => { revision++; detail.value = undefined; if (dialog.value?.open) dialog.value.close() })
async function load() {
  if (!props.agentId) return
  const current = ++revision
  loading.value = true; error.value = ''; detail.value = undefined
  try {
    const result = await getAgent(props.agentId)
    if (current === revision) detail.value = result
  } catch (cause) {
    if (current === revision) error.value = cause instanceof Error ? cause.message : '未能读取 Agent 能力，请重试。'
  } finally { if (current === revision) loading.value = false }
}
function open() { dialog.value?.showModal(); void load() }
defineExpose({ open })
</script>

<template>
  <dialog ref="dialog" class="workspace-dialog" aria-labelledby="capabilities-title">
    <div class="dialog-heading"><h2 id="capabilities-title">当前 Agent 的能力</h2><button type="button" class="icon-button" aria-label="关闭能力面板" @click="dialog?.close()">×</button></div>
    <p class="dialog-intro">Agent 会按任务需要使用已绑定且启用的能力。这里查看配置，实际执行前会再次检查可用状态。</p>
    <p v-if="loading" role="status">正在读取配置…</p>
    <div v-else-if="error" role="alert"><p>{{ error }}</p><button type="button" class="button button-plain" @click="load">重试</button></div>
    <template v-else-if="detail">
      <p class="capability-model">{{ detail.name }} <span>· {{ detail.model_name }}</span></p>
      <section v-for="group in groups" :key="group.label" class="capability-section">
        <h3>{{ group.label }} <span>{{ group.items.filter(item => item.enabled && !item.unavailable_reason).length }} 项可用</span></h3>
        <p v-if="!group.items.length" class="muted">尚未绑定</p>
        <div v-for="item in group.items" :key="item.id" class="capability-item"><strong>{{ item.name }}</strong><span v-if="!item.enabled || item.unavailable_reason" class="muted">{{ item.unavailable_reason || '已停用' }}</span><p>{{ item.description }}</p></div>
      </section>
      <RouterLink :to="`/agents/${encodeURIComponent(detail.id)}/edit`" class="button button-primary" @click="dialog?.close()">调整 Agent 能力<AppIcon name="arrow" /></RouterLink>
    </template>
  </dialog>
</template>
