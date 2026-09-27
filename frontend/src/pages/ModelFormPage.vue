<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUnsavedChanges } from '../composables/useUnsavedChanges'
import PageHeader from '../components/PageHeader.vue'
import ConnectionStatus from '../components/ConnectionStatus.vue'
import { getModel, saveModel, testModel, type ModelConfig, type ModelSave } from '../api/models'
import { ApiError } from '../api/client'

const route = useRoute()
const router = useRouter()
const id = typeof route.params.id === 'string' ? route.params.id : undefined
const editing = !!id
const loading = ref(editing)
const loaded = ref(!editing)
const saving = ref(false)
const error = ref('')
const keyConfigured = ref(false)
const pricingOpen = ref(false)
const advancedOpen = ref(false)
const savedId = ref(id)
const connection = ref('')
const errors = ref<Record<string, string>>({})
const form = reactive({ display_name: '', model_id: '', base_url: '', api_key: '', context_length: '8192', max_output_tokens: '2048', temperature: '1', input_price: '', output_price: '', cached_input_price: '', pricing_currency: 'CNY', price_unit_tokens: '1000000' })
const { markSaved } = useUnsavedChanges(() => JSON.stringify(form), loaded, saving)
type FormField = keyof typeof form
interface Field { key: FormField; label: string; hint: string; placeholder?: string; type?: string; maxLength?: number; step?: string; min?: string; max?: string }
function updateField(field: FormField, event: Event) {
  form[field] = (event.target as HTMLInputElement).value
  delete errors.value[field]
}
const groups = computed<{ title: string; description: string; fields: Field[] }[]>(() => [
  { title: '连接配置', description: '填写服务商提供的接口信息。带 * 的项目为必填。', fields: [
    { key: 'base_url', label: '服务地址 *', hint: '填写 API 地址，保留所需的 /v1，不含 /chat/completions。', placeholder: 'https://api.example.com/v1', type: 'url', maxLength: 2048 },
    { key: 'model_id', label: '模型名称 *', hint: '填写服务商提供的模型名称。', placeholder: '填写服务商的模型标识', maxLength: 200 },
    { key: 'api_key', label: 'API Key' + (editing && keyConfigured.value ? '' : ' *'), hint: keyConfigured.value ? '已配置，留空则保留原密钥。填写新密钥后，保存时替换。' : '密钥加密保存在本机。', placeholder: keyConfigured.value ? '已配置，留空则保留原密钥' : '输入 API Key', type: 'password', maxLength: 4096 },
  ] },
  { title: '高级设置', description: '默认上下文 8192、输出上限 2048 Token；这是本应用的使用限制，请按服务商说明调整。', fields: [
    { key: 'display_name', label: '显示名称（选填）', hint: '便于识别的名称，仅在本应用中显示。', placeholder: '例如：我的日常模型', maxLength: 100 },

    { key: 'context_length', label: '上下文长度 *', hint: '单位 token。填写模型实际支持的上下文窗口大小。', type: 'number', step: '1', min: '1', max: '2147483647', placeholder: '按服务商说明填写' },
    { key: 'max_output_tokens', label: '最大输出长度 *', hint: '单位 token。不得超过上下文长度，也应符合服务商的输出限制。', type: 'number', step: '1', min: '1', max: '2147483647', placeholder: '按服务商说明填写' },
    { key: 'temperature', label: '温度 *', hint: '建议值 1，范围 0–2。数值越高，输出通常越随机；还需符合服务商限制。', type: 'number', step: 'any', min: '0', max: '2' },
  ] },
  { title: '价格记录', description: '选填。明确币种和计价 Token 数，历史运行会保存当时的价格快照。留空表示未知，0 表示免费。', fields: [
    { key: 'pricing_currency', label: '币种 *', hint: '使用三个大写字母，例如 CNY、USD。', maxLength: 3 },
    { key: 'price_unit_tokens', label: '计价 Token 数 *', hint: '单价对应的 Token 数，服务商通常按 1,000,000 Token 报价。', type: 'number', step: '1', min: '1', max: '1000000000' },
    { key: 'input_price', label: '输入单价', hint: '每个计价 Token 数的输入价格。', type: 'number', step: 'any', min: '0', placeholder: '未填写' },
    { key: 'output_price', label: '输出单价', hint: '每个计价 Token 数的输出价格。', type: 'number', step: 'any', min: '0', placeholder: '未填写' },
    { key: 'cached_input_price', label: '缓存命中输入单价', hint: '每个计价 Token 数的缓存输入价格。', type: 'number', step: 'any', min: '0', placeholder: '未填写' },
  ] },
])
async function load() {
  if (!id) return
  loading.value = true
  error.value = ''
  try {
    const model = await getModel(id)
    for (const field of Object.keys(form) as FormField[]) {
      if (field !== 'api_key') {
        const fallback = field === 'pricing_currency' ? 'CNY' : field === 'price_unit_tokens' ? '1000000' : ''
        form[field] = model[field as keyof ModelConfig] == null ? fallback : String(model[field as keyof ModelConfig])
      }
    }
    form.api_key = ''
    keyConfigured.value = model.key_configured
    markSaved()
    loaded.value = true
  } catch (e) { error.value = e instanceof Error ? e.message : '无法加载模型。' }
  finally { loading.value = false }
}
function validate() {
  const invalid: Record<string, string> = {}
  for (const field of ['model_id', 'base_url'] as const) {
    if (!form[field].trim()) invalid[field] = '请填写此项。'
  }
  if (!keyConfigured.value && !form.api_key.trim()) invalid.api_key = '请填写 API Key。'
  if (form.api_key.trim() && !/^[\x21-\x7E]+$/.test(form.api_key.trim())) invalid.api_key = '密钥应为不含空白的 ASCII 字符。'
  try {
    const url = new URL(form.base_url.trim())
    if (!['https:', 'http:'].includes(url.protocol) || !url.hostname || url.username || url.password || /[?#\s\\]/.test(form.base_url.trim())) throw new Error()
    if (url.pathname.replace(/\/+$/, '').toLowerCase().endsWith('/chat/completions')) invalid.base_url = '请移除末尾的 /chat/completions，只填写 API Base URL。'
  } catch { invalid.base_url = '请输入有效的 http(s) 服务地址，不含账号、查询参数或片段。' }
  for (const field of ['context_length', 'max_output_tokens'] as const) {
    const value = Number(form[field])
    if (!Number.isInteger(value) || value <= 0 || value > 2147483647) invalid[field] = '请输入 1 至 2147483647 的正整数。'
  }
  if (!invalid.max_output_tokens && !invalid.context_length && Number(form.max_output_tokens) > Number(form.context_length)) invalid.max_output_tokens = '最大输出长度不得超过上下文长度。'
  if (!form.temperature.trim() || !Number.isFinite(Number(form.temperature)) || Number(form.temperature) < 0 || Number(form.temperature) > 2) invalid.temperature = '温度应为 0 至 2 的数字。'
  if (!/^[A-Za-z]{3}$/.test(form.pricing_currency.trim())) invalid.pricing_currency = '请输入三个字母的币种代码，例如 CNY。'
  if (!Number.isInteger(Number(form.price_unit_tokens)) || Number(form.price_unit_tokens) < 1 || Number(form.price_unit_tokens) > 1000000000) invalid.price_unit_tokens = '请输入 1 至 1,000,000,000 的正整数。'
  for (const field of ['input_price', 'output_price', 'cached_input_price'] as const) {
    if (form[field].trim() && (!Number.isFinite(Number(form[field])) || Number(form[field]) < 0)) invalid[field] = '价格不得为负数，未知时请留空。'
  }
  errors.value = invalid
  return !Object.keys(invalid).length
}
async function focusError() {
  if (['display_name', 'context_length', 'max_output_tokens', 'temperature'].some(key => errors.value[key])) advancedOpen.value = true
  if (['pricing_currency', 'price_unit_tokens', 'input_price', 'output_price', 'cached_input_price'].some(key => errors.value[key])) pricingOpen.value = true
  await nextTick()
  document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()
}
async function submit(test = false) {
  if (saving.value || !loaded.value) return
  error.value = ''
  connection.value = ''
  if (!validate()) { await focusError(); return }
  saving.value = true
  const data: ModelSave = {
    display_name: form.display_name.trim() || form.model_id.trim().slice(0, 100), model_id: form.model_id.trim(), base_url: form.base_url.trim(),
    context_length: Number(form.context_length), max_output_tokens: Number(form.max_output_tokens), temperature: Number(form.temperature),
    input_price: form.input_price.trim() ? Number(form.input_price) : null,
    output_price: form.output_price.trim() ? Number(form.output_price) : null,
    cached_input_price: form.cached_input_price.trim() ? Number(form.cached_input_price) : null,
    pricing_currency: form.pricing_currency.trim().toUpperCase(),
    price_unit_tokens: Number(form.price_unit_tokens),
    ...(form.api_key.trim() ? { api_key: form.api_key.trim() } : {}),
  }
  try {
    const saved = await saveModel(data, savedId.value)
    savedId.value = saved.id
    keyConfigured.value = true
    form.api_key = ''
    markSaved()
    if (test) {
      const result = await testModel(saved.id)
      connection.value = result.success ? '连接成功，配置已保存。' : `${result.message} ${result.suggestion}`
    } else await router.push('/models')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存失败，请重试。'
    if (e instanceof ApiError) errors.value = e.fields
    saving.value = false
    await focusError()
  } finally { saving.value = false }
}
onMounted(load)
onBeforeUnmount(() => { form.api_key = '' })
</script>

<template>
  <div class="module-page model-form-page">
    <RouterLink class="form-back" to="/models">← 返回模型连接</RouterLink>
    <PageHeader :title="editing ? '编辑模型' : '添加模型'" description="填写服务商提供的连接信息。" />
    <div v-if="error" class="model-feedback" role="alert"><p>{{ error }}</p><button v-if="!loaded" class="button button-ghost" :disabled="loading" @click="load">重新加载</button></div>
    <p v-if="loading" role="status">正在加载配置…</p>
    <form v-else-if="loaded" novalidate autocomplete="off" @submit.prevent="submit(false)">
      <template v-for="(group, index) in groups" :key="group.title"><component :is="index > 0 ? 'details' : 'section'" :class="index > 0 ? 'agent-advanced model-pricing' : 'model-form-section'" :open="index === 2 ? pricingOpen : index === 1 ? advancedOpen : undefined" :aria-label="group.title" @toggle="index === 2 ? (pricingOpen = ($event.currentTarget as HTMLDetailsElement).open) : index === 1 && (advancedOpen = ($event.currentTarget as HTMLDetailsElement).open)"><summary v-if="index > 0">{{ index === 1 ? '高级设置' : '价格记录（选填）' }}</summary>
        <header class="form-section-heading">
          <span class="eyebrow" aria-hidden="true">0{{ index + 1 }}</span>
          <h2 :id="`form-section-${index}`">{{ group.title }}</h2>
          <p class="form-section-note">{{ group.description }}</p>
        </header>
        <fieldset class="model-field-grid" :disabled="saving" :aria-label="group.title">
          <div v-for="field in group.fields" :key="field.key" class="model-field" :class="{ 'field-wide': index === 0 }">
            <label :for="field.key">{{ field.label }}</label>
            <input :id="field.key" :value="form[field.key]" :type="field.type || 'text'" :maxlength="field.maxLength" :step="field.step" :min="field.min" :max="field.max" :placeholder="field.placeholder" :autocomplete="field.key === 'api_key' ? 'new-password' : 'off'" :spellcheck="false" :aria-invalid="!!errors[field.key]" :aria-describedby="`${field.key}-hint${errors[field.key] ? ` ${field.key}-error` : ''}`" @input="updateField(field.key, $event)" />
            <p :id="`${field.key}-hint`" class="field-hint">{{ field.hint }}</p>
            <p v-if="errors[field.key]" :id="`${field.key}-error`" class="field-error">{{ errors[field.key] }}</p>
          </div>
        </fieldset>
      </component></template>
      <div class="form-submit"><span class="muted">测试连接会保存配置并发送一条测试请求。</span><div class="model-actions"><button type="button" class="button button-plain" :disabled="saving" @click="router.push('/models')">取消</button><button type="submit" class="button button-ghost" :disabled="saving">{{ saving ? '正在保存…' : '保存' }}</button><button type="button" class="button button-primary" :disabled="saving" @click="submit(true)">{{ saving ? '正在处理…' : '测试连接' }}</button></div></div>
      <p v-if="connection" role="status" class="model-notice">{{ connection }}</p>
    </form>
    <footer class="page-footer"><span class="footer-note">密钥仅用于向所填写的模型服务发起请求。</span><ConnectionStatus /></footer>
  </div>
</template>
