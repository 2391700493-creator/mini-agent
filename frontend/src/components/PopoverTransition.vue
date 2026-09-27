<script setup lang="ts">
// 离场只保留视觉衔接，菜单立即退出键盘和辅助技术的操作范围。
function enter(element: Element) {
  element.removeAttribute('inert')
  element.removeAttribute('aria-hidden')
}
function leave(element: Element) {
  element.setAttribute('inert', '')
  element.setAttribute('aria-hidden', 'true')
}
</script>

<template>
  <Transition name="motion-popover" @before-enter="enter" @before-leave="leave"><slot /></Transition>
</template>
