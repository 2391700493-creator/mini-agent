<script setup lang="ts">
import { ref, useId } from 'vue'
import AppIcon from './AppIcon.vue'
import type { IconName } from '../router/modules'
withDefaults(defineProps<{ label: string; icon: IconName; tooltip?: string; disabled?: boolean; pressed?: boolean; expanded?: boolean }>(), { pressed: undefined, expanded: undefined })
defineEmits<{ click: [] }>()
const tooltipId = useId()
const button = ref<HTMLButtonElement>()
defineExpose({ focus: () => button.value?.focus() })
</script>
<template>
  <span class="icon-action">
    <button ref="button" type="button" class="icon-action-button" :aria-label="label" :aria-describedby="tooltipId" :aria-pressed="pressed" :aria-expanded="expanded" :disabled="disabled" @click="$emit('click')">
      <span class="action-icon-slot" aria-hidden="true"><Transition name="motion-icon"><AppIcon :key="icon" :name="icon" /></Transition></span><span class="visually-hidden">{{ label }}</span>
    </button>
    <span :id="tooltipId" class="icon-tooltip" role="tooltip">{{ tooltip || label }}</span>
  </span>
</template>
