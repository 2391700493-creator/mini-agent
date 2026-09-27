"""有界流式 Chat Completions 传输；工具调度由 Agent Runtime 负责。"""

import asyncio
import json
import math
import re
from dataclasses import dataclass, field

import httpx

from app.services.attachments import has_images
from app.services.model_connection import http_failure

CONTEXT_ERROR = "消息超过模型可用上下文容量，请缩短输入或新建会话。"


class ChatFailure(Exception):
    pass


def estimate_tokens(value) -> int:
    """兼容服务无统一 tokenizer；按 UTF-8 字节与结构开销做稳定、偏保守的估算。"""
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return max(1, math.ceil(len(encoded) / 3))


def estimate_request_tokens(messages, tools=None) -> int:
    # 每条消息补充角色、分隔符等协议开销；结果始终明确标为估算值。
    safe_messages = []
    image_tokens = 0
    for message in messages:
        item = dict(message)
        if isinstance(item.get("content"), list):
            parts = []
            for part in item["content"]:
                if part.get("type") == "image_url":
                    # 图片统一 low detail；为兼容不同 tokenizer 保守预留 4096 token。
                    image_tokens += 4096
                    parts.append({"type": "text", "text": "[图片]"})
                else:
                    parts.append(part)
            item["content"] = parts
        safe_messages.append(item)
    return (
        estimate_tokens(safe_messages)
        + image_tokens
        + 4 * len(messages)
        + (estimate_tokens(tools) if tools else 0)
    )


async def events(response):
    # 限制单帧与累计响应，按 SSE 空行组帧，兼容 CRLF 和分块 UTF-8。
    buffer = bytearray()
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > 16 * 1024 * 1024:
            raise ChatFailure("模型输出过长，回复未完成。")
        buffer.extend(chunk)
        while b"\n" in buffer:
            line, _, rest = buffer.partition(b"\n")
            buffer = bytearray(rest)
            if len(line) > 1024 * 1024:
                raise ChatFailure("模型流式响应过大，回复未完成。")
            yield line.rstrip(b"\r").decode("utf-8", errors="strict")
        if len(buffer) > 1024 * 1024:
            raise ChatFailure("模型流式响应过大，回复未完成。")
    if buffer:
        yield buffer.rstrip(b"\r").decode("utf-8", errors="strict")


@dataclass
class ModelReply:
    tool_calls: list[dict] = field(default_factory=list)
    usage: dict | None = None
    finish_reason: str | None = None


