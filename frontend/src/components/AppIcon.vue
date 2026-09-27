<script setup lang="ts">
import { inject, ref, type Ref } from 'vue'
import type { IconName } from '../router/modules'
import { materialPaths } from '../assets/material-symbols'
defineProps<{ name: IconName }>()
const useMaterialSymbols = inject<Readonly<Ref<boolean>>>('useMaterialSymbols', ref(false))
const paths: Record<IconName, string> = {
  folder: 'M3 6h7l2 2h9v12H3V6Z',
  clock: 'M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18ZM12 7v5l3 2',
  chat: 'M20 11.5a7.5 7.5 0 0 1-7.5 7.5H5l-3 3V11.5a9 9 0 0 1 18 0ZM7 10h8M7 14h5',
  agent: 'M8 4h8l5 8-5 8H8l-5-8 5-8ZM8 4l4 8 4-8M3 12h18M8 20l4-8 4 8',
  model: 'm12 3 9 5-9 5-9-5 9-5ZM3 12l9 5 9-5M3 16l9 5 9-5',
  tool: 'm14 6 4 4m-8 0L3 17a2.8 2.8 0 0 0 4 4l7-7a6 6 0 0 0 7-8l-4 4-3-3 4-4a6 6 0 0 0-8 7Z',
  mcp: 'm8 8 3-3a4.3 4.3 0 0 1 6 6l-3 3M10 10l-3 3a4.3 4.3 0 0 0 6 6l3-3M9 15l6-6M5 19l-2 2M19 5l2-2',
  skill: 'M5 4h7v16H5a2 2 0 0 0-2 1V6a2 2 0 0 1 2-2ZM19 4h-7v16h7a2 2 0 0 1 2 1V6a2 2 0 0 0-2-2ZM7 8h2m6 0h2M7 12h2m6 0h2',
  history: 'M3 10a9 9 0 1 1 1 7M3 4v6h6M12 7v6l4 2',
  evaluation: 'M9 4V2h6v2M8 4H5v17h14V4h-3M8 3h8v4H8V3Zm0 11 3 3 5-6',
  arrow: 'M4 12h16m-6-6 6 6-6 6',
  refresh: 'M20 10a8 8 0 0 0-14-4L3 9m0-6v6h6m-5 5a8 8 0 0 0 14 4l3-3m0 6v-6h-6',
  chevron: 'm9 6 6 6-6 6',
  info: 'M12 11v6m0-10v.1M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z',
  check: 'm5 12 4 4L19 6',
  user: 'M16 8a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM4 21v-2a8 8 0 0 1 16 0v2',
  close: 'm6 6 12 12M6 18 18 6',
  attach: 'm8 13 7-7a3 3 0 0 1 4 4l-9 9a5 5 0 0 1-7-7L13 2M6 15l9-9',
  search: 'M16 10a6 6 0 1 1-12 0 6 6 0 0 1 12 0Zm-1 5 6 6',
  write: 'm15 3 6 6M4 20l5-1L21 7l-5-5L4 14v6Z',
  send: 'M12 20V4m-6 6 6-6 6 6',
  add: 'M12 5v14M5 12h14',
  copy: 'M9 8V3H3v14h5M8 8h13v13H8V8Z',
  share: 'M12 16V3m-4 4 4-4 4 4M5 12v9h14v-9',
  feedback: 'M2 11V7h2v4H2Zm2-4 3-5h1v4h3l-1 5H4M22 13v4h-2v-4h2Zm-2 4-3 5h-1v-4h-3l1-5h6',
  more: 'M5 12h.01M12 12h.01M19 12h.01',
}
</script>

<template>
  <svg v-if="useMaterialSymbols" viewBox="0 -960 960 960" fill="currentColor" aria-hidden="true" class="app-icon material-icon">
    <path v-for="(path, index) in materialPaths[name]" :key="index" :d="path" />
  </svg>
  <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="app-icon">
    <path :d="paths[name]" />
  </svg>
</template>
