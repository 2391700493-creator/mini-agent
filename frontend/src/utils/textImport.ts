export const MAX_TEXT_FILE_BYTES = 5 * 1024 * 1024
export const MAX_DRAFT_LENGTH = 100000

export async function importTextFile(file: File): Promise<string> {
  if (!/\.(txt|md|csv|json)$/i.test(file.name)) throw new Error('支持 TXT、Markdown、CSV 和 JSON 文本；暂不支持 PDF 和图片。')
  if (file.size > MAX_TEXT_FILE_BYTES) throw new Error('文件超过 5 MiB，请精简后再添加。')
  let text: string
  try { text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()) }
  catch { throw new Error('文件无法读取，请使用 UTF-8 编码的文本文件。') }
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(text)) throw new Error('文件包含非文本内容，请使用纯文本文件。')
  if (!text.trim()) throw new Error('这个文件没有可添加的文本。')
  if (text.length > MAX_DRAFT_LENGTH) throw new Error('文件文本超过消息长度上限，请精简后再添加。')
  return text
}
