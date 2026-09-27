<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChatStore } from '../stores/chat'
import type { Conversation } from '../api/chat'
import * as workspace from '../api/workspace'
import ConversationRow from './ConversationRow.vue'
import AppIcon from './AppIcon.vue'
const chat = useChatStore()
const route = useRoute()
const router = useRouter()
const projects = ref<workspace.Project[]>([])
const search = ref('')
const periodOpen = ref<Record<string, boolean>>({ today: true, yesterday: true, week: true, earlier: true })
const clock = ref(new Date())
const projectsOpen = ref(true)
const historyOpen = ref(true)
const projectOpen = ref<Record<string, boolean>>({})
const error = ref('')
const saving = ref(false)
const dialog = ref<HTMLDialogElement>()
const dialogOpen = ref(false)
const mode = ref<'project' | 'rename-project' | 'delete-project' | 'conversation'>('project')
const project = ref<workspace.Project>()
const selected = ref<Conversation>()
const name = ref('')
const projectId = ref('')
const pinned = ref(false)
const dropTarget = ref('')
let returnFocus: HTMLElement | null = null
let timer: ReturnType<typeof setInterval>
const filtered = computed(() => chat.sessions
  .filter(item => item.title.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase()))
  .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at) || a.id.localeCompare(b.id)))
