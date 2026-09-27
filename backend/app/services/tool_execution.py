"""本地工具唯一执行入口，供 HTTP 和后续 Agent Loop 共同调用。"""

import copy
import errno
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, resolve_database_path
from app.repositories import tools as repository
from app.schemas.tools import ToolResult, ToolView, validate_timezone
from app.services import tool_shell
from app.services.tool_files import ToolFailure, execute_file
from app.services.tool_registry import REGISTRY


class ToolRuntime:
    def __init__(self, database_path=None, *, root=None, timezone=None, key_path=None):
        value = Path(
            root or os.getenv("MINI_AGENT_TOOL_ROOT", str(BACKEND_DIR.parent / "tool-workspace"))
        ).expanduser()
        self.root = (value if value.is_absolute() else BACKEND_DIR / value).resolve()
        self.timezone = timezone or os.getenv("MINI_AGENT_DEFAULT_TIMEZONE", "Asia/Shanghai")
        self.lock = threading.Lock()
        self.configuration_error = None
        protected = [
            BACKEND_DIR,
            BACKEND_DIR.parent / "frontend",
            BACKEND_DIR.parent / "docs",
            Path.home() / ".config",
            Path.home() / ".ssh",
            Path.home() / ".aws",
            Path.home() / ".codex",
            Path.home() / "Library",
            Path("/System"),
            Path("/usr"),
            Path("/bin"),
            Path("/sbin"),
            Path("/etc").resolve(),
            resolve_database_path(database_path),
        ]
        if key_path:
            protected.append(Path(key_path).resolve())
        if any(self.root.is_relative_to(p) or p.is_relative_to(self.root) for p in protected):
            self.configuration_error = (
                "授权目录必须是独立工作目录，不能包含应用代码、数据库、密钥或系统目录。"
            )

    def scoped(self, folder):
        from app.services.tool_files import open_directory, path_parts

        self.prepare_root()
        parts = path_parts(folder, directory=True)
        with open_directory(self.root, parts):
            pass
        scoped = copy.copy(self)
        scoped.root = self.root.joinpath(*parts)
        return scoped

    def prepare_root(self):
        if self.configuration_error:
            raise ToolFailure("configuration_error", self.configuration_error)
        if self.root.is_symlink() or self.root.resolve() != self.root:
            raise ToolFailure("path_denied", "授权目录不能被替换成符号链接。")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def view(self, tool_id: str, enabled: bool) -> ToolView:
        definition = REGISTRY[tool_id]
        problem = self.configuration_error if tool_id != "current_time" else None
        if tool_id == "current_time":
            try:
                validate_timezone(self.timezone)
            except ValueError:
                problem = "系统默认时区无效，请修正 MINI_AGENT_DEFAULT_TIMEZONE。"
        if tool_id == "shell" and not tool_shell.available():
            problem = "当前环境不支持 macOS sandbox-exec，Shell 暂不可执行。"
        return ToolView(
            id=tool_id,
            name=definition.name,
            description=definition.description,
            limitations=list(definition.limitations),
            input_schema=definition.schema.model_json_schema(),
            enabled=enabled,
            available=problem is None,
            unavailable_reason=problem,
            defaults={"timezone": self.timezone}
            if tool_id == "current_time"
            else {"root": str(self.root)},
        )


def execute_tool(
    session: Session,
    runtime: ToolRuntime,
    tool_id: str,
    arguments: object,
    *,
    cancel=None,
    authorize=None,
    scope=None,
) -> ToolResult:
    start = time.monotonic()

    def result(success, code, message, data=None):
        return ToolResult(
            tool_id=tool_id,
            success=success,
            code=code,
            message=message,
            data=data,
            duration_ms=round((time.monotonic() - start) * 1000),
        )

    if tool_id not in REGISTRY:
        return result(False, "tool_not_found", "工具不存在，请刷新工具列表。")
    if not runtime.lock.acquire(blocking=False):
        return result(False, "tool_busy", "另一个本地工具正在执行，请稍后重试。")
    try:
        if cancel is not None and cancel.is_set():
            return result(False, "cancelled", "工具调用已取消。")
        if authorize is not None and not authorize(session):
            return result(False, "permission_denied", "工具未绑定或运行权限已收窄。")
        if not repository.enabled(session, tool_id):
            return result(False, "tool_disabled", "工具已停用，请先在工具管理中启用。")
        args = REGISTRY[tool_id].schema.model_validate(arguments)
        session.rollback()  # 命令运行期间不持有数据库读事务。
        if tool_id == "current_time":
            timezone = args.timezone or validate_timezone(runtime.timezone)
            now = datetime.now(ZoneInfo(timezone))
            return result(
                True,
                "ok",
                "已获取当前时间。",
                {
                    "timezone": timezone,
                    "datetime": now.isoformat(timespec="seconds"),
                    "date": now.date().isoformat(),
                    "time": now.strftime("%H:%M:%S"),
                    "utc_offset": now.strftime("%z"),
                    "timestamp": int(now.timestamp()),
                },
            )
        if scope is not None:
            runtime = runtime.scoped(scope)
        runtime.prepare_root()
        if tool_id == "file":
            return result(
                True, "ok", "文件操作完成。", execute_file(runtime.root, args, cancel=cancel)
            )
        return result(*tool_shell.execute_shell(runtime.root, args, cancel=cancel))
    except ValidationError as error:
        # 仅返回固定字段名和错误类别，不能返回 input / ctx / 原始值。
        fields = sorted(
            {
                str(item["loc"][0])
                for item in error.errors()
                if item["loc"] and item["loc"][0] in REGISTRY[tool_id].schema.model_fields
            }
        )
        reasons = []
        for item in error.errors():
            if item["type"] == "value_error":
                reasons.append(item["msg"].removeprefix("Value error, "))
            elif item["type"] == "extra_forbidden":
                reasons.append("包含未定义的参数，请只填写参数说明中的字段。")
            elif item["type"] == "missing":
                reasons.append("缺少必填参数。")
            else:
                reasons.append("参数类型、可选值或范围不正确，请检查参数说明。")
        return result(
            False, "invalid_arguments", " ".join(dict.fromkeys(reasons)), {"fields": fields}
        )
    except ToolFailure as error:
        return result(False, error.code, error.message)
    except FileNotFoundError:
        return result(
            False, "file_not_found", "文件或父目录不存在，请检查路径；write 仅修改现有文件。"
        )
    except FileExistsError:
        return result(False, "file_exists", "文件已存在；如需替换内容，请使用 write。")
    except UnicodeError:
        return result(False, "invalid_encoding", "只支持 UTF-8 纯文本文件，请检查编码。")
    except OSError as error:
        if error.errno in {errno.ELOOP, errno.ENOTDIR, errno.EISDIR}:
            return result(
                False, "path_denied", "路径包含链接或类型不符；仅支持授权目录内的普通文件。"
            )
        return result(False, "io_error", "操作被系统拒绝，请检查目录权限、可用空间及沙箱限制。")
    except SQLAlchemyError:
        session.rollback()
        return result(False, "database_unavailable", "数据库暂不可用，请检查迁移并重试。")
    except ValueError:
        return result(False, "configuration_error", "系统默认时区配置无效，请使用 IANA 时区名称。")
    except Exception:
        # 不将异常正文或堆栈发往前端或写入日志；单次失败不影响后续请求。
        return result(False, "execution_failed", "工具执行失败，请检查运行环境后重试。")
    finally:
        runtime.lock.release()
