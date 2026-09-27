<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import ResourceGuideCard from '../components/ResourceGuideCard.vue'
import PageHeader from '../components/PageHeader.vue'
import ConnectionStatus from '../components/ConnectionStatus.vue'
import AppIcon from '../components/AppIcon.vue'
import { deleteModel, listModels, setDefaultModel, testModel, type LanguageModel, type ConnectionResult } from '../api/models'

const models = ref<LanguageModel[]>([])
const loading = ref(true)
const error = ref('')
const notice = ref('')
const busy = ref(false)
const deleting = ref<string | null>(null)
const deletingModel = computed(() => models.value.find(model => model.id === deleting.value))
const deleteDialog = ref<HTMLDialogElement>()
const deleteCancel = ref<HTMLButtonElement>()
const replacement = ref('')
const testing = ref(new Set<string>())
const results = ref<Record<string, ConnectionResult>>({})
const date = (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false })
const reason = (e: unknown) => e instanceof Error ? e.message : '操作未完成，请重试。'

async function load() {
  loading.value = true
  error.value = ''
  try { models.value = await listModels() }
  catch (e) { error.value = reason(e) }
  finally { loading.value = false }
}
async function makeDefault(model: LanguageModel) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await setDefaultModel(model.id)
    notice.value = `已将「${model.display_name}」设为默认模型。`
    await load()
  } catch (e) { error.value = reason(e) }
  finally { busy.value = false }
}
async function confirmDelete(model: LanguageModel) {
  if (busy.value || testing.value.has(model.id)) return
  error.value = ''
  deleting.value = model.id
  replacement.value = ''
  await nextTick()
  deleteDialog.value?.showModal()
  deleteCancel.value?.focus()
}
async function cancelDelete() {
  if (busy.value) return
  const id = deleting.value
  deleteDialog.value?.close()
  deleting.value = null
  await nextTick()
  document.getElementById(`delete-${id}`)?.focus()
}
async function remove(model: LanguageModel) {
  if (busy.value || (model.is_default && models.value.length > 1 && !replacement.value)) return
  busy.value = true
  error.value = ''
  try {
    await deleteModel(model.id, replacement.value)
    notice.value = `已删除「${model.display_name}」及其密钥。`
    deleteDialog.value?.close()
    deleting.value = null
    await load()
    await nextTick()
    document.getElementById('page-title')?.focus()
  } catch (e) { error.value = reason(e) }
  finally { busy.value = false }
}
async function test(model: LanguageModel) {
  if (testing.value.has(model.id)) return
  testing.value.add(model.id)
  delete results.value[model.id]
  try { results.value[model.id] = await testModel(model.id) }
  catch (e) {
    results.value[model.id] = { success: false, code: 'local_error', message: reason(e), suggestion: '确认本地服务可用后重试。', reply: null }
  } finally { testing.value.delete(model.id) }
}
onMounted(load)
</script>

