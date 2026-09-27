<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { ChatAgent } from '../api/chat'
import AppIcon from './AppIcon.vue'
import PopoverTransition from './PopoverTransition.vue'
const props = defineProps<{ agents: ChatAgent[]; modelValue?: string | null; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [id: string] }>()
const root = ref<HTMLElement>()
const trigger = ref<HTMLButtonElement>()
const list = ref<HTMLElement>()
const opened = ref(false)
const active = ref(-1)
const chosen = computed(() => props.agents.find(item => item.id === props.modelValue && item.is_ready !== false))
const available = computed(() => props.agents.map((item, index) => item.is_ready !== false ? index : -1).filter(index => index >= 0))
const activeId = computed(() => active.value >= 0 ? `agent-option-${props.agents[active.value]?.id}` : undefined)
function close(restore = false) { opened.value = false; if (restore) trigger.value?.focus() }
async function open() {
  if (props.disabled) return
  if (opened.value) { close(true); return }
  opened.value = true
  active.value = props.agents.findIndex(item => item.id === chosen.value?.id)
  if (active.value < 0) active.value = available.value[0] ?? -1
  await nextTick(); list.value?.focus()
}
function choose(index: number) {
  const item = props.agents[index]
  if (!item || item.is_ready === false || props.disabled) return
  close(true)
  if (item.id !== chosen.value?.id) emit('update:modelValue', item.id)
}
function key(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(true); return }
  if (event.key === 'Tab') { close(true); return }
  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.stopPropagation(); choose(active.value); return }
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  event.preventDefault(); event.stopPropagation()
  const indices = available.value
  if (!indices.length) return
  const index = indices.indexOf(active.value)
  active.value = event.key === 'Home' ? indices[0]! : event.key === 'End' ? indices.at(-1)! : indices[(index + (event.key === 'ArrowUp' ? -1 : 1) + indices.length) % indices.length]!
  void nextTick(() => document.getElementById(activeId.value || '')?.scrollIntoView?.({block:'nearest'}))
}
function outside(event: Event) { if (event.target instanceof Node && !root.value?.contains(event.target)) close() }
watch(() => props.disabled, value => { if (value) close() })
watch(() => props.modelValue, () => close())
onMounted(() => { document.addEventListener('pointerdown', outside); document.addEventListener('focusin', outside) })
onUnmounted(() => { document.removeEventListener('pointerdown', outside); document.removeEventListener('focusin', outside) })
</script>
<template>
  <div ref="root" class="chat-agent-picker" :class="{ 'is-open': opened }">
    <AppIcon name="agent" class="agent-trigger-icon" />
    <button id="chat-agent" ref="trigger" type="button" class="agent-picker-trigger" :value="chosen?.id || ''" :disabled="disabled" aria-label="对话 Agent" aria-haspopup="listbox" aria-controls="chat-agent-options" :aria-expanded="opened" @click="open" @keydown.down.prevent="open" @keydown.up.prevent="open"><span>{{ chosen?.name || (available.length ? '请选择 Agent' : '暂无可用 Agent') }}</span><AppIcon name="chevron" class="picker-chevron" /></button>
    <PopoverTransition>
    <div v-if="opened" class="agent-picker-popover">
      <p class="agent-picker-caption">选择 Agent</p>
      <div id="chat-agent-options" ref="list" class="agent-picker-list" role="listbox" aria-label="对话 Agent" tabindex="-1" :aria-activedescendant="activeId" @keydown="key">
        <button v-for="(agent, index) in agents" :id="`agent-option-${agent.id}`" :key="agent.id" type="button" class="agent-picker-option" :class="{ 'is-highlighted': index === active }" role="option" tabindex="-1" :aria-selected="chosen?.id === agent.id" :aria-disabled="agent.is_ready === false" @pointermove="active = agent.is_ready === false ? active : index" @click="choose(index)"><span class="agent-option-avatar"><AppIcon name="agent" /></span><span class="agent-option-copy"><strong>{{ agent.name }}</strong><small v-if="agent.is_ready === false">{{ agent.unavailable_reason || '暂不可用' }}</small><small v-else-if="agent.description" :title="agent.description">{{ agent.description }}</small></span><AppIcon v-if="chosen?.id === agent.id" name="check" class="agent-selected-check" /></button>
        <p v-if="!agents.length" class="sidebar-empty">暂无可用 Agent</p>
      </div>
    </div>
    </PopoverTransition>
  </div>
</template>
