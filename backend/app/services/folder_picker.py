"""系统文件夹选择器；只返回授权工作目录内的单个相对路径。"""

import os
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import HTTPException

_picker_lock = threading.Lock()
_SCRIPT = """ObjC.import('AppKit');
function run(argv) {
    const app = $.NSApplication.sharedApplication;
    app.setActivationPolicy($.NSApplicationActivationPolicyAccessory);
    app.activateIgnoringOtherApps(true);
    const panel = $.NSOpenPanel.openPanel;
    panel.canChooseFiles = false;
    panel.canChooseDirectories = true;
    panel.allowsMultipleSelection = false;
    panel.canCreateDirectories = false;
    panel.title = '选择工作文件夹';
    panel.message = '选择授权工作目录或其中的文件夹';
    panel.prompt = '选择';
    panel.directoryURL = $.NSURL.fileURLWithPath(argv[0]);
    return panel.runModal === $.NSModalResponseOK ? panel.URL.path.js : '';
}"""


def choose_folder(store):
    if sys.platform != "darwin":
        raise HTTPException(501, "当前系统暂不支持本地文件夹选择器。")
    if not _picker_lock.acquire(blocking=False):
        raise HTTPException(409, "文件夹选择器已打开。")
    try:
        store.validate_folder(".")
        root = store.tools.root.absolute()
        try:
            result = subprocess.run(
                ["/usr/bin/osascript", "-l", "JavaScript", "-e", _SCRIPT, str(root)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                timeout=120,
                check=False,
                env={"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"},
                close_fds=True,
            )
        except (OSError, subprocess.TimeoutExpired, UnicodeError):
            raise HTTPException(503, "未能打开文件夹选择器，请重试。") from None
        if result.returncode != 0:
            raise HTTPException(503, "未能打开文件夹选择器，请重试。")
        selected = result.stdout.removesuffix("\n")
        if not selected:
            return {"folder": None}
        if len(selected.encode("utf-8")) > 4096 or any(ord(char) < 32 for char in selected):
            raise HTTPException(422, "文件夹名称不可用，请重新选择。")
        try:
            # 不解析符号链接；沿用目录描述符校验，拒绝链接与越界。
            relative = Path(selected).relative_to(root)
            folder = relative.as_posix()
            if os.path.isabs(folder):
                raise ValueError
            store.validate_folder(folder)
        except ValueError:
            raise HTTPException(422, "请选择授权工作目录或其中的文件夹。") from None
        return {"folder": folder}
    finally:
        _picker_lock.release()