<template>
  <div class="module-page models-page">
    <div class="models-header">
      <PageHeader title="模型连接" description="连接模型，配置参数，验证每一次调用。" />
      <RouterLink to="/models/new" class="button button-primary"><AppIcon name="add" />添加模型</RouterLink>
    </div>
    <p v-if="notice" class="model-notice" role="status">{{ notice }}</p>
    <div v-if="error && !deleting" class="model-feedback" role="alert">
      <p>{{ error }}</p><button class="button button-ghost" :disabled="loading || busy" @click="load">重新加载</button>
    </div>
    <p v-if="loading" class="model-loading" role="status">正在加载模型…</p>
    <div v-else-if="!models.length && !error" class="resource-grid"><RouterLink class="resource-empty-card" to="/models/new"><AppIcon name="model" /><strong>添加第一个模型</strong><span>填写服务地址、模型名称和 API Key。</span></RouterLink></div>
    <section v-else-if="models.length" aria-label="已添加的模型">
      <div class="model-list-heading"><h2>已添加的模型 <span>{{ models.length }}</span></h2><span class="muted">OpenAI 兼容接口</span></div>
      <div class="management-list resource-grid">
      <article v-for="model in models" :key="model.id" class="model-card management-row model-row resource-card" :aria-label="model.display_name">
        <div class="model-card-heading"><h3><RouterLink class="resource-main-link" :to="`/models/${model.id}/edit`">{{ model.display_name }}</RouterLink></h3><span v-if="model.is_default" class="default-tag"><span class="status-dot is-connected" aria-hidden="true" />默认模型</span></div>
        <dl class="model-facts">
          <div><dt>模型标识</dt><dd>{{ model.model_id }}</dd></div>
          <div class="model-url"><dt>服务地址</dt><dd>{{ model.base_url }}</dd></div>
          <div><dt>上下文长度</dt><dd>{{ model.context_length.toLocaleString() }} <span class="muted">token</span></dd></div>
          <div><dt>API Key</dt><dd>{{ model.key_configured ? '已配置' : '未配置' }}</dd></div>
        </dl>
        <div class="model-card-footer">
          <div class="model-actions">
            <button class="button button-ghost" :disabled="testing.has(model.id) || busy || deleting === model.id" @click="test(model)"><AppIcon :name="testing.has(model.id) ? 'refresh' : 'check'" :class="{ spinning: testing.has(model.id) }" />{{ testing.has(model.id) ? '正在测试' : '测试连接' }}</button>
            <RouterLink :to="`/models/${model.id}/edit`" class="button button-plain">编辑</RouterLink>
            <button v-if="!model.is_default" class="button button-plain" :disabled="busy || !!deleting" @click="makeDefault(model)">设为默认</button>
          </div>
          <div class="model-card-maintenance"><time class="model-updated" :datetime="model.updated_at">更新于 {{ date(model.updated_at) }}</time><button :id="`delete-${model.id}`" class="button button-plain button-danger" :disabled="busy || testing.has(model.id)" @click="confirmDelete(model)">删除</button></div>
        </div>
        <div v-if="testing.has(model.id)" class="model-test-result" role="status">正在向模型发送真实请求，请稍候…</div>
        <div v-else-if="results[model.id]" class="model-test-result" :role="results[model.id]!.success ? 'status' : 'alert'">
          <strong>{{ results[model.id]!.message }}</strong>
          <p v-if="results[model.id]!.suggestion">{{ results[model.id]!.suggestion }}</p>
          <blockquote v-if="results[model.id]!.reply">{{ results[model.id]!.reply }}</blockquote><RouterLink v-if="results[model.id]!.success" class="text-link" :to="{ path: '/agents/new', query: { model: model.id } }">用这个模型创建 Agent →</RouterLink>
        </div>

      </article>
      <ResourceGuideCard title="连接新的模型" description="为 Agent 添加一个可用模型。" icon="model" :steps="['填写服务地址与模型名称', '配置 API Key', '测试连接后用于 Agent']" action="添加模型" to="/models/new" />
      </div>
    </section>
    <dialog ref="deleteDialog" id="delete-confirmation" class="conversation-dialog model-delete-dialog" aria-labelledby="model-delete-title" aria-describedby="model-delete-description" @cancel.prevent="cancelDelete">
      <template v-if="deletingModel">
        <h2 id="model-delete-title">删除「{{ deletingModel.display_name }}」？</h2>
        <p id="model-delete-description">{{ deletingModel.is_default && models.length > 1 ? '这是当前默认模型，请先选择新的默认模型。切换与删除将一起完成。' : models.length === 1 ? '这是最后一个模型。删除后将清除默认模型设置，页面回到空状态。' : '模型配置和保存的密钥将一起删除。' }}</p>
        <label v-if="deletingModel.is_default && models.length > 1" class="replacement-label" for="replacement">新的默认模型
          <select id="replacement" v-model="replacement" :disabled="busy"><option disabled value="">请选择模型</option><option v-for="other in models.filter(item => item.id !== deleting)" :key="other.id" :value="other.id">{{ other.display_name }} · {{ other.model_id }}</option></select>
        </label>
        <p v-if="error" class="field-error" role="alert">{{ error }}</p>
        <div class="model-actions"><button ref="deleteCancel" class="button button-ghost" :disabled="busy" @click="cancelDelete">取消</button><button class="button button-primary" :disabled="busy || (deletingModel.is_default && models.length > 1 && !replacement)" @click="remove(deletingModel)">{{ busy ? '正在删除…' : '确认删除' }}</button></div>
      </template>
    </dialog>
    <footer class="page-footer"><span class="footer-note">密钥加密保存在本机，保存后不再显示。</span><ConnectionStatus /></footer>
  </div>
</template>
