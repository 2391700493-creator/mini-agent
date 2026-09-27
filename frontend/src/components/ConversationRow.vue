<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import type { Conversation } from '../api/chat'
import AppIcon from './AppIcon.vue'
const props = defineProps<{ item: Conversation; active: boolean; busy?: boolean; detailed?: boolean }>()
const emit = defineEmits<{ open: [id: string]; manage: [item: Conversation]; delete: [item: Conversation] }>()
const trigger = ref<HTMLButtonElement>()
const menu = ref<HTMLElement>()
const opened = ref(false)
const position = ref({ left: '0px', top: '0px' })
const updated = computed(() => {
  const date = new Date(props.item.updated_at)
  if (Number.isNaN(date.getTime())) return null
  return {
    short: date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }),
    full: date.toLocaleString('zh-CN', { hour12: false }),
  }
})
function close(restore = false) { opened.value = false; if (restore) trigger.value?.focus() }
async function toggle() {
  if (opened.value) { close(true); return }
  const box = trigger.value?.getBoundingClientRect()
  if (!box) return
  position.value = { left: `${Math.min(window.innerWidth - 192, Math.max(8, box.right - 176))}px`, top: `${Math.min(window.innerHeight - 100, box.bottom + 4)}px` }
  opened.value = true
  await nextTick(); menu.value?.querySelector<HTMLButtonElement>('button')?.focus()
}
function action(kind: 'manage' | 'delete') { close(true); if (kind === 'manage') emit('manage', props.item); else emit('delete', props.item) }
function key(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(true) }
  if (event.key === 'Tab') { close(true); return }
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault()
    const buttons = [...(menu.value?.querySelectorAll<HTMLButtonElement>('button') ?? [])]
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
    const target = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowUp' ? -1 : 1) + buttons.length) % buttons.length
    buttons[target]?.focus()
  }
}
function outside(event: Event) { if (event.target instanceof Node && !menu.value?.contains(event.target) && !trigger.value?.contains(event.target)) close() }
function drag(event: DragEvent) {
  if (!event.dataTransfer || props.busy) { event.preventDefault(); return }
  close()
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('application/x-mini-agent-conversation', props.item.id)
}
function resize() { close() }
function listen(on: boolean) {
  const method = on ? 'addEventListener' : 'removeEventListener'
  document[method]('pointerdown', outside)
  document[method]('focusin', outside)
  window[method]('resize', resize)
  window[method]('scroll', resize, true)
}
watch(opened, listen)
onUnmounted(() => listen(false))
</script>
<template>
  <div class="conversation-row" :class="{ selected: active, 'has-details': detailed }" :draggable="!busy" @dragstart="drag">
    <button class="conversation-open" :title="item.title" :aria-label="item.title" :aria-describedby="detailed && updated ? `conversation-updated-${item.id}` : undefined" :aria-current="active ? 'true' : undefined" @click="emit('open', item.id)">
      <AppIcon name="chat" />
      <span class="conversation-row-copy">
        <span class="conversation-title">{{ !detailed && item.pinned ? '· ' : '' }}{{ item.title }}</span>
        <span v-if="detailed" class="conversation-row-meta">
          <time v-if="updated" :id="`conversation-updated-${item.id}`" :datetime="item.updated_at" :title="updated.full">{{ updated.short }}</time>
          <span v-if="busy" class="conversation-row-status"><span aria-hidden="true" />生成中</span>
          <span v-else-if="item.pinned" class="conversation-row-pinned">置顶</span>
        </span>
      </span>
    </button>
    <button :id="`conversation-actions-${item.id}`" ref="trigger" class="conversation-more" :aria-label="`会话操作：${item.title}`" aria-haspopup="menu" :aria-expanded="opened" :aria-controls="`conversation-menu-${item.id}`" :disabled="busy" @click="toggle">···</button>
    <Teleport to="body"><div v-if="opened" :id="`conversation-menu-${item.id}`" ref="menu" class="conversation-menu" :style="position" role="menu" :aria-label="`会话操作：${item.title}`" @keydown="key"><button role="menuitem" @click="action('manage')"><AppIcon name="write" />重命名与归属</button><button role="menuitem" class="menu-danger" @click="action('delete')"><AppIcon name="close" />删除对话</button></div></Teleport>
  </div>
</template>
