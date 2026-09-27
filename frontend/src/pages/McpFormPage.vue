<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import PageHeader from '../components/PageHeader.vue'
import ConnectionStatus from '../components/ConnectionStatus.vue'
import { getMcp, importMcpJson, updateMcpJson, type McpServer } from '../api/mcp'

const route = useRoute()
const router = useRouter()
const id = typeof route.params.id === 'string' ? route.params.id : undefined
const configuration = ref('')
const loading = ref(!!id)
const loaded = ref(!id)
const saving = ref(false)
const testing = ref(false)
const error = ref('')
const original = ref('')
const dirty = computed(() => loaded.value && configuration.value !== original.value)
const locked = computed(() => loading.value || saving.value || testing.value)
const reason = (e: unknown) => e instanceof Error ? e.message : '操作失败，请重试。'
const example = JSON.stringify({ mcpServers: { example: { command: 'node', args: ['server.js'], env: { API_KEY: 'your-key' } } } }, null, 2)

function editableConfiguration(item: McpServer) {
  const server: Record<string, unknown> = { command: item.command, args: item.args }
  if (item.description) server.description = item.description
  const keys = Object.keys(item.env)
  if (keys.length) server.env = Object.fromEntries(keys.map(key => [key, null]))
  return JSON.stringify({ mcpServers: { [item.name]: server } }, null, 2)
}

async function load() {
  if (!id) return
  loading.value = true
  error.value = ''
  try {
    const item = await getMcp(id)
    configuration.value = editableConfiguration(item)
    testing.value = item.testing
    loaded.value = true
    original.value = configuration.value
  } catch (e) { error.value = reason(e) }
  finally { loading.value = false }
}

async function submit() {
  if (locked.value || !configuration.value.trim()) return
  error.value = ''
  saving.value = true
  try {
    if (id) await updateMcpJson(id, configuration.value)
    else await importMcpJson(configuration.value)
    configuration.value = ''
    original.value = ''
    await router.push('/mcp')
  } catch (e) { error.value = reason(e) }
  finally { saving.value = false }
}

function shortcut(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
    event.preventDefault()
    void submit()
  }
}

onBeforeRouteLeave(() => {
  if (saving.value && dirty.value) return false
  if (dirty.value) return window.confirm('有尚未保存的修改，确定离开？')
})
onMounted(load)
onUnmounted(() => { configuration.value = '' })
</script>

<template>
  <div class="module-page mcp-json-page">
    <RouterLink class="form-back" to="/mcp">← 返回 外部工具</RouterLink>
    <PageHeader :title="id ? '编辑外部工具' : '连接外部工具'" description="粘贴工具提供的连接配置。" />
    <div v-if="error" class="model-feedback" role="alert"><p>{{ error }}</p><button v-if="!loaded" class="button button-ghost" :disabled="loading" @click="load">重新加载</button></div>
    <div v-if="testing" class="model-feedback" role="status"><p>该 Server 正在测试，测试结束后才能修改。</p><button class="button button-ghost" :disabled="loading" @click="load">重新加载</button></div>
    <p v-if="loading" class="model-loading" role="status">正在读取配置…</p>
    <form v-if="loaded" class="mcp-json-form" @submit.prevent="submit">
      <label for="mcp-json">JSON 配置</label>
      <textarea id="mcp-json" v-model="configuration" class="mcp-json-editor" rows="10" maxlength="1048576" :placeholder="example" :disabled="locked" :aria-invalid="!!error" aria-describedby="mcp-json-hint" autocomplete="off" spellcheck="false" @keydown="shortcut" />
      <details class="skills-format"><summary>配置说明</summary><p id="mcp-json-hint" class="field-hint">环境变量会加密保存。编辑时，值为 <code>null</code> 表示保留原值。每次只保存一个 Server。</p></details>
      <div class="form-submit"><span class="muted">{{ id ? '保存后需要重新测试连接。' : '导入后默认停用。' }}</span><div class="model-actions"><button type="button" class="button button-ghost" :disabled="saving" @click="router.push('/mcp')">取消</button><button type="submit" class="button button-primary" :disabled="locked || !configuration.trim()">{{ saving ? '正在保存…' : id ? '保存修改' : '导入配置' }}</button></div></div>
    </form>
    <footer class="page-footer"><ConnectionStatus /></footer>
  </div>
</template>
