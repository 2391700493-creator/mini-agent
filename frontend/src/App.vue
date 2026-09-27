<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, provide, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppSidebar from './components/AppSidebar.vue'
import { useSystemStore } from './stores/system'

const route = useRoute()
provide('useMaterialSymbols', ref(true))
const system = useSystemStore()
const sidebarCollapsed = ref(window.innerWidth < 900)
let previousWidth = window.innerWidth
function responsiveSidebar() {
  if (window.innerWidth < 900 && previousWidth >= 900) sidebarCollapsed.value = true
  previousWidth = window.innerWidth
}
function pointerInput() { document.documentElement.dataset.inputModality = 'pointer' }
function keyboardInput() { document.documentElement.dataset.inputModality = 'keyboard' }
async function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  await nextTick()
  document.getElementById(sidebarCollapsed.value ? 'sidebar-expand' : 'sidebar-collapse')?.focus()
}
onMounted(() => {
  void system.checkConnection()
  window.addEventListener('resize', responsiveSidebar)
  document.addEventListener('pointerdown', pointerInput, true)
  document.addEventListener('keydown', keyboardInput, true)
})
onUnmounted(() => {
  window.removeEventListener('resize', responsiveSidebar)
  document.removeEventListener('pointerdown', pointerInput, true)
  document.removeEventListener('keydown', keyboardInput, true)
  delete document.documentElement.dataset.inputModality
})
watch(() => route.path, async () => {
  await nextTick()
  document.querySelector<HTMLElement>('.main-panel')?.scrollTo?.({ top: 0 })
  document.querySelector<HTMLElement>('#page-title')?.focus({ preventScroll: true })
})
</script>

<template>
  <a class="skip-link" href="#main-content">跳转到主要内容</a>
  <div class="app-shell product-theme" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
    <AppSidebar :collapsed="sidebarCollapsed" @collapse="toggleSidebar" />
    <div class="main-panel">
      <main id="main-content" tabindex="-1">
        <RouterView :key="route.path" />
      </main>
    </div>
  </div>
</template>
