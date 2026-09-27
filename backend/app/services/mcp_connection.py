"""有界 stdio 探测：仅初始化和发现工具，绝不发送 tools/call。

使用 SDK 的协议模型验证响应，自行管理管道以限制输出并禁止 SDK 记录原始响应。
"""

import json
import os
import select
import selectors
import signal
import subprocess
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from jsonschema import validators
from jsonschema.exceptions import SchemaError
from mcp import types
from mcp.client.stdio import get_default_environment
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
from pydantic import ValidationError

from app.config import BACKEND_DIR


@dataclass
class ProbeResult:
    success: bool
    code: str
    message: str
    diagnostic: str | None = None
    tools: list[dict] = field(default_factory=list)


class ProbeError(Exception):
    def __init__(self, code: str, diagnostic: str = ""):
        self.code = code
        self.diagnostic = diagnostic


MESSAGES = {
    "command_not_found": "启动命令不存在，请检查可执行文件路径或安装情况。",
    "start_failed": "程序启动失败，请检查文件权限和运行环境。",
    "exited": "程序提前退出或关闭连接，请检查启动参数和所需环境变量。",
    "timeout": "连接或读取工具超时，请检查程序能否正常启动后重试。",
    "incompatible": "协议版本或响应格式不兼容，请使用支持 stdio 的 MCP Server。",
    "server_error": "Server 主动返回错误，请检查其配置与使用说明。",
    "unknown": "发生未知错误，请参考诊断信息后重试。",
}


def redact(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, str):
        for secret in sorted(set(secrets), key=len, reverse=True):
            if secret:
                value = value.replace(secret, "[已隐藏]")
        return value
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {redact(key, secrets): redact(item, secrets) for key, item in value.items()}
    return value


def redact_tools(tools: list[dict], secrets: list[str]) -> list[dict]:
    # 保留返回 schema 的固定字段名，短环境变量值也不能破坏 Tool 的结构。
    return [
        {
            "name": redact(tool["name"], secrets),
            "description": redact(tool["description"], secrets),
            "input_schema": redact(tool["input_schema"], secrets),
        }
        for tool in tools
    ]


class StdioProbe:
    def __init__(self, process: subprocess.Popen, timeout: float, cancel=None):
        self.cancel = cancel
        self.process = process
        self.deadline = time.monotonic() + timeout
        self.buffer = bytearray()
        self.total = 0
        self.sequence = 0
        self.stage = "initialize"
        self.selector = selectors.DefaultSelector()
        self.selector.register(process.stdout, selectors.EVENT_READ)
        os.set_blocking(process.stdout.fileno(), False)
        os.set_blocking(process.stdin.fileno(), False)

    def send(self, body: dict):
        payload = memoryview((json.dumps({"jsonrpc": "2.0", **body}) + "\n").encode())
        while payload:
            if self.cancel is not None and self.cancel.is_set():
                raise ProbeError("cancelled")
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise ProbeError("timeout")
            if not select.select([], [self.process.stdin], [], min(remaining, 0.05))[1]:
                continue
            try:
                written = os.write(self.process.stdin.fileno(), payload)
                payload = payload[written:]
            except BlockingIOError:
                continue

    def read(self) -> dict:
        while True:
            if self.cancel is not None and self.cancel.is_set():
                raise ProbeError("cancelled")
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise ProbeError("timeout")
            if b"\n" in self.buffer:
                line, _, self.buffer = self.buffer.partition(b"\n")
                if len(line) > 1024 * 1024:
                    raise ProbeError("incompatible", "单条响应超过 1 MiB 限制")
                value = json.loads(line)
                # Reject ambiguous envelopes before SDK's union parser chooses a branch.
                if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
                    raise ProbeError("incompatible")
                if sum(key in value for key in ("method", "result", "error")) != 1:
                    raise ProbeError("incompatible")
                types.JSONRPCMessage.model_validate(value, strict=True)
                return value
            if len(self.buffer) > 1024 * 1024:
                raise ProbeError("incompatible", "单条响应超过 1 MiB 限制")
            if not self.selector.select(min(remaining, 0.05)):
                continue
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise ProbeError("exited")
            self.total += len(chunk)
            if self.total > 4 * 1024 * 1024:
                raise ProbeError("incompatible", "响应总量超过 4 MiB 限制")
            self.buffer.extend(chunk)

    def request(self, method: str, params: dict) -> dict:
        self.stage = method
        self.sequence += 1
        request_id = self.sequence
        self.send({"id": request_id, "method": method, "params": params})
        while True:
            response = self.read()
            if "method" in response:
                if "id" in response:
                    if response["method"] == "ping":
                        self.send({"id": response["id"], "result": {}})
                    else:
                        self.send(
                            {
                                "id": response["id"],
                                "error": {"code": -32601, "message": "Capability not supported"},
                            }
                        )
                continue
            if type(response.get("id")) is not int or response["id"] != request_id:
                raise ProbeError("incompatible", "响应 ID 与当前请求不匹配")
            if "error" in response:
                code = response["error"]["code"]
                raise ProbeError("server_error", f"JSON-RPC 错误码：{code}")
            return response["result"]

    def discover(self) -> list[dict]:
        initialized = types.InitializeResult.model_validate(
            self.request(
                "initialize",
                {
                    "protocolVersion": SUPPORTED_PROTOCOL_VERSIONS[-1],
                    "capabilities": {},
                    "clientInfo": {"name": "mini-agent", "version": "0.1.0"},
                },
            ),
            strict=True,
        )
        if initialized.protocolVersion not in SUPPORTED_PROTOCOL_VERSIONS:
            raise ProbeError("incompatible", "Server 返回了当前客户端不支持的协议版本")
        self.send({"method": "notifications/initialized"})
        if initialized.capabilities.tools is None:
            return []
        tools, cursors, names = [], set(), set()
        params = {}
        for _ in range(100):
            page = types.ListToolsResult.model_validate(
                self.request("tools/list", params), strict=True
            )
            for tool in page.tools:
                if not tool.name or tool.name in names or tool.inputSchema.get("type") != "object":
                    raise ProbeError("incompatible", "工具名称重复或参数 schema 无效")
                validators.validator_for(tool.inputSchema).check_schema(tool.inputSchema)
                names.add(tool.name)
                tools.append(
                    {
                        "name": tool.name,
                        "description": tool.description or "未提供用途说明",
                        "input_schema": tool.inputSchema,
                    }
                )
                if len(tools) > 1000:
                    raise ProbeError("incompatible", "工具数量超过 1000 项限制")
            if page.nextCursor is None:
                return tools
            if page.nextCursor in cursors or len(page.nextCursor) > 4096:
                raise ProbeError("incompatible", "工具分页游标重复或超过长度限制")
            cursors.add(page.nextCursor)
            params = {"cursor": page.nextCursor}
        raise ProbeError("incompatible", "工具分页超过 100 页限制")


