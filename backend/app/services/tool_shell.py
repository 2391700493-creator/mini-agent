"""macOS Seatbelt 执行器。无可用沙箱时拒绝执行，绝不回退。"""

import json
import os
import selectors
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

from app.schemas.tools import ShellInput
from app.services.tool_files import ToolFailure, open_directory, path_parts

OUTPUT_LIMIT = 64 * 1024
SANDBOX = Path("/usr/bin/sandbox-exec")
# 原生工具白名单限制系统管理、网络客户端、任意本机解释器及脱离进程组的程序。
BINARIES = (
    "/bin/sh",
    "/bin/bash",
    "/bin/cat",
    "/bin/echo",
    "/bin/date",
    "/bin/ls",
    "/bin/pwd",
    "/bin/mkdir",
    "/bin/cp",
    "/bin/sleep",
    "/bin/test",
    "/usr/bin/true",
    "/usr/bin/false",
    "/usr/bin/uname",
    "/usr/bin/find",
    "/usr/bin/grep",
    "/usr/bin/head",
    "/usr/bin/tail",
    "/usr/bin/wc",
    "/usr/bin/sort",
    "/usr/bin/uniq",
    "/usr/bin/cut",
    "/usr/bin/tr",
    "/usr/bin/sed",
    "/usr/bin/awk",
    "/usr/bin/printf",
    "/usr/bin/diff",
    "/usr/bin/basename",
    "/usr/bin/dirname",
    "/usr/bin/touch",
)


def available() -> bool:
    return sys.platform == "darwin" and os.access(SANDBOX, os.X_OK)


def profile(root: Path) -> str:
    binaries = " ".join(f"(literal {json.dumps(path)})" for path in BINARIES)
    return f"""(version 1)
(deny default)
(allow process-fork sysctl-read)
(allow process-exec {binaries})
(allow file-read-metadata)
(allow file-read* (literal "/") (subpath "/bin") (subpath "/usr/bin")
  (subpath "/usr/lib") (subpath "/usr/share") (subpath "/System/Library")
  (subpath "/System/Volumes/Preboot/Cryptexes")
  (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random"))
(allow file-read* file-write* (subpath {json.dumps(str(root))}))
(allow file-write-data (literal "/dev/null"))
(deny file-read-data file-write*
  (regex #"/\\.[^/]+(/|$)"
    #"\\.([pP][eE][mM]|[kK][eE][yY]|[pP]12|[pP][fF][xX]|[dD][bB])$"
    #"\\.[sS][qQ][lL][iI][tT][eE]3?$"
    #"/([iI][dD]_[rR][sS][aA]|[iI][dD]_[eE][dD]25519|[cC][rR][eE][dD][eE][nN][tT][iI][aA][lL][sS]|[sS][eE][cC][rR][eE][tT][sS])(\\.|/|$)"))
"""


def check_workspace(root: Path, cancel=None):
    # 预存硬链接可能让同一 inode 在授权目录内拥有另一个名称，必须拒绝。
    count = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            if cancel is not None and cancel.is_set():
                raise ToolFailure("cancelled", "Shell 调用已取消。")
            count += 1
            if count > 10000:
                raise ToolFailure("workspace_too_large", "授权目录超过 10000 项，请缩小工作范围。")
            info = (Path(directory) / name).lstat()
            if stat.S_ISLNK(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
                raise ToolFailure(
                    "path_denied", "Shell 授权目录中不能包含符号链接或硬链接，请移除链接后重试。"
                )
            if not stat.S_ISREG(info.st_mode) and not stat.S_ISDIR(info.st_mode):
                raise ToolFailure("path_denied", "Shell 授权目录中仅允许普通文件和目录。")


def execute_shell(root: Path, args: ShellInput, *, cancel=None) -> tuple[bool, str, str, dict]:
    if not available():
        raise ToolFailure(
            "sandbox_unavailable", "Shell 需要 macOS sandbox-exec 沙箱，当前环境不可用。"
        )
    parts = path_parts(args.cwd, directory=True)
    with open_directory(root, parts):
        pass
    check_workspace(root, cancel)
    # 在独立的启动进程设置硬资源上限；避免在多线程后端使用 preexec_fn。
    process_count = len(
        subprocess.run(
            ["/bin/ps", "-U", str(os.getuid()), "-o", "pid="],
            capture_output=True,
            check=True,
            timeout=2,
        ).stdout.splitlines()
    )
    launcher = """import os, resource, sys
resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
limit = int(sys.argv.pop(1))
hard = resource.getrlimit(resource.RLIMIT_NPROC)[1]
if hard != resource.RLIM_INFINITY:
    limit = min(limit, hard)
resource.setrlimit(resource.RLIMIT_NPROC, (limit, limit))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
os.execve(sys.argv[1], sys.argv[1:], dict(os.environ))
"""
    if cancel is not None and cancel.is_set():
        raise ToolFailure("cancelled", "Shell 调用已取消。")
    process = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-c",
            launcher,
            str(process_count + 32),
            str(SANDBOX),
            "-p",
            profile(root),
            "/bin/sh",
            "-c",
            args.command,
        ],
        cwd=root.joinpath(*parts),
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(root),
            "TMPDIR": str(root),
            "LC_ALL": "en_US.UTF-8",
        },
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        close_fds=True,
    )
    chunks = {"stdout": bytearray(), "stderr": bytearray()}
    code = "ok"
    deadline = time.monotonic() + args.timeout_seconds
    try:
        with selectors.DefaultSelector() as selector:
            for stream, label in ((process.stdout, "stdout"), (process.stderr, "stderr")):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, label)
            while selector.get_map() or process.poll() is None:
                if cancel is not None and cancel.is_set():
                    code = "cancelled"
                    break
                if time.monotonic() >= deadline:
                    code = "timeout"
                    break
                if sum(map(len, chunks.values())) >= OUTPUT_LIMIT:
                    code = "output_limit"
                    break
                for key, _ in selector.select(
                    timeout=min(0.05, max(0, deadline - time.monotonic()))
                ):
                    remaining = OUTPUT_LIMIT - sum(map(len, chunks.values()))
                    data = os.read(key.fileobj.fileno(), min(8192, max(1, remaining)))
                    if not data:
                        selector.unregister(key.fileobj)
                    else:
                        chunks[key.data].extend(data[:remaining])
    finally:
        # 正常退出也清理同组后台任务，避免请求结束后仍有写入。
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            # macOS 对已经不存在的进程组也可能返回 EPERM。
            if process.poll() is None:
                process.kill()
        process.wait(timeout=2)
        process.stdout.close()
        process.stderr.close()
    data = {key: value.decode("utf-8", errors="replace") for key, value in chunks.items()}
    data.update(exit_code=process.returncode, truncated=code == "output_limit")
    if code == "ok" and process.returncode != 0:
        code = "command_failed"
    messages = {
        "cancelled": "命令已取消，已清理进程组；部分操作可能已完成。",
        "ok": "命令执行完成。",
        "command_failed": "命令执行失败，请检查标准错误、命令参数及沙箱允许的操作。",
        "timeout": "命令超时，已终止进程组；部分操作可能已完成。",
        "output_limit": "输出达到 64 KiB，已终止进程组；请缩小输出范围。",
    }
    return code == "ok", code, messages[code], data
