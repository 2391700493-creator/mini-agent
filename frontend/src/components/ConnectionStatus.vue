<script setup lang="ts">
import { useSystemStore } from '../stores/system'
import AppIcon from './AppIcon.vue'
const system = useSystemStore()
</script>

<template>
  <div class="connection-block">
    <div class="connection-summary">
      <span class="connection-state" role="status" aria-live="polite">
        <span class="status-dot" :class="{ 'is-connected': system.status === 'ready' }" />
        {{ system.label }}
      </span>
      <button class="button button-ghost connection-button" :disabled="system.status === 'loading'" @click="system.checkConnection">
        <AppIcon name="refresh" :class="{ spinning: system.status === 'loading' }" />
        {{ system.status === 'error' ? '重试连接' : '检查连接' }}
      </button>
    </div>
    <p v-if="system.error" class="connection-error" role="alert">{{ system.error }}</p>
  </div>
</template>
