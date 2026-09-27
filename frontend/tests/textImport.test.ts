import { File as NodeFile } from 'node:buffer'
import { describe, expect, it } from 'vitest'
import { importTextFile, MAX_TEXT_FILE_BYTES } from '../src/utils/textImport'

const file = (content: string | Uint8Array, name = '笔记.md') => new NodeFile([content], name) as unknown as File

describe('文本导入边界', () => {
  it('保留 UTF-8 正文、换行和 Markdown 原文', async () => {
    const content = '# 目标\n\n保持清晰。\n'
    expect(await importTextFile(file(content))).toBe(content)
  })
  it('拒绝未支持格式、空文件和二进制内容', async () => {
    await expect(importTextFile(file('内容', '文档.pdf'))).rejects.toThrow('暂不支持 PDF')
    await expect(importTextFile(file('  \n'))).rejects.toThrow('没有可添加的文本')
    await expect(importTextFile(file(new Uint8Array([0, 1, 2])))).rejects.toThrow('非文本内容')
    await expect(importTextFile(file(new Uint8Array([255, 254])))).rejects.toThrow('UTF-8')
  })
  it('同时限制文件字节数和消息字符数', async () => {
    await expect(importTextFile(file('x'.repeat(MAX_TEXT_FILE_BYTES + 1)))).rejects.toThrow('5 MiB')
    await expect(importTextFile(file('x'.repeat(100001)))).rejects.toThrow('消息长度上限')
    expect((await importTextFile(file('x'.repeat(100000)))).length).toBe(100000)
  })
})
