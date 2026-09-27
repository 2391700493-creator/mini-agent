import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MarkdownMessage from '../src/components/MarkdownMessage.vue'

describe('MarkdownMessage', () => {
  it('安全渲染常用 Markdown，并为代码块提供复制入口', () => {
    const wrapper = mount(MarkdownMessage, {
      props: { content: '# 标题\n\n- 一\n- 二\n\n```ts\nconst value = 1\n```\n\n[链接](https://example.com)\n\n<script>alert(1)</script>' },
    })
    expect(wrapper.get('h1').text()).toBe('标题')
    expect(wrapper.findAll('li').map(item => item.text())).toEqual(['一', '二'])
    expect(wrapper.get('.markdown-code-heading').text()).toContain('ts')
    expect(wrapper.get('.markdown-code-heading button').text()).toBe('复制代码')
    expect(wrapper.get('a').attributes('target')).toBe('_blank')
    expect(wrapper.get('a').attributes('rel')).toBe('noopener noreferrer')
    expect(wrapper.html()).not.toContain('<script>')
  })
})