const history = computed(() => filtered.value.filter(item => !item.project_id))
const historyGroups = computed(() => {
  const today = new Date(clock.value); today.setHours(0, 0, 0, 0)
  const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1)
  const week = new Date(today); week.setDate(week.getDate() - 6)
  const groups = [
    { id: 'today', label: '今天', items: [] as Conversation[] },
    { id: 'yesterday', label: '昨天', items: [] as Conversation[] },
    { id: 'week', label: '一周', items: [] as Conversation[] },
    { id: 'earlier', label: '更早', items: [] as Conversation[] },
  ]
  for (const item of history.value) {
    const date = new Date(item.updated_at)
    const index = date >= today ? 0 : date >= yesterday ? 1 : date >= week ? 2 : 3
    groups[index]!.items.push(item)
  }
  return groups.filter(group => group.items.length)
})
const projectConversations = computed(() => {
  const byProject = new Map<string, Conversation[]>()
  for (const item of filtered.value) {
    if (!item.project_id) continue
    const items = byProject.get(item.project_id) ?? []
    items.push(item); byProject.set(item.project_id, items)
  }
  return byProject
})
const inProject = (id: string) => projectConversations.value.get(id) ?? []
async function load() { try { projects.value = await workspace.projects(); error.value = '' } catch (e) { error.value = e instanceof Error ? e.message : '项目加载失败' } }
async function open(id: string) { if (route.path !== '/chat') await router.push({path:'/chat',query:{session:id}}); else { await chat.select(id); await router.replace({path:'/chat',query:{session:id}}) } }
async function create(id?: string) {
  search.value = ''
  await chat.create({ project_id: id || null, folder: null })
  if (chat.error) { error.value = chat.error; return }
  chat.clearNewComposer()
  if (id) { projectsOpen.value = true; projectOpen.value[id] = true } else historyOpen.value = true
  await router.push({ path: '/chat', query: { session: chat.selected } })
  await nextTick(); document.getElementById('chat-input')?.focus()
}
async function show(kind: typeof mode.value, item?: workspace.Project | Conversation) {
  returnFocus = kind === 'conversation' && item ? document.getElementById(`conversation-actions-${item.id}`) : document.activeElement as HTMLElement
  mode.value = kind; error.value = ''; name.value = item && 'name' in item ? item.name : ''; project.value = kind.includes('project') ? item as workspace.Project : undefined
  if (kind === 'conversation') { selected.value = item as Conversation; name.value = selected.value.title; projectId.value = selected.value.project_id || ''; pinned.value = selected.value.pinned }
  dialogOpen.value = true
  await nextTick(); dialog.value?.showModal(); dialog.value?.querySelector<HTMLInputElement>('input')?.focus()
}
function close() { if (saving.value) return; dialog.value?.close(); dialogOpen.value = false; returnFocus?.focus() }
async function save() {
  if (saving.value || !name.value.trim()) return
  saving.value = true
  try {
    if (mode.value === 'conversation' && selected.value) {
      if (!await chat.update(selected.value.id, { title: name.value.trim(), project_id: projectId.value || null, pinned: pinned.value })) throw new Error(chat.error)
    } else await workspace.saveProject(name.value.trim(), project.value?.id)
    await load(); saving.value = false; close()
  } catch (e) { error.value = e instanceof Error ? e.message : '保存失败' }
  finally { saving.value = false }
}
async function remove() {
  if (saving.value) return
  saving.value = true
  try {
    if (mode.value === 'delete-project' && project.value) await workspace.deleteProject(project.value.id)
    else if (selected.value && !await chat.remove(selected.value.id)) throw new Error(chat.error)
    await load(); if (mode.value === 'delete-project') await chat.refreshList(); saving.value = false; close()
  } catch (e) { error.value = e instanceof Error ? e.message : '删除失败' }
  finally { saving.value = false }
}
const deleteConfirm = ref(false)
async function confirmConversationDelete(item: Conversation) {
  deleteConfirm.value = true
  await show('conversation', item)
  await nextTick(); dialog.value?.querySelector<HTMLButtonElement>('.button-ghost')?.focus()
}
function acceptDrop(event: DragEvent, id: string) {
  if (!event.dataTransfer?.types.includes('application/x-mini-agent-conversation')) return
  event.preventDefault(); event.dataTransfer.dropEffect = 'move'; dropTarget.value = id
}
async function moveConversation(event: DragEvent, id: string) {
  const cid = event.dataTransfer?.getData('application/x-mini-agent-conversation')
  dropTarget.value = ''
  if (!cid || !chat.sessions.some(item => item.id === cid) || !projects.value.some(item => item.id === id)) return
  event.preventDefault()
  if (chat.sessions.find(item => item.id === cid)?.project_id === id) return
  if (await chat.update(cid, { project_id: id })) { projectsOpen.value = true; projectOpen.value[id] = true }
  else error.value = chat.error
}
function refreshVisible() {
  if (document.visibilityState === 'hidden') return
  const now = new Date()
  if (now.toDateString() !== clock.value.toDateString()) clock.value = now
  void chat.refreshList()
}
onMounted(() => {
  void load()
  if (route.path !== '/chat') void chat.refreshList()
  timer = setInterval(refreshVisible, 5000)
  document.addEventListener('visibilitychange', refreshVisible)
})
onUnmounted(() => { clearInterval(timer); document.removeEventListener('visibilitychange', refreshVisible) })
</script>
<template>
  <div class="primary-conversations">
    <button class="new-conversation" aria-label="新建对话" title="新建对话" :disabled="chat.creating" @click="create()"><AppIcon name="write" /><span>新建对话</span></button>
    <slot name="navigation" />
    <div class="sidebar-session-content">
      <label class="conversation-search"><AppIcon name="search" /><input v-model="search" type="search" aria-label="搜索会话标题" placeholder="搜索对话" /></label>
      <p v-if="error && !dialog?.open" class="field-error">{{ error }} <button @click="load">重试</button></p>
      <section class="session-section">
        <div class="session-section-heading"><button :aria-expanded="projectsOpen" aria-controls="project-list" @click="projectsOpen = !projectsOpen"><AppIcon name="chevron" /><span>项目</span></button><button aria-label="创建项目" title="创建项目" @click="show('project')"><AppIcon name="folder" /></button></div>
        <div v-if="projectsOpen" id="project-list">
          <p v-if="!projects.length" class="sidebar-empty">按项目整理对话</p>
          <div v-for="item in projects" :key="item.id" class="project-group" :class="{ 'is-drop-target': dropTarget === item.id }" @dragover="acceptDrop($event, item.id)" @dragleave="dropTarget = ''" @drop="moveConversation($event, item.id)">
            <div class="project-heading"><button :aria-expanded="!!projectOpen[item.id]" :aria-controls="`project-conversations-${item.id}`" @click="projectOpen[item.id] = !projectOpen[item.id]"><AppIcon name="chevron" class="project-chevron" /><AppIcon name="folder" /><span>{{ item.name }}</span></button><button :aria-label="`在${item.name}中新建对话`" title="新建对话" @click="create(item.id)"><AppIcon name="write" /></button><button :aria-label="`管理项目：${item.name}`" title="管理项目" @click="show('rename-project',item)"><AppIcon name="more" /></button></div>
            <div v-if="projectOpen[item.id]" :id="`project-conversations-${item.id}`" class="project-conversations">
              <p v-if="!inProject(item.id).length" class="sidebar-empty">暂无匹配的对话</p>
              <ConversationRow v-for="conversation in inProject(item.id)" :key="conversation.id" :item="conversation" detailed :active="route.path === '/chat' && chat.selected === conversation.id" :busy="!!chat.busy[conversation.id]" @open="open" @manage="deleteConfirm = false; show('conversation', $event)" @delete="confirmConversationDelete" />
            </div>
          </div>
        </div>
      </section>
      <section class="session-section history-section">
        <div class="session-section-heading"><button :aria-expanded="historyOpen" aria-controls="history-list" @click="historyOpen = !historyOpen"><AppIcon name="chevron" /><span>历史对话</span><small>{{ history.length }}</small></button></div>
        <div v-if="historyOpen" id="history-list">
          <p v-if="!history.length" class="sidebar-empty">{{ search ? '没有匹配的对话' : '对话会保存在这里' }}</p>
          <section v-for="group in historyGroups" :key="group.id" class="history-period">
            <button class="history-period-toggle" :aria-expanded="periodOpen[group.id]" :aria-controls="`history-${group.id}`" @click="periodOpen[group.id] = !periodOpen[group.id]"><AppIcon name="chevron" /><span>{{ group.label }}</span><small>{{ group.items.length }}</small></button>
            <div v-if="periodOpen[group.id]" :id="`history-${group.id}`">
              <ConversationRow v-for="item in group.items" :key="item.id" :item="item" detailed :active="route.path === '/chat' && chat.selected === item.id" :busy="!!chat.busy[item.id]" @open="open" @manage="deleteConfirm = false; show('conversation', $event)" @delete="confirmConversationDelete" />
            </div>
          </section>
        </div>
      </section>
    </div>
    <dialog ref="dialog" class="conversation-dialog workspace-manager" aria-labelledby="workspace-manager-title" @cancel.prevent="close">
      <template v-if="dialogOpen"><h2 id="workspace-manager-title">{{ mode === 'conversation' ? '管理对话' : mode === 'project' ? '新建项目' : mode === 'delete-project' ? '删除项目' : '管理项目' }}</h2>
      <p v-if="error" role="alert" class="field-error">{{ error }}</p>
      <template v-if="mode === 'delete-project' || deleteConfirm"><p>{{ mode === 'delete-project' ? '删除项目后，其中对话移入历史对话，文件夹记录保留。' : '删除此对话？应用中的消息将被删除，无法恢复；文件夹内的副本会保留。' }}</p><div class="model-actions"><button class="button button-ghost" :disabled="saving" @click="deleteConfirm=false;close()">取消</button><button class="button button-primary" :disabled="saving" @click="remove">确认删除</button></div></template>
      <form v-else class="workspace-edit" @submit.prevent="save">
        <label>名称<input :id="selected && mode==='conversation' ? `conversation-title-${selected.id}` : 'project-name'" v-model="name" maxlength="100" required :disabled="saving" /></label>
        <template v-if="mode==='conversation'"><label>归属项目<select v-model="projectId" :disabled="saving"><option value="">历史对话</option><option v-for="item in projects" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><label class="inline-check"><input v-model="pinned" type="checkbox" :disabled="saving" />置顶</label></template>
        <div class="model-actions"><button v-if="mode!=='project'" type="button" class="button button-plain" :disabled="saving" @click="mode==='conversation' ? deleteConfirm=true : mode='delete-project'">删除</button><button type="button" class="button button-ghost" :disabled="saving" @click="close">取消</button><button class="button button-primary" :disabled="saving || !name.trim()">保存</button></div>
      </form>
    </template></dialog>
  </div>
</template>
