import { computed, onBeforeUnmount, onMounted, ref, type Ref } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'

// 快照仅保留在组件内存中，不写入浏览器存储。
export function useUnsavedChanges(snapshot: () => string, ready: Ref<boolean>, saving: Ref<boolean>) {
  const baseline = ref(snapshot())
  const dirty = computed(() => ready.value && baseline.value !== snapshot())
  const markSaved = () => { baseline.value = snapshot() }
  const canLeave = () => {
    if (!dirty.value) return true
    if (saving.value) return false
    return window.confirm('有尚未保存的修改，确定离开？')
  }
  const beforeUnload = (event: BeforeUnloadEvent) => {
    if (!dirty.value) return
    event.preventDefault()
    event.returnValue = ''
  }
  onBeforeRouteLeave(canLeave)
  onBeforeRouteUpdate(canLeave)
  onMounted(() => window.addEventListener('beforeunload', beforeUnload))
  onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
  return { dirty, markSaved }
}
