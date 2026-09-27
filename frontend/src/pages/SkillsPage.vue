<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import ResourceGuideCard from '../components/ResourceGuideCard.vue'
import PageHeader from '../components/PageHeader.vue'
import ConnectionStatus from '../components/ConnectionStatus.vue'
import AppIcon from '../components/AppIcon.vue'
import { deleteSkill, importSkill, listSkills, refreshSkills, toggleSkill, type Skill, type SkillList } from '../api/skills'

const skills = ref<Skill[]>([])
const issues = ref<SkillList['issues']>([])
const loading = ref(true)
const pending = ref(false)
const busy = computed(() => loading.value || pending.value)
const error = ref('')
const notice = ref('')
const deleting = ref<Skill | null>(null)
const deleteDialog = ref<HTMLDialogElement>()
const deleteCancel = ref<HTMLButtonElement>()
const picker = ref<HTMLInputElement | null>(null)
const reason = (e: unknown) => e instanceof Error ? e.message : '操作未完成，请重试。'
const date = (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false })
function update(result: SkillList) { skills.value = result.items; issues.value = result.issues }
async function load(refresh = false) {
  if (pending.value) return
  loading.value = true
  error.value = ''
  try {
    update(await (refresh ? refreshSkills() : listSkills()))
    if (refresh) notice.value = '已重新扫描 workspace/skills。'
    deleting.value = null
    deleteDialog.value?.close()
  } catch (e) { error.value = reason(e) }
  finally { loading.value = false }
}
async function upload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || busy.value) return
  error.value = ''
  notice.value = ''
  if (!file.name.toLowerCase().endsWith('.zip')) { error.value = '请选择 ZIP 文件。'; return }
  if (file.size > 5 * 1024 * 1024) { error.value = 'ZIP 文件不能超过 5 MiB。'; return }
  pending.value = true
  try {
    const skill = await importSkill(file)
    notice.value = `已导入并启用「${skill.name}」。`
    update(await listSkills())
  } catch (e) { error.value = reason(e) }
  finally { pending.value = false }
}
async function toggle(skill: Skill) {
  if (busy.value) return
  pending.value = true
  error.value = ''; notice.value = ''
  try {
    const updated = await toggleSkill(skill.id, !skill.enabled)
    skills.value = skills.value.map(item => item.id === updated.id ? updated : item)
    notice.value = `已${updated.enabled ? '启用' : '停用'}「${updated.name}」。`
  } catch (e) { error.value = reason(e) }
  finally { pending.value = false }
}
async function confirmDelete(skill: Skill) {
  if (busy.value) return
  error.value = ''
  deleting.value = skill
  await nextTick()
  deleteDialog.value?.showModal()
  deleteCancel.value?.focus()
}
async function cancelDelete() {
  if (pending.value) return
  const id = deleting.value?.id
  deleteDialog.value?.close()
  deleting.value = null
  await nextTick()
  document.getElementById(`delete-${id}`)?.focus()
}
async function remove() {
  if (!deleting.value || busy.value) return
  pending.value = true
  error.value = ''; notice.value = ''
  const skill = deleting.value
  try {
    await deleteSkill(skill.id)
    skills.value = skills.value.filter(item => item.id !== skill.id)
    deleteDialog.value?.close()
    deleting.value = null
    notice.value = `已删除「${skill.name}」及其目录。`
    await nextTick()
    document.getElementById('page-title')?.focus()
  } catch (e) { error.value = reason(e) }
  finally { pending.value = false }
}
onMounted(() => load())
</script>

