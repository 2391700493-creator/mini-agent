<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Presentation, ToolProcess } from '../api/chat'

const props = defineProps<{ process: ToolProcess }>()
const expanded = ref(false)
const opened = ref<Record<string, boolean>>({})
const previewLimit = 2400

const statusText = computed(() => ({
  running: '正在执行', completed: '执行成功', failed: '执行失败', cancelled: '已取消', unknown: '状态未知',
}[props.process.status]))
const duration = computed(() => props.process.duration_ms === null ? '' : props.process.duration_ms < 1000 ? `${props.process.duration_ms} 毫秒` : `${(props.process.duration_ms / 1000).toFixed(1)} 秒`)

function printable(presentation: Presentation | null) {
  if (!presentation) return '暂无可展示内容。'
  return typeof presentation.value === 'string' ? presentation.value : JSON.stringify(presentation.value, null, 2)
}
function clipped(key: string, presentation: Presentation | null) {
  const value = printable(presentation)
  return !opened.value[key] && value.length > previewLimit ? `${value.slice(0, previewLimit)}\n\n（内容较长，展开后查看全部）` : value
}
function hasMore(key: string, presentation: Presentation | null) {
  return printable(presentation).length > previewLimit && !opened.value[key]
}
</script>

<template>
  <section class="tool-process" :class="`is-${process.status}`" :aria-label="`${process.name}：${statusText}`">
    <button class="tool-process-toggle" type="button" :aria-expanded="expanded" @click="expanded = !expanded">
      <span class="tool-process-status" aria-hidden="true"></span>
      <span class="tool-process-heading">
        <span v-if="process.server_name" class="tool-process-server">{{ process.server_name }}</span>
        <span>{{ process.name }}</span>
      </span>
      <span class="tool-process-state">{{ statusText }}<template v-if="duration"> · {{ duration }}</template></span>
      <span class="tool-process-chevron" aria-hidden="true">⌄</span>
    </button>
    <p v-if="expanded || process.status === 'failed'" class="tool-process-summary">{{ process.summary }}</p>
    <div v-if="expanded" class="tool-process-details">
      <section>
        <h4>输入参数</h4>
        <pre>{{ clipped('input', process.input) }}</pre>
        <button v-if="hasMore('input', process.input)" type="button" class="tool-process-more" @click="opened.input = true">查看全部</button>
        <p v-if="process.input?.truncated" class="tool-process-notice">{{ process.input.notice || '输入内容过长，未展示全部。' }}</p>
      </section>
      <section>
        <h4>执行结果</h4>
        <pre>{{ clipped('result', process.result) }}</pre>
        <button v-if="hasMore('result', process.result)" type="button" class="tool-process-more" @click="opened.result = true">查看全部</button>
        <p v-if="process.result?.truncated" class="tool-process-notice">{{ process.result.notice || '结果内容过长，未展示全部。' }}</p>
      </section>
    </div>
  </section>
</template>
