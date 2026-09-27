import asyncio
import json
import re

import httpx

from app.schemas.language_models import ConnectionResult, ModelView


def failed(code: str, message: str, suggestion: str) -> ConnectionResult:
    return ConnectionResult(success=False, code=code, message=message, suggestion=suggestion)


def http_failure(status: int, body: bytes) -> ConnectionResult:
    # 仅根据状态和标准错误代码分类；绝不转发供应商错误正文。
    code = ""
    try:
        error = json.loads(body).get("error", {})
        if isinstance(error, dict):
            code = str(error.get("code", ""))
    except (ValueError, AttributeError):
        pass
    if status == 401 or code in {"invalid_api_key", "incorrect_api_key"}:
        return failed("invalid_key", "密钥验证失败", "请检查 API Key 是否正确、过期或已被撤销。")
    if code in {"model_not_found", "invalid_model", "model_not_available"}:
        return failed(
            "invalid_model", "模型标识无效或无权访问", "请核对模型标识及该密钥的模型权限。"
        )
    if status == 403:
        return failed("forbidden", "服务拒绝访问", "请检查密钥权限、账户状态及服务的访问限制。")
    if status == 404:
        return failed(
            "not_found",
            "未找到接口或模型，暂时无法确定原因",
            "请检查 Base URL 是否需要 /v1，并核对模型标识。",
        )
    if status == 429:
        return failed("rate_limited", "服务限流或额度不足", "请检查账户余额和调用限制，稍后重试。")
    if 300 <= status < 400:
        return failed("redirect", "服务地址发生重定向", "请直接填写最终 API Base URL 后重试。")
    if status >= 500:
        return failed("provider_error", "模型服务暂时异常", "请检查服务运行状态，稍后重试。")
    return failed(
        "request_rejected",
        "模型服务未接受请求，暂时无法确定原因",
        "请核对模型、温度和输出限制；服务需支持 Chat Completions 的 max_tokens 参数。",
    )


async def test_connection(
    config: ModelView, key: str, transport: httpx.AsyncBaseTransport | None = None
) -> ConnectionResult:
    payload = {
        "model": config.model_id,
        "messages": [{"role": "user", "content": "请用一句简短的话打个招呼。"}],
        "temperature": config.temperature,
        "max_tokens": min(config.max_output_tokens, 64),
        "stream": False,
    }
    try:
        async with (
            asyncio.timeout(20),
            httpx.AsyncClient(
                timeout=httpx.Timeout(15, connect=5),
                follow_redirects=False,
                transport=transport,
                trust_env=False,
            ) as client,
        ):
            async with client.stream(
                "POST",
                f"{config.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                json=payload,
            ) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 256_000:
                        return failed(
                            "invalid_response",
                            "服务返回内容过大",
                            "请确认地址指向兼容 Chat Completions 的接口。",
                        )
                if not response.is_success:
                    return http_failure(response.status_code, bytes(body))
                data = json.loads(body)
                reply = data["choices"][0]["message"]["content"]
                if not isinstance(reply, str) or not reply.strip():
                    raise ValueError
                # 防止供应商或回显服务把 Authorization 中的密钥带回页面。
                reply = reply.replace(key, "[密钥已隐藏]")
                reply = re.sub(r"(?i)Bearer\s+\S+|\bsk-[\w-]+", "[密钥已隐藏]", reply)
                return ConnectionResult(
                    success=True, code="connected", message="模型已连接", reply=reply.strip()[:280]
                )
    except (TimeoutError, httpx.TimeoutException):
        return failed("timeout", "请求超时", "请检查网络和服务负载，稍后重试。")
    except (httpx.ConnectError, httpx.NetworkError, httpx.ProxyError):
        return failed(
            "unreachable", "无法访问服务地址", "请检查域名、端口、证书和本地服务是否启动。"
        )
    except (
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        httpx.DecodingError,
        httpx.RemoteProtocolError,
    ):
        return failed(
            "invalid_response", "返回格式异常", "请确认服务返回 Chat Completions JSON 和文本回复。"
        )
    except httpx.HTTPError:
        return failed(
            "connection_error", "连接未完成，暂时无法确定原因", "请检查服务地址和网络后重试。"
        )
