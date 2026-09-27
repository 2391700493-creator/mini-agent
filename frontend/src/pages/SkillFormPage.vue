<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import PageHeader from '../components/PageHeader.vue'
import ConnectionStatus from '../components/ConnectionStatus.vue'
import { getSkill, saveSkill, type SkillSave } from '../api/skills'
import { ApiError } from '../api/client'

const route = useRoute()
const router = useRouter()
const id = String(route.params.id)
const loading = ref(true)
const loaded = ref(false)
const saving = ref(false)
const error = ref('')
const errors = ref<Record<string, string>>({})
const conflict = ref(false)
const original = ref('')
const form = reactive<SkillSave>({ name: '', description: '', instructions: '', revision: '' })
const dirty = computed(() => loaded.value && JSON.stringify(form) !== original.value)
const fields = [
  { key: 'name', title: '名称', hint: '简短、明确，便于 Agent 识别任务。修改名称不会改变目录名。', max: 100 },
  { key: 'description', title: '用途说明', hint: '说明何时使用、适合处理什么任务。', max: 500 },
  { key: 'instructions', title: '详细指令', hint: '支持 Markdown。写明处理步骤、输出格式和限制；这些内容仅供 Agent 阅读。', max: 500000 },
] as const
async function load() {
  if (dirty.value && !window.confirm('重新加载会丢弃尚未保存的修改，是否继续？')) return
  loading.value = true
  error.value = ''
  try {
    const skill = await getSkill(id)
    Object.assign(form, { name: skill.name, description: skill.description, instructions: skill.instructions, revision: skill.revision })
    original.value = JSON.stringify(form)
    loaded.value = true
    conflict.value = false
    errors.value = {}
  } catch (e) { error.value = e instanceof Error ? e.message : '加载失败，请重试。' }
  finally { loading.value = false }
}
async function submit() {
  if (saving.value || !loaded.value) return
  errors.value = {}
  for (const field of fields) if (!form[field.key].trim()) errors.value[field.key] = '请填写此项。'
  if (Object.keys(errors.value).length) {
    await nextTick()
    document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()
    return
  }
  saving.value = true
  error.value = ''
  try {
    await saveSkill(id, { ...form })
    original.value = JSON.stringify(form)
    await router.push('/skills')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存失败，请重试。'
    if (e instanceof ApiError) { errors.value = e.fields; conflict.value = e.status === 409 }
  } finally { saving.value = false }
}
onBeforeRouteLeave(() => {
  if (saving.value && dirty.value) return false
  if (dirty.value) return window.confirm('有尚未保存的修改，确定离开？')
})
onMounted(load)
</script>

<template>
  <div class="module-page skill-form-page">
    <RouterLink class="form-back" to="/skills">← 返回 任务技能</RouterLink>
    <PageHeader title="编辑技能" description="把任务方法、输出要求和限制写清楚。" />
    <div v-if="error" class="model-feedback" role="alert"><p>{{ error }}</p><button v-if="!loaded || conflict" class="button button-ghost" :disabled="loading || saving" @click="load">重新加载</button></div>
    <p v-if="loading" class="model-loading" role="status">正在读取 SKILL.md…</p>
    <form v-else-if="loaded" novalidate @submit.prevent="submit">
      <section class="skill-basics" aria-label="技能信息">
        <div v-for="field in fields.slice(0, 2)" :key="field.key" class="model-field">
          <label :for="field.key">{{ field.title }} *</label>
          <input v-if="field.key === 'name'" :id="field.key" v-model="form.name" :maxlength="field.max" :disabled="saving" :aria-invalid="!!errors[field.key]" :aria-describedby="`hint-${field.key} error-${field.key}`" @input="delete errors[field.key]" />
          <textarea v-else :id="field.key" v-model="form[field.key]" rows="3" :maxlength="field.max" :disabled="saving" :spellcheck="false" :aria-invalid="!!errors[field.key]" :aria-describedby="`hint-${field.key} error-${field.key}`" @input="delete errors[field.key]" />
          <p :id="`hint-${field.key}`" class="field-hint">{{ field.hint }}</p>
          <p :id="`error-${field.key}`" class="field-error">{{ errors[field.key] }}</p>
          <p class="field-hint">{{ form[field.key].length.toLocaleString() }} / {{ field.max.toLocaleString() }} 字</p>
        </div>
      </section>
      <section class="skill-editor-section" aria-labelledby="instructions-label">
        <label id="instructions-label" for="instructions">详细指令 *</label>
        <p id="hint-instructions" class="field-hint">{{ fields[2].hint }}</p>
        <textarea id="instructions" v-model="form.instructions" class="skill-instructions" rows="16" :maxlength="fields[2].max" :disabled="saving" :spellcheck="false" :aria-invalid="!!errors.instructions" aria-describedby="hint-instructions error-instructions" @input="delete errors.instructions" />
        <p id="error-instructions" class="field-error">{{ errors.instructions }}</p>
        <p class="field-hint">{{ form.instructions.length.toLocaleString() }} / {{ fields[2].max.toLocaleString() }} 字</p>
      </section>
      <div class="form-submit"><span class="muted">保存后立即生效</span><div class="model-actions"><button class="button button-ghost" type="button" :disabled="saving" @click="router.push('/skills')">取消</button><button class="button button-primary" type="submit" :disabled="saving">{{ saving ? '正在保存…' : '保存技能' }}</button></div></div>
    </form>
    <footer class="page-footer"><span class="footer-note">保存后同步更新文件与列表。</span><ConnectionStatus /></footer>
  </div>
</template>
