"""系统工具的唯一描述与输入 schema 来源；数据库不能修改"
+ "这些定义。"""

from dataclasses import dataclass

from pydantic import BaseModel

from app.schemas.tools import FileInput, ShellInput, TimeInput


@dataclass(frozen=True)
class Definition:
    name: str
    description: str
    schema: type[BaseModel]
    limitations: tuple[str, ...]


REGISTRY = {
    "current_time": Definition(
        "当前时间",
        (
            "查询指定时区的当前日期和时间，用于确认当地时间、日期及 UTC "
            + "偏移。用户未指定时区时使用系统默认时区。"
        ),
        TimeInput,
        (
            (
                "使用 IANA 时区名称，如 Asia/Shanghai、Ame"
                + "rica/New_York、Etc/UTC；禁止 CST 等歧义"
                + "缩写。"
            ),
            "返回调用当时的时间，不用于查询历史时间或设置系统时钟。",
        ),
    ),
    "shell": Definition(
        "Shell",
        (
            "在授权目录中执行命令，查看系统信息、搜索文件、运行已检查的本地 "
            + "Shell 脚本和 Shell 测试，返回标准输出、标准错误及退"
            + "出码。"
        ),
        ShellInput,
        (
            (
                ("仅支持 macOS sandbox-exec；沙箱不可用时拒绝执" + "行。使用 /bin/sh ")
                + "和系统命令白名单，未开放 Python、Node、软件安装与任意可执行文件。"
            ),
            (
                "只允许访问授权目录和必要的系统运行库；禁止联网、读取外部数据、密"
                + "钥、隐藏文件和数据库。不要将敏感内容放入授权目录。"
            ),
            (
                "禁止递归删除系统目录、格式化磁盘、修改关键权限、关闭安全防护、外"
                + "传密钥和下载后直接执行脚本；系统管理及网络命令不在执行白名单内。"
            ),
            (
                "最长 30 秒，输出合计最多 64 KiB；限制进程数、打开文件"
                + "数和单文件大小。超限中止，已完成的操作不会回滚。仅支持前台任务。"
            ),
            ("工作目录必须存在；授权目录不得含符号链接、硬链接、设备、管道，最" + "多 10000 项。"),
        ),
    ),
    "file": Definition(
        "文件读写",
        (
            "读取、创建和修改授权目录内的 UTF-8 文本文件，用于查看资料"
            + "、保存结果及更新内容。修改时提交完整文件内容。"
        ),
        FileInput,
        (
            (
                "路径相对于授权目录，如 notes/todo.txt；父目录必须"
                + "存在，不自动创建。禁止绝对路径、..、符号链接和硬链接。"
            ),
            (
                "read 只读取现有文件；create 遇到已有文件时报错；wr"
                + "ite 完整替换已有文件，文件不存在时报错。空字符串可创建或替换"
                + "为空文件。"
            ),
            (
                "只支持 UTF-8 纯文本，单文件最多 1 MiB；禁止隐藏文件"
                + "、密钥、数据库、设备和管道。请勿将敏感内容放入授权目录。"
            ),
        ),
    ),
}
