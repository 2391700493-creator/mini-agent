<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '../components/PageHeader.vue'
import ConnectionStatus from '../components/ConnectionStatus.vue'
import { getTool, toggleTool, type Tool, type Parameter } from '../api/tools'

const route = useRoute()
const tool = ref<Tool | null>(null)
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const reason = (e: unknown) => e instanceof Error ? e.message : '操作未完成，请重试。'
const typeLabel = (param: Parameter) => param.type ?? param.anyOf?.map(item => item.type).join(' / ') ?? '—'
const examples: Record<string, object> = {
  current_time: { arguments: { timezone: 'Asia/Shanghai' } },
  shell: { arguments: { command: 'uname -s', cwd: '.', timeout_seconds: 10 } },
  file: { arguments: { operation: 'create', path: 'note.txt', content: '这是文件内容。' } },
}
const example = computed(() => JSON.stringify(examples[String(route.params.id)], null, 2))
async function load() {
  loading.value = true
  error.value = ''
  try { tool.value = await getTool(String(route.params.id)) }
  catch (e) { error.value = reason(e) }
  finally { loading.value = false }
}
async function toggle() {
  if (!tool.value || busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    tool.value = await toggleTool(tool.value.id, !tool.value.enabled)
    notice.value = `已${tool.value.enabled ? '启用' : '停用'}「${tool.value.name}」。`
  } catch (e) { error.value = reason(e) }
  finally { busy.value = false }
}
onMounted(load)
</script>

<template>
  <div class="module-page tool-detail-page">
    <RouterLink to="/tools" class="form-back">← 返回工具管理</RouterLink>
    <PageHeader :title="tool?.name ?? '工具详情'" :description="tool?.description ?? '查看工具用途、输入参数和使用限制。'" />
    <p v-if="notice" class="model-notice" role="status">{{ notice }}</p>
    <div v-if="error" class="model-feedback" role="alert"><p>{{ error }}</p><button class="button button-ghost" :disabled="loading || busy" @click="load">重新加载</button></div>
    <p v-if="loading" class="model-loading" role="status">正在加载工具…</p>
    <template v-else-if="tool">
      <div class="tool-detail-status"><div><span class="subtle-tag">{{ tool.is_builtin ? '系统内置' : '自定义' }}</span><span class="muted">{{ tool.id }}</span></div><button class="tool-switch" role="switch" :aria-checked="tool.enabled" :aria-label="`${tool.name}启用状态`" :disabled="busy" @click="toggle"><span class="switch-track" :class="{ 'is-on': tool.enabled }" aria-hidden="true"><span /></span>{{ busy ? '保存中…' : tool.enabled ? '已启用' : '已停用' }}</button></div>
      <p v-if="!tool.available" class="model-feedback" role="alert">{{ tool.unavailable_reason }}</p>
      <aside class="tool-note tool-defaults"><p v-if="tool.defaults.timezone"><strong>默认时区</strong><span>{{ tool.defaults.timezone }}</span></p><p v-if="tool.defaults.root"><strong>授权目录</strong><span>{{ tool.defaults.root }}</span></p><p>系统内置工具的用途和参数不可修改，也不能删除。</p></aside>
      <section class="tool-section" aria-labelledby="parameters-title"><h2 id="parameters-title">输入参数</h2><dl class="tool-parameters"><div v-for="(param, key) in tool.input_schema.properties" :key="key"><dt>{{ key }} <span>{{ typeLabel(param) }} · {{ tool.input_schema.required?.includes(key) ? '必填' : '可选' }}</span></dt><dd>{{ param.description }}<p v-if="param.enum" class="muted">可选值：{{ param.enum.join(' / ') }}</p><p v-if="param.default != null" class="muted">默认值：{{ param.default }}</p></dd></div></dl></section>
      <section class="tool-section" aria-labelledby="limits-title"><h2 id="limits-title">使用限制</h2><ul class="tool-limits"><li v-for="limit in tool.limitations" :key="limit">{{ limit }}</li></ul></section>
      <section class="tool-section" aria-labelledby="example-title"><h2 id="example-title">调用示例</h2><div class="tool-example"><p class="muted">POST /api/tools/{{ tool.id }}/execute</p><pre>{{ example }}</pre><p class="field-hint">以上为参数示例，尚未执行。返回结果包含是否成功、结果代码、说明、数据与耗时。</p></div></section>
    </template>
    <footer class="page-footer"><span class="footer-note">所有本地调用均通过统一执行入口校验。</span><ConnectionStatus /></footer>
  </div>
</template>
