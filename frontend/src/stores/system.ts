import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { getHealth } from '../api/health'

export const useSystemStore = defineStore('system', () => {
  const status = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const error = ref('')
  const label = computed(() => ({
    idle: '等待连接', loading: '正在连接', ready: '本地服务已连接', error: '本地服务未就绪',
  })[status.value])

  async function checkConnection() {
    if (status.value === 'loading') return
    status.value = 'loading'
    error.value = ''
    try {
      await getHealth()
      status.value = 'ready'
    } catch (cause) {
      status.value = 'error'
      error.value = cause instanceof Error ? cause.message : '连接失败，请重试。'
    }
  }
  return { status, error, label, checkConnection }
})