<template>
  <div class="module-page skills-page">
    <div class="models-header">
      <PageHeader title="任务技能" description="保存任务方法，让 Agent 按照明确的步骤与要求工作。" />
      <div class="model-actions skills-toolbar">
        <button class="button button-ghost" :disabled="busy" @click="load(true)"><AppIcon name="refresh" :class="{ spinning: loading }" />刷新</button>
        <button class="button button-primary" :disabled="busy" @click="picker?.click()"><AppIcon name="add" />{{ pending ? '处理中…' : '导入 ZIP' }}</button>
        <input ref="picker" class="skill-file-input" type="file" accept=".zip,application/zip" aria-label="选择 Skill ZIP 文件" @change="upload" />
      </div>
    </div>
    <details class="skills-format"><summary>技能是什么？</summary><p class="skills-intro">Skill 是供 Agent 阅读的任务说明，本身不执行代码或调用工具。文件保存在 <code>workspace/skills</code>；手动添加或修改后，点击刷新即可同步。</p></details>
    <p v-if="notice" class="model-notice" role="status">{{ notice }}</p>
    <div v-if="error && !deleting" class="model-feedback" role="alert"><p>{{ error }}</p><button class="button button-ghost" :disabled="busy" @click="load(true)">重新加载</button></div>
    <section v-if="issues.length" class="skills-scan-issues" aria-label="扫描问题" role="alert">
      <h2>以下目录未载入</h2><p>修正文件后点击刷新，这些内容暂不提供给 Agent。</p>
      <ul><li v-for="issue in issues" :key="issue.directory"><strong>{{ issue.directory }}</strong>：{{ issue.message }}</li></ul>
    </section>
    <dialog ref="deleteDialog" id="skill-delete-confirmation" class="conversation-dialog skill-delete-dialog" aria-labelledby="skill-delete-title" aria-describedby="skill-delete-description" @cancel.prevent="cancelDelete">
      <template v-if="deleting">
      <h2 id="skill-delete-title">删除「{{ deleting.name }}」？</h2>
      <p id="skill-delete-description">将永久删除 workspace/skills/{{ deleting.id }} 目录和其中的所有文件。如需保留文件，请使用停用。</p>
      <p v-if="error" class="field-error" role="alert">{{ error }}</p>
      <div class="model-actions"><button ref="deleteCancel" class="button button-ghost" :disabled="busy" @click="cancelDelete">取消</button><button class="button button-primary" :disabled="busy" @click="remove">{{ pending ? '正在删除…' : '确认删除' }}</button></div>
      </template>
    </dialog>
    <p v-if="loading" class="model-loading" role="status">正在扫描 Skills…</p>
    <section v-else-if="skills.length" aria-label="已添加的 Skills">
      <div class="model-list-heading"><h2>任务说明 <span>{{ skills.length }}</span></h2><span class="muted">已启用 {{ skills.filter(skill => skill.enabled).length }} 项</span></div>
      <div class="management-list resource-grid">
      <article v-for="skill in skills" :key="skill.id" class="model-card skill-card management-row skill-row resource-card" :class="{ 'is-enabled': skill.enabled }" :aria-label="skill.name">
        <div class="model-card-heading"><h3><RouterLink class="resource-main-link" :to="`/skills/${encodeURIComponent(skill.id)}/edit`">{{ skill.name }}</RouterLink></h3></div>
        <p class="skill-description">{{ skill.description }}</p>
        <div class="model-card-footer"><div class="resource-card-controls"><button class="tool-switch" role="switch" :aria-checked="skill.enabled" :aria-label="`${skill.name}启用状态`" :disabled="busy || !!deleting" @click="toggle(skill)"><span class="switch-track" :class="{ 'is-on': skill.enabled }" aria-hidden="true"><span /></span><span>{{ skill.enabled ? '已启用' : '已停用' }}</span></button><div class="model-actions">
          <RouterLink :to="`/skills/${encodeURIComponent(skill.id)}/edit`" class="button button-plain">编辑</RouterLink>
        </div></div><div class="resource-card-maintenance"><time class="model-updated" :datetime="skill.updated_at">更新于 {{ date(skill.updated_at) }}</time>
          <button :id="`delete-${skill.id}`" class="button button-plain button-danger" :disabled="busy || !!deleting" @click="confirmDelete(skill)">删除</button>
        </div></div>
      </article>
      <ResourceGuideCard title="添加新的任务技能" description="把常用方法交给 Agent。" icon="skill" :steps="['准备包含 SKILL.md 的 ZIP', '导入并检查任务说明', '在 Agent 中选择该技能']" action="导入技能" :disabled="busy" @choose="picker?.click()" />
      </div>
    </section>
    <div v-else-if="!error" class="resource-grid"><button class="resource-empty-card" :disabled="busy" @click="picker?.click()"><AppIcon name="skill" /><strong>导入第一个技能</strong><span>选择包含 SKILL.md 的 ZIP 文件。</span></button></div>
    <details class="skills-format"><summary>查看文件格式与导入要求</summary><p>ZIP 根目录或唯一的一级目录中须包含 SKILL.md。名称、用途说明和正文均为必填；正文支持 Markdown。目录名支持字母、数字、中文、短横线和下划线，不能以下划线开头。</p><pre>---
name: 会议纪要
description: 将会议记录整理为结论与待办
---

# 处理步骤
1. 提取已确认的结论。
2. 按负责人整理待办；缺失信息标注为待确认。

# 输出要求
分别列出会议结论、待办事项与待确认问题。</pre><p>ZIP 最大 5 MiB，最多 100 个文件或目录；解压后单文件最多 1 MiB、合计最多 10 MiB。不接受同名 Skill、隐藏路径、符号链接、加密文件或越界路径。附件仅保存，不会执行。</p></details>
    <footer class="page-footer"><span class="footer-note">停用保留文件，启停状态保存在本机。</span><ConnectionStatus /></footer>
  </div>
</template>
