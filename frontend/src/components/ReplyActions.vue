<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import IconAction from './IconAction.vue'
import PopoverTransition from './PopoverTransition.vue'
import { saveMessageFeedback, type ChatMessage, type MessageFeedback } from '../api/chat'
const props = defineProps<{ message: ChatMessage; canRegenerate: boolean }>()
const emit = defineEmits<{ regenerate: []; feedback: [rating: MessageFeedback] }>()
const copied = ref<'copy' | 'share' | null>(null)
const feedbackOpen = ref(false)
const saving = ref(false)
const error = ref('')
const feedbackTrigger = ref<InstanceType<typeof IconAction>>()
const feedbackArea = ref<HTMLElement>()
let timer: ReturnType<typeof setTimeout> | undefined
async function copy(action: 'copy' | 'share') {
  error.value = ''
  try {
    await navigator.clipboard.writeText(props.message.content)
    copied.value = action
    clearTimeout(timer)
    timer = setTimeout(() => { copied.value = null }, 1800)
  } catch { error.value = '复制失败，请检查剪贴板权限。' }
}
async function feedback(rating: MessageFeedback) {
  if (saving.value) return
  saving.value = true; error.value = ''
  try {
    const result = await saveMessageFeedback(props.message.conversation_id, props.message.id, rating)
    emit('feedback', result.feedback_rating ?? null)
    feedbackOpen.value = false
    saving.value = false
    await nextTick()
    feedbackTrigger.value?.focus()
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '反馈未保存，请重试。' }
  finally { saving.value = false }
}
function closeFeedback() { feedbackOpen.value = false; void nextTick(() => feedbackTrigger.value?.focus()) }
function outside(event: PointerEvent) {
  if (feedbackOpen.value && !feedbackArea.value?.contains(event.target as Node)) feedbackOpen.value = false
}
onMounted(() => document.addEventListener('pointerdown', outside))
onUnmounted(() => { clearTimeout(timer); document.removeEventListener('pointerdown', outside) })
</script>
<template>
  <div class="reply-actions-wrap">
    <div class="chat-message-actions" aria-label="回复操作">
      <IconAction :label="copied === 'copy' ? '已复制' : '复制'" :icon="copied === 'copy' ? 'check' : 'copy'" @click="copy('copy')" />
      <IconAction :label="copied === 'share' ? '已复制' : '分享'" :icon="copied === 'share' ? 'check' : 'share'" @click="copy('share')" />
      <span ref="feedbackArea" class="reply-feedback" @keydown.esc.stop.prevent="closeFeedback">
        <IconAction ref="feedbackTrigger" label="反馈" icon="feedback" :expanded="feedbackOpen" :pressed="!!message.feedback_rating" :disabled="saving" :tooltip="message.feedback_rating === 'helpful' ? '反馈：有帮助' : message.feedback_rating === 'unhelpful' ? '反馈：没帮助' : '反馈'" @click="feedbackOpen = !feedbackOpen" />
        <PopoverTransition>
        <div v-if="feedbackOpen" class="reply-feedback-picker" role="group" aria-label="这条回复有帮助吗？">
          <button type="button" :disabled="saving" :aria-pressed="message.feedback_rating === 'helpful'" @click="feedback('helpful')">有帮助</button>
          <button type="button" :disabled="saving" :aria-pressed="message.feedback_rating === 'unhelpful'" @click="feedback('unhelpful')">没帮助</button>
          <button v-if="message.feedback_rating" type="button" :disabled="saving" @click="feedback(null)">取消反馈</button>
        </div>
        </PopoverTransition>
      </span>
      <IconAction label="重新生成" icon="refresh" :disabled="!canRegenerate" :tooltip="canRegenerate ? '重新生成' : '仅可重新生成最新回复'" @click="emit('regenerate')" />
    </div>
    <p v-if="error" class="field-error" role="alert">{{ error }}</p>
  </div>
</template>
