import type { AttachmentInput } from '../api/chat'
import { importTextFile } from './textImport'

export const MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
export const MAX_ATTACHMENTS_BYTES = 10 * 1024 * 1024
const types: Record<string, string> = {
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif',
  pdf: 'application/pdf', txt: 'text/plain', md: 'text/markdown', csv: 'text/csv', json: 'application/json',
}
export async function importAttachment(file: File): Promise<AttachmentInput> {
  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  const mime = types[extension]
  if (!mime) throw new Error('支持 PNG、JPEG、WebP、静态 GIF、PDF、TXT、MD、CSV 和 JSON。')
  if (!file.size) throw new Error('文件为空，请添加有内容的文件。')
  if (file.size > MAX_ATTACHMENT_BYTES) throw new Error('单个文件最多 5 MiB，请压缩或拆分后添加。')
  if (file.name.length > 200 || /[\x00-\x1f/\\]/.test(file.name)) throw new Error('文件名无效或过长，请重命名后添加。')
  if (['txt', 'md', 'csv', 'json'].includes(extension)) await importTextFile(file)
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 32768) binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768))
  return { name: file.name, mime_type: mime, data: btoa(binary) }
}
