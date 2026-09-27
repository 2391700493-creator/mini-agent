<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import PageHeader from '../components/PageHeader.vue'
import AppIcon from '../components/AppIcon.vue'
import { chatAgents, type ChatAgent } from '../api/chat'
import * as api from '../api/automations'
const items = ref<api.Automation[]>([])
const agents = ref<ChatAgent[]>([])
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const editor = ref<HTMLDialogElement>()
const deletion = ref<HTMLDialogElement>()
const deleting = ref<api.Automation>()
const editing = ref<string>()
const advanced = ref(false)
const form = reactive<api.AutomationInput>({name:'',prompt:'',agent_id:'',frequency:'daily',time:'09:00',weekday:0,timezone:'Asia/Shanghai',allow_tools:false,enabled:true})
const date = (value: string) => new Date(value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : value+'Z').toLocaleString('zh-CN', {month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})
const status = (value: string) => ({idle:'待执行',running:'执行中',completed:'已完成',failed:'未完成',cancelled:'已停止',limit_reached:'达到限制'}[value] || value)
let timer: ReturnType<typeof setInterval>
let focus: HTMLElement | null = null
async function load() { try { [items.value,agents.value] = await Promise.all([api.listAutomations(),chatAgents()]); error.value='' } catch(e) { error.value=e instanceof Error?e.message:'加载失败' } finally { loading.value=false } }
function open(item?: api.Automation) {
  focus=document.activeElement as HTMLElement; editing.value=item?.id; advanced.value=false; error.value=''
  Object.assign(form,item ? {...item,agent_id:item.agent_id || ''} : {name:'',prompt:'',agent_id:agents.value.find(a=>a.is_default)?.id || agents.value[0]?.id || '',frequency:'daily',time:'09:00',weekday:0,timezone:'Asia/Shanghai',allow_tools:false,enabled:true})
  editor.value?.showModal()
}
function askDelete(item: api.Automation, event: Event) { focus = event.currentTarget as HTMLElement; deleting.value = item; deletion.value?.showModal() }
function close() { if(busy.value)return; editor.value?.close(); deletion.value?.close(); focus?.focus() }
async function save() { if(busy.value)return; busy.value=true; error.value=''; try { const {name,prompt,agent_id,frequency,time,weekday,timezone,allow_tools,enabled}=form; await api.saveAutomation({name,prompt,agent_id,frequency,time,weekday,timezone,allow_tools,enabled},editing.value); busy.value=false; close(); await load() } catch(e) {error.value=e instanceof Error?e.message:'保存失败';advanced.value=true} finally {busy.value=false} }
async function action(item: api.Automation, operation:'run'|'toggle'|'delete') { if(busy.value)return; busy.value=true;error.value='';try { if(operation==='run')await api.runAutomation(item.id,item.status==='running');else if(operation==='toggle')await api.toggleAutomation(item.id,!item.enabled);else await api.deleteAutomation(item.id);busy.value=false;deletion.value?.close();await load() }catch(e){error.value=e instanceof Error?e.message:'操作失败'}finally{busy.value=false} }
onMounted(()=>{void load();timer=setInterval(()=>{if(!editor.value?.open&&!busy.value)void load()},5000)})
onUnmounted(()=>clearInterval(timer))
</script>
<template>
  <div class="module-page automations-page">
    <div class="models-header"><PageHeader title="定时任务" description="把重复的事交给 Agent。" /><button class="button button-primary" @click="open()"><AppIcon name="add" />新建任务</button></div>
    <div v-if="error&&!editor?.open&&!deletion?.open" class="model-feedback" role="alert">{{ error }} <button @click="load">重试</button></div>
    <p v-if="loading" role="status">正在加载…</p>
    <div v-else class="resource-grid automation-grid">
      <button v-if="!items.length" class="resource-empty-card" @click="open()"><AppIcon name="clock" /><strong>创建第一个定时任务</strong><span>写下任务，选好执行时间。</span></button>
      <article v-for="item in items" :key="item.id" class="resource-card automation-card">
        <button class="resource-card-main" :disabled="item.status==='running'" @click="open(item)"><AppIcon name="clock" /><h2>{{ item.name }}</h2><p>{{ item.prompt }}</p></button>
        <p class="field-hint">{{ item.frequency==='daily'?'每天':item.frequency==='weekdays'?'工作日':`每周${['一','二','三','四','五','六','日'][item.weekday]}` }} {{ item.time }} · {{ item.timezone }}</p>
        <p class="field-hint">{{ item.enabled ? `下次 ${date(item.next_run_at)}`:'已暂停' }} · {{ status(item.status) }}</p>
        <p v-if="item.last_error" class="field-error">{{ item.last_error }}</p>
        <div class="resource-card-actions"><button class="button button-ghost" :disabled="busy" @click="action(item,'run')">{{ item.status==='running'?'停止':'立即运行' }}</button><button class="button button-plain" :disabled="busy" @click="action(item,'toggle')">{{ item.enabled?'暂停':'启用' }}</button><RouterLink v-if="item.last_conversation_id" :to="{path:'/chat',query:{session:item.last_conversation_id}}">查看结果</RouterLink><button class="button button-plain" :disabled="busy||item.status==='running'" @click="askDelete(item,$event)">删除</button></div>
      </article>
    </div>
    <dialog ref="editor" class="conversation-dialog automation-editor" aria-labelledby="automation-title" @cancel.prevent="close">
      <div class="dialog-heading"><h2 id="automation-title">{{ editing?'编辑任务':'新建任务' }}</h2><button class="icon-button" :disabled="busy" aria-label="关闭任务编辑" @click="close">×</button></div>
      <p v-if="error" class="field-error" role="alert">{{ error }}</p>
      <form class="workspace-edit" @submit.prevent="save">
        <label>任务名称<input v-model="form.name" required maxlength="100" :disabled="busy" placeholder="例如：整理每日待办" /></label>
        <label>做什么<textarea v-model="form.prompt" required rows="4" maxlength="100000" :disabled="busy" placeholder="写下要交给 Agent 的任务" /></label>
        <label>由谁执行<select v-model="form.agent_id" required :disabled="busy"><option value="" disabled>选择 Agent</option><option v-for="agent in agents" :key="agent.id" :value="agent.id" :disabled="agent.is_ready===false">{{ agent.name }}</option></select></label>
        <p v-if="!agents.length" class="field-hint">请先在 Agent 管理中创建可用 Agent。</p>
        <div class="schedule-fields"><label>重复<select v-model="form.frequency" :disabled="busy"><option value="daily">每天</option><option value="weekdays">工作日</option><option value="weekly">每周</option></select></label><label v-if="form.frequency==='weekly'">星期<select v-model="form.weekday" :disabled="busy"><option v-for="(day,index) in ['一','二','三','四','五','六','日']" :key="day" :value="index">星期{{ day }}</option></select></label><label>时间<input v-model="form.time" type="time" required :disabled="busy" /></label></div>
        <details class="agent-advanced" :open="advanced" @toggle="advanced=($event.currentTarget as HTMLDetailsElement).open"><summary>高级设置</summary><label>时区<input v-model="form.timezone" :disabled="busy" /></label><label class="inline-check"><input v-model="form.allow_tools" type="checkbox" :disabled="busy" />允许使用已绑定工具</label><p class="field-hint">默认只生成回复。启用后可能读写文件或调用外部服务。</p></details>
        <div class="model-actions"><button type="button" class="button button-ghost" :disabled="busy" @click="close">取消</button><button class="button button-primary" :disabled="busy||!form.agent_id">{{busy?'保存中…':'保存任务'}}</button></div>
      </form>
    </dialog>
    <dialog ref="deletion" class="conversation-dialog" aria-labelledby="delete-automation-title" @cancel.prevent="close"><h2 id="delete-automation-title">删除「{{ deleting?.name }}」？</h2><p>已有运行结果和对话会保留。</p><p v-if="error" class="field-error" role="alert">{{ error }}</p><div class="model-actions"><button class="button button-ghost" :disabled="busy" @click="close">取消</button><button class="button button-primary" :disabled="busy" @click="deleting&&action(deleting,'delete')">确认删除</button></div></dialog>
  </div>
</template>
