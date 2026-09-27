"""聊天附件校验与模型内容构造；原文件只持久化到 SQLite。"""

import base64
import binascii
import io
import logging
import multiprocessing
import warnings
from dataclasses import dataclass
from hashlib import sha256

from fastapi import HTTPException
from PIL import Image

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 10 * 1024 * 1024
MAX_TEXT_LENGTH = 100_000
IMAGE_TYPES = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP", "image/gif": "GIF"}
TEXT_TYPES = {"text/plain", "text/markdown", "text/csv", "application/json"}


@dataclass(frozen=True)
class PreparedAttachment:
    name: str
    mime_type: str
    data: bytes
    digest: str
    extracted_text: str | None = None
    width: int | None = None
    height: int | None = None


def decode_attachment(item):
    try:
        raw = base64.b64decode(item.data, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, "附件编码无效，请重新添加。") from None
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise HTTPException(422, "附件不能为空，且单个文件最多 5 MiB。")
    return raw


def pdf_worker(data, connection):
    # 独立进程有时间与输出边界，解析错误不包含文件正文或异常堆栈。
    logging.disable(logging.CRITICAL)
    try:
        import resource

        from pypdf import Configuration, PdfReader, apply_configuration

        resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
        config = Configuration(
            zlib_maximum_output_length=8 * 1024 * 1024,
            lzw_maximum_output_length=8 * 1024 * 1024,
            run_length_maximum_output_length=8 * 1024 * 1024,
            array_based_stream_maximum_output_length=8 * 1024 * 1024,
            maximum_declared_stream_length=8 * 1024 * 1024,
            page_tree_maximum_entries=1000,
            page_tree_maximum_depth=30,
            xform_maximum_invocations_per_extraction=100,
            jbig2dec_binary=None,
        )
        with apply_configuration(config):
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted:
                connection.send((False, "PDF 已加密，请先解密后添加。"))
                return
            if len(reader.pages) > 50:
                connection.send((False, "PDF 最多 50 页，请拆分后添加。"))
                return
            parts = []
            length = 0
            for page in reader.pages:
                part = page.extract_text() or ""
                length += len(part)
                if length > MAX_TEXT_LENGTH:
                    connection.send((False, "PDF 文本超过 100,000 字符，请拆分后添加。"))
                    return
                parts.append(part)
            text = "\n\n".join(parts)
            if not text.strip():
                connection.send((False, "PDF 没有可提取的文本；扫描件请转为图片添加。"))
                return
            connection.send((True, text))
    except Exception:
        connection.send((False, "PDF 无法解析，请使用有效的文本 PDF。"))
    finally:
        connection.close()


def extract_pdf(data):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=pdf_worker, args=(data, sender), daemon=True)
    try:
        process.start()
        sender.close()
        if not receiver.poll(6):
            raise HTTPException(422, "PDF 解析超时，请拆分或转换文件后重试。")
        try:
            success, value = receiver.recv()
        except EOFError:
            raise HTTPException(422, "PDF 无法解析，请拆分或转换文件后重试。") from None
        if not success:
            raise HTTPException(422, value)
        return value
    finally:
        sender.close()
        receiver.close()
        if process.pid:
            if process.is_alive():
                process.terminate()
            process.join(1)
            if process.is_alive():
                process.kill()
                process.join()


def prepare_attachments(items):
    prepared = []
    total = 0
    text_length = 0
    for item in items:
        raw = decode_attachment(item)
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise HTTPException(422, "一次最多添加 10 MiB 附件，请分开发送。")
        text = None
        width = height = None
        if item.mime_type in IMAGE_TYPES:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(raw)) as image:
                        width, height = image.size
                        if image.format != IMAGE_TYPES[item.mime_type]:
                            raise ValueError
                        if width * height > 20_000_000 or max(width, height) > 8192:
                            raise HTTPException(422, "图片最多 2,000 万像素，单边最多 8192 像素。")
                        if getattr(image, "n_frames", 1) != 1:
                            raise HTTPException(422, "暂不支持动态图，请添加静态图片。")
                        image.verify()
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(422, "图片格式或内容无效，请重新添加。") from None
        elif item.mime_type == "application/pdf":
            if not raw.startswith(b"%PDF-"):
                raise HTTPException(422, "PDF 内容无效，请重新添加。")
            text = extract_pdf(raw)
        elif item.mime_type in TEXT_TYPES:
            try:
                text = raw.decode("utf-8", errors="strict")
                if not text.strip() or any(ord(c) < 32 and c not in "\t\r\n" for c in text):
                    raise ValueError
            except (ValueError, UnicodeError):
                raise HTTPException(422, "文本附件必须是非空 UTF-8 纯文本。") from None
        else:
            raise HTTPException(422, "支持 PNG、JPEG、WebP、静态 GIF、PDF、TXT、MD、CSV 和 JSON。")
        text_length += len(text or "")
        if text_length > MAX_TEXT_LENGTH:
            raise HTTPException(422, "附件文本合计超过 100,000 字符，请精简后发送。")
        prepared.append(
            PreparedAttachment(
                item.name, item.mime_type, raw, sha256(raw).hexdigest(), text, width, height
            )
        )
    return prepared


def model_content(content, attachments):
    if not attachments:
        return content
    parts = []
    if content:
        parts.append({"type": "text", "text": content})
    for item in attachments:
        parts.append({"type": "text", "text": f"文件：{item.name}"})
        if item.mime_type in IMAGE_TYPES:
            encoded = base64.b64encode(item.data).decode("ascii")
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{item.mime_type};base64,{encoded}",
                        "detail": "low",
                    },
                }
            )
        else:
            parts.append({"type": "text", "text": item.extracted_text})
    return parts


def text_content(content):
    """摘要保留文件名和文本；图片正文不会混进摘要或运行日志。"""
    if isinstance(content, str):
        return content
    return "\n".join(
        part["text"] if part["type"] == "text" else "[历史图片附件]" for part in content
    )


def redact_content(content, secrets, redact):
    if isinstance(content, str):
        return redact(content, secrets)
    return [
        {**part, "text": redact(part["text"], secrets)} if part["type"] == "text" else part
        for part in content
    ]


def valid_model_content(value):
    if isinstance(value, str):
        return True
    if not isinstance(value, list) or not value or len(value) > 16:
        return False
    for part in value:
        if not isinstance(part, dict):
            return False
        if part.get("type") == "text":
            if set(part) != {"type", "text"} or not isinstance(part["text"], str):
                return False
        elif part.get("type") == "image_url":
            image = part.get("image_url")
            if set(part) != {"type", "image_url"} or not isinstance(image, dict):
                return False
            if set(image) != {"url", "detail"} or image["detail"] != "low":
                return False
            if not isinstance(image["url"], str) or not any(
                image["url"].startswith(f"data:{mime};base64,") for mime in IMAGE_TYPES
            ):
                return False
        else:
            return False
    return True


def has_images(messages):
    return any(
        isinstance(item.get("content"), list)
        and any(part.get("type") == "image_url" for part in item["content"])
        for item in messages
    )
