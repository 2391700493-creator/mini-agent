import { describe, expect, it } from 'vitest'
import { importAttachment, MAX_ATTACHMENT_BYTES } from '../src/utils/attachmentImport'
function file(name: string, bytes: Uint8Array, size = bytes.length) {
  return { name, size, arrayBuffer: async () => bytes.buffer } as File
}
describe('多模态附件导入', () => {
  it('编码图片并保留单独的 MIME，不占据文本草稿', async () => {
    expect(await importAttachment(file('照片.png', new Uint8Array([137, 80, 78, 71])))).toEqual({ name: '照片.png', mime_type: 'image/png', data: 'iVBORw==' })
  })
  it('支持 PDF，拒绝未知格式、空文件、越界大小和非法名称', async () => {
    expect((await importAttachment(file('文件.pdf', new TextEncoder().encode('%PDF-1.7')))).mime_type).toBe('application/pdf')
    await expect(importAttachment(file('video.mp4', new Uint8Array([1])))).rejects.toThrow('支持 PNG')
    await expect(importAttachment(file('empty.png', new Uint8Array()))).rejects.toThrow('文件为空')
    await expect(importAttachment(file('large.png', new Uint8Array([1]), MAX_ATTACHMENT_BYTES + 1))).rejects.toThrow('5 MiB')
    await expect(importAttachment(file('../a.png', new Uint8Array([1])))).rejects.toThrow('文件名')
  })
  it('文本保留 UTF-8 与字符上限，拒绝无效编码', async () => {
    await expect(importAttachment(file('text.md', new Uint8Array([255])))).rejects.toThrow('UTF-8')
    const valid = await importAttachment(file('text.md', new TextEncoder().encode('材料')))
    expect(valid).toEqual({ name: 'text.md', mime_type: 'text/markdown', data: '5p2Q5paZ' })
  })
})