async def stream_reply(config, key, messages, transport=None, *, tools=None, reply=None):
    reply = reply if reply is not None else ModelReply()
    calls = {}

    estimate = estimate_request_tokens(messages, tools)
    if estimate + config.max_output_tokens > config.context_length:
        raise ChatFailure(CONTEXT_ERROR + "（按保守估算检查）")
    payload = {
        "model": config.model_id,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_output_tokens,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
    payload["stream_options"] = {"include_usage": True}
    try:
        async with (
            asyncio.timeout(300),
            httpx.AsyncClient(
                timeout=httpx.Timeout(60, connect=10),
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client,
            client.stream(
                "POST",
                f"{config.base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {key}", "Accept": "text/event-stream"},
            ) as response,
        ):
            if response.status_code != 200:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 1024 * 1024:
                        break
                try:
                    error = json.loads(body).get("error", {})
                    code = error.get("code") if isinstance(error, dict) else None
                except (ValueError, AttributeError):
                    code = None
                if code in {"context_length_exceeded", "max_context_length_exceeded"}:
                    raise ChatFailure(CONTEXT_ERROR)
                failure = http_failure(response.status_code, bytes(body))
                if failure.code == "request_rejected" and has_images(messages):
                    raise ChatFailure(
                        "模型服务未接受图片输入，请确认模型和接口支持视觉消息后重试。"
                    )
                raise ChatFailure(f"{failure.message}。{failure.suggestion}")
            data = []
            finish = None
            async for line in events(response):
                if line.startswith("data:"):
                    data.append(line[5:].lstrip(" "))
                elif not line and data:
                    raw = "\n".join(data)
                    data = []
                    if raw == "[DONE]":
                        reply.finish_reason = (
                            finish
                            if finish in {"stop", "tool_calls", "length", "content_filter"}
                            else "unknown"
                        )
                        if finish in {"stop", "tool_calls"}:
                            if bool(calls) != (finish == "tool_calls"):
                                raise ChatFailure("模型工具调用结束标记不一致。")
                            ids = set()
                            for index in sorted(calls):
                                call = calls[index]
                                if (
                                    not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", call["id"])
                                    or key in call["id"]
                                    or call["id"] in ids
                                    or not call["function"]["name"]
                                ):
                                    raise ChatFailure("模型工具调用标识格式不正确或重复。")
                                ids.add(call["id"])
                            reply.tool_calls = [calls[i] for i in sorted(calls)]
                            return
                        if finish == "length":
                            raise ChatFailure(
                                "已达到模型输出上限，回复未完成。可调整输出上限后重试。"
                            )
                        raise ChatFailure("模型未正常完成回答，回复未完成。")
                    event = json.loads(raw)
                    if not isinstance(event, dict) or "error" in event:
                        raise ChatFailure("模型流式输出发生错误，回复未完成。")
                    usage = event.get("usage")
                    if isinstance(usage, dict):
                        reply.usage = {
                            name: value if type(value) is int and value >= 0 else None
                            for name in ("prompt_tokens", "completion_tokens", "total_tokens")
                            for value in [usage.get(name)]
                        }
                        details = usage.get("prompt_tokens_details")
                        cached = details.get("cached_tokens") if isinstance(details, dict) else None
                        if cached is None:
                            cached = usage.get("cached_prompt_tokens")
                        reply.usage["cached_input_tokens"] = (
                            cached if type(cached) is int and cached >= 0 else None
                        )
                    choices = event.get("choices", [])
                    if not choices:
                        continue
                    choice = choices[0]
                    if choice.get("index", 0) != 0:
                        raise ChatFailure("模型返回了不支持的多路回复。")
                    delta = choice.get("delta", {})
                    if delta.get("function_call"):
                        raise ChatFailure("模型返回了不支持的旧版工具调用格式。")
                    for fragment in delta.get("tool_calls") or []:
                        index = fragment["index"]
                        if type(index) is not int or not 0 <= index < 32:
                            raise ChatFailure("单轮工具调用超过限制或索引无效。")
                        call = calls.setdefault(
                            index,
                            {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            },
                        )
                        if fragment.get("type", "function") != "function":
                            raise ChatFailure("模型工具调用类型不支持。")
                        if fragment.get("id"):
                            call["id"] += fragment["id"]
                        function = fragment.get("function") or {}
                        for name in ("name", "arguments"):
                            value = function.get(name, "")
                            if not isinstance(value, str):
                                raise ChatFailure("模型工具参数格式不正确。")
                            call["function"][name] += value
                        if len(json.dumps(call).encode()) > 1024 * 1024:
                            raise ChatFailure("模型工具参数超过 1 MiB。")
                    content = delta.get("content")
                    if content is not None:
                        if not isinstance(content, str):
                            raise ChatFailure("模型返回的正文格式不正确。")
                        if content:
                            yield content
                    finish = choice.get("finish_reason") or finish
            # 缺少正常终止标志，不能把意外断流当成完整回答。
            raise ChatFailure("模型输出中断，回复未完成，请稍后重试。")
    except (TimeoutError, httpx.TimeoutException):
        raise ChatFailure("模型请求超时，请稍后重试。") from None
    except httpx.HTTPError:
        raise ChatFailure("模型连接失败或输出中断，请检查模型服务后重试。") from None
    except (ValueError, TypeError, KeyError, AttributeError, IndexError):
        raise ChatFailure("模型流式响应格式不正确，回复未完成。") from None


class StreamRedactor:
    """在帧边界保留可能的密钥前缀，避免服务意外回显凭据到页面或数据库。"""

    def __init__(self, key):
        self.key = key
        self.pending = ""

    def push(self, delta):
        text = (self.pending + delta).replace(self.key, "[已隐藏]")
        keep = 0
        for length in range(1, min(len(self.key), len(text) + 1)):
            if text.endswith(self.key[:length]):
                keep = length
        self.pending = text[-keep:] if keep else ""
        return text[:-keep] if keep else text
