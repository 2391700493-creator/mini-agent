<script setup lang="ts">
defineProps<{ title: string; description: string }>()
</script>

<template>
  <header class="page-header">
    <h1 id="page-title" tabindex="-1">{{ title }}</h1>
    <p>{{ description }}</p>
  </header>
</template>
