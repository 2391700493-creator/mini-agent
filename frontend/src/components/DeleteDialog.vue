<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

const opened = defineModel<boolean>({ required: true })
const props = defineProps<{ title: string; description: string; busy: boolean; error: string }>()
const emit = defineEmits<{ confirm: [] }>()
const dialog = ref<HTMLDialogElement>()
const cancel = ref<HTMLButtonElement>()
let trigger: HTMLElement | null = null
function close() { if (!props.busy) opened.value = false }
watch(opened, async value => {
  if (value) {
    trigger = document.activeElement as HTMLElement
    await nextTick()
    dialog.value?.showModal()
    cancel.value?.focus()
  } else {
    dialog.value?.close()
    if (trigger?.isConnected) trigger.focus()
    else document.getElementById('page-title')?.focus()
  }
})
</script>

<template>
  <dialog ref="dialog" class="conversation-dialog delete-confirmation-dialog" :aria-label="title" @cancel.prevent="close">
    <h2>{{ title }}</h2><p>{{ description }}</p>
    <p v-if="error" class="field-error" role="alert">{{ error }}</p>
    <div class="model-actions"><button ref="cancel" type="button" class="button button-ghost" :disabled="busy" @click="close">取消</button><button type="button" class="button button-primary" :disabled="busy" @click="emit('confirm')">{{ busy ? '正在删除…' : '确认删除' }}</button></div>
  </dialog>
</template>