def cleanup(process: subprocess.Popen):
    # 先关闭 stdin，让 Server 正常退出；再清理同一进程组的残留子进程。
    with suppress(OSError):
        process.stdin.close()
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=0.5)
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=0.5)
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()
    process.stdout.close()


def start_process(command: str, args: list[str], env: dict[str, str]):
    return subprocess.Popen(
        [command, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={**get_default_environment(), **env},
        cwd=BACKEND_DIR.parent,
        bufsize=0,
        shell=False,
        start_new_session=True,
        close_fds=True,
    )


class RuntimeConnection:
    """复用管理探测的有界协议、初始化与进程清理，增加 tools/call。"""

    def __init__(self, server, cancel):
        self.server = server
        self.closed = False
        self.process = start_process(
            server.command,
            server.args,
            {key: value.get_secret_value() for key, value in server.env.items()},
        )
        self.client = None
        try:
            self.client = StdioProbe(self.process, 20, cancel)
            self.tools = self.client.discover()
        except BaseException:
            self.close()
            raise

    def call(self, name, arguments):
        if self.closed:
            raise ProbeError("exited")
        self.client.deadline = time.monotonic() + 30
        self.client.total = len(self.client.buffer)
        try:
            return types.CallToolResult.model_validate(
                self.client.request("tools/call", {"name": name, "arguments": arguments}),
                strict=True,
            )
        except BaseException:
            # 超时或协议失败后立即清理，禁止遗留工具继续执行或复用失步的连接。
            self.close()
            raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.client:
            self.client.selector.close()
        cleanup(self.process)


def probe(command: str, args: list[str], env: dict[str, str], timeout: float = 20) -> ProbeResult:
    process = None
    client = None
    try:
        process = start_process(command, args, env)
        client = StdioProbe(process, timeout)
        tools = redact_tools(client.discover(), list(env.values()))
        return ProbeResult(
            True,
            "success",
            f"连接成功，发现 {len(tools)} 个工具" if tools else "连接成功，未发现工具",
            tools=tools,
        )
    except FileNotFoundError:
        code, detail = "command_not_found", "可执行文件或其解释器未找到"
    except (PermissionError, subprocess.SubprocessError):
        code, detail = "start_failed", "操作系统拒绝启动程序"
    except ProbeError as error:
        code, detail = error.code, error.diagnostic
    except (ValidationError, ValueError, UnicodeError, SchemaError, RecursionError):
        code, detail = "incompatible", "响应未通过 JSON-RPC / MCP schema 校验"
    except (BrokenPipeError, ConnectionResetError):
        code, detail = "exited", "标准输入输出连接已关闭"
    except OSError:
        code, detail = ("start_failed" if process is None else "unknown"), "系统 I/O 操作失败"
    except Exception:
        code, detail = "unknown", "未分类的客户端错误；原始错误正文已隐藏"
    finally:
        if client:
            client.selector.close()
        if process:
            cleanup(process)
    stage = client.stage if client else "启动"
    # 诊断只输出结构化事实，永不回传 stderr、异常文本、Server 错误正文。
    diagnostic = f"阶段：{stage}；类别：{code}"
    if code == "exited" and process is not None:
        diagnostic += f"；进程退出码：{process.returncode}"
    if detail:
        diagnostic += f"；{detail}"
    return ProbeResult(False, code, MESSAGES[code], diagnostic)
