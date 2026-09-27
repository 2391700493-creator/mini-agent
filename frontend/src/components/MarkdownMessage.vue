<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js/lib/common'

const props = defineProps<{ content: string }>()

const codeBlocks = new Map<string, string>()
let codeIndex = 0
const markdown = new MarkdownIt({
  breaks: true,
  html: false,
  linkify: true,
})
const originalLinkOpen = markdown.renderer.rules.link_open || ((tokens, index, options, _env, self) => self.renderToken(tokens, index, options))
markdown.renderer.rules.link_open = (tokens, index, options, env, self) => {
  tokens[index]?.attrSet('target', '_blank')
  tokens[index]?.attrSet('rel', 'noopener noreferrer')
  return originalLinkOpen(tokens, index, options, env, self)
}
markdown.renderer.rules.fence = (tokens, index) => {
  const token = tokens[index]
  if (!token) return ''
  const language = token.info.trim().split(/\s+/)[0] || ''
  const id = `code-${codeIndex++}`
  codeBlocks.set(id, token.content)
  const code = language && hljs.getLanguage(language)
    ? hljs.highlight(token.content, { language, ignoreIllegals: true }).value
    : markdown.utils.escapeHtml(token.content)
  const label = markdown.utils.escapeHtml(language || '文本')
  const languageClass = language ? ` language-${markdown.utils.escapeHtml(language)}` : ''
  return `<div class="markdown-code-block"><div class="markdown-code-heading"><span>${label}</span><button type="button" data-copy-code="${id}">复制代码</button></div><pre><code class="${languageClass.trim()}">${code}</code></pre></div>`
}

const rendered = computed(() => {
  codeBlocks.clear()
  codeIndex = 0
  return markdown.render(props.content)
})

async function copyCode(event: MouseEvent) {
  const button = (event.target as Element | null)?.closest<HTMLButtonElement>('[data-copy-code]')
  const id = button?.dataset.copyCode
  if (!id) return
  const content = codeBlocks.get(id)
  if (content === undefined) return
  try {
    await navigator.clipboard.writeText(content)
    button.textContent = '已复制'
    window.setTimeout(() => { if (button.isConnected) button.textContent = '复制代码' }, 1800)
  } catch { button.textContent = '未复制' }
}
</script>

<template>
  <div class="markdown-message" @click="copyCode" v-html="rendered" />
</template>
