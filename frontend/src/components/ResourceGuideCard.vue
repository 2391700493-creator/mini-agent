<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import type { IconName } from '../router/modules'
defineProps<{ title: string; description: string; icon: IconName; steps: string[]; action: string; to?: string; disabled?: boolean }>()
defineEmits<{ choose: [] }>()
</script>
<template>
  <article class="resource-guide-card" :aria-label="title">
    <span class="resource-guide-icon"><AppIcon :name="icon" /></span>
    <div><h3>{{ title }}</h3><p>{{ description }}</p></div>
    <ol><li v-for="(step, index) in steps" :key="step"><span>{{ index + 1 }}</span>{{ step }}</li></ol>
    <RouterLink v-if="to" :to="to" class="resource-guide-action" :aria-label="`${title}：${action}`">{{ action }}<AppIcon name="arrow" /></RouterLink>
    <button v-else type="button" :disabled="disabled" class="resource-guide-action" :aria-label="`${title}：${action}`" @click="$emit('choose')">{{ action }}<AppIcon name="arrow" /></button>
  </article>
</template>
