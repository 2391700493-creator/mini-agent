"""只通过目录描述符访问授权文件，不跟随符号链接，不接受硬链接。"""

import os
import re
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path

from app.schemas.tools import FileInput

MAX_FILE_BYTES = 1024 * 1024
SENSITIVE = re.compile(
    r"(^\.|\.(pem|key|p12|pfx|db|sqlite|sqlite3)$|^(id_rsa|id_ed25519|credentials|secrets)(\.|$))",
    re.I,
)


class ToolFailure(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def path_parts(value: str, *, directory=False) -> list[str]:
    if directory and value == ".":
        return []
    parts = value.split("/")
    if any(
        not p or p in {".", ".."} or "\\" in p or "\x00" in p or SENSITIVE.search(p) for p in parts
    ):
        raise ToolFailure(
            "path_denied",
            "路径必须在授权目录内，使用相对路径；不允许隐藏文件、密钥、数据库或路径跳转。",
        )
    return parts


@contextmanager
def open_directory(root: Path, parts: list[str]):
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def regular_file(fd: int):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ToolFailure("path_denied", "仅支持普通文件，不允许符号链接、硬链接、设备或管道。")
    if info.st_size > MAX_FILE_BYTES:
        raise ToolFailure("file_too_large", "文件超过 1 MiB，请缩小文件后重试。")


def execute_file(root: Path, args: FileInput, *, cancel=None) -> dict:
    def check_cancel():
        if cancel is not None and cancel.is_set():
            raise ToolFailure("cancelled", "文件操作已取消；已完成的操作不会自动回滚。")

    check_cancel()
    parts = path_parts(args.path)
    with open_directory(root, parts[:-1]) as parent:
        name = parts[-1]
        if args.operation in {"read", "write"}:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(fd, "rb") as source:
                regular_file(source.fileno())
                if args.operation == "read":
                    content = source.read(MAX_FILE_BYTES + 1)
                    if len(content) > MAX_FILE_BYTES:
                        raise ToolFailure("file_too_large", "文件超过 1 MiB，请缩小文件后重试。")
                    check_cancel()
                    return {
                        "path": args.path,
                        "content": content.decode("utf-8"),
                        "bytes": len(content),
                    }
        check_cancel()
        content = args.content.encode("utf-8")
        temporary = f".mini-agent-{uuid.uuid4().hex}.tmp"
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent
        )
        try:
            with os.fdopen(fd, "wb") as target:
                target.write(content)
                target.flush()
                os.fsync(target.fileno())
            check_cancel()
            if args.operation == "create":
                os.link(
                    temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False
                )
            else:
                # 原子替换目录项，不打开目标写入，避免链接换位造成目录外写入。
                os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            return {"path": args.path, "operation": args.operation, "bytes": len(content)}
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
