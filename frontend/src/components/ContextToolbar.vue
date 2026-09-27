<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { useChatStore } from '../stores/chat'
import * as workspace from '../api/workspace'
import AppIcon from './AppIcon.vue'
const chat = useChatStore()
const choosing = ref(false)
const error = ref('')
const trigger = ref<HTMLButtonElement>()
const fixed = computed(() => !!chat.current?.messages.length || chat.generating)
const label = computed(() => choosing.value ? '正在选择…' : chat.current?.folder === '.' ? '工作目录' : chat.current?.folder?.split('/').pop() || '选择本地文件夹')
let disposed = false
async function choose() {
  if (!chat.current || fixed.value || choosing.value) return
  const cid = chat.selected
  choosing.value = true; error.value = ''
  try {
    const result = await workspace.chooseFolder()
    if (disposed) return
    if (cid !== chat.selected || fixed.value) { error.value = '对话已变化，请重新选择文件夹。'; return }
    if (result.folder !== null && !await chat.update(cid, { folder: result.folder })) error.value = chat.error
  } catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : '选择失败，请重试。' }
  finally { choosing.value = false; if (!disposed) trigger.value?.focus() }
}
async function clear() { if (!await chat.update(chat.selected, { folder: null })) error.value = chat.error }
async function retry() { try { await workspace.syncArchive(chat.selected); await chat.select(chat.selected) } catch(e) { error.value = e instanceof Error ? e.message : '同步失败' } }
onUnmounted(() => { disposed = true })
</script>
<template>
  <div class="context-toolbar" role="region" aria-label="上下文工具栏">
    <button ref="trigger" type="button" class="context-folder-chip" :disabled="!chat.current || fixed || chat.loading || choosing || !!chat.busy[chat.selected]" :title="fixed ? '文件夹已绑定；新建对话可选择其他文件夹' : '从本地授权工作目录选择文件夹'" @click="choose"><AppIcon name="folder" /><span>{{ label }}</span><AppIcon name="chevron" class="folder-chevron" /></button>
    <button v-if="chat.current?.folder && !fixed" type="button" class="context-folder-clear" aria-label="取消文件夹绑定" :disabled="choosing || !!chat.busy[chat.selected]" @click="clear"><AppIcon name="close" /></button>
    <span v-if="chat.current?.folder" class="context-folder-note">回复自动保存为 MD</span>
    <p v-if="error" class="field-error" role="alert">{{ error }}</p>
    <p v-if="chat.current?.archive_error" class="field-error" role="alert">{{ chat.current.archive_error }} <button @click="retry">重试同步</button></p>
  </div>
</template>
