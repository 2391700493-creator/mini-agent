"""项目分组与授权目录中的会话副本；SQLite 是会话事实来源。"""

import os
import stat
import threading
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update

from app.models import ChatMessage, Conversation, Project
from app.repositories.language_models import write_transaction
from app.services.tool_files import ToolFailure, open_directory, path_parts


def atomic_text(fd, name, body):
    """目录描述符内原子写入，拒绝已有符号链接与硬链接。"""
    try:
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("unsafe output")
    except FileNotFoundError:
        pass
    temporary = f".conversation-{uuid4().hex}.tmp"
    out = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=fd,
    )
    try:
        with os.fdopen(out, "wb") as target:
            target.write(body)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass


class WorkspaceStore:
    def __init__(self, factory, tools):
        self.factory, self.tools = factory, tools
        self.lock = threading.RLock()

    def validate_folder(self, folder):
        if folder is None:
            return
        try:
            self.tools.prepare_root()
            with open_directory(self.tools.root, path_parts(folder, directory=True)):
                pass
        except (OSError, ToolFailure):
            raise HTTPException(422, "文件夹不可用，请从已授权目录重新选择。") from None

    def folders(self, parent="."):
        self.validate_folder(parent)
        parts = path_parts(parent, directory=True)
        result = []
        with open_directory(self.tools.root, parts) as fd, os.scandir(fd) as entries:
            for entry in entries:
                if len(result) >= 200:
                    break
                try:
                    path_parts(entry.name)
                    if entry.is_dir(follow_symlinks=False):
                        result.append({"path": "/".join([*parts, entry.name]), "name": entry.name})
                except (ToolFailure, OSError):
                    continue
        return {
            "parent": parent,
            "root_name": self.tools.root.name,
            "items": sorted(result, key=lambda i: i["name"]),
        }

    def projects(self):
        with self.factory() as session:
            return [
                {"id": p.id, "name": p.name}
                for p in session.scalars(select(Project).order_by(Project.created_at))
            ]

    def save_project(self, name, project_id=None):
        with self.factory() as session, write_transaction(session):
            row = (
                session.get(Project, project_id)
                if project_id
                else Project(id=str(uuid4()), created_at=datetime.now(UTC))
            )
            if row is None:
                raise HTTPException(404, "项目不存在。")
            row.name = name
            session.add(row)
            session.flush()
            return {"id": row.id, "name": row.name}

    def delete_project(self, project_id):
        with self.factory() as session, write_transaction(session):
            row = session.get(Project, project_id)
            if row is None:
                raise HTTPException(404, "项目不存在。")
            session.execute(
                update(Conversation)
                .where(Conversation.project_id == project_id)
                .values(project_id=None)
            )
            session.delete(row)

    def archive(self, conversation_id):
        with self.lock:
            with self.factory() as session:
                row = session.get(Conversation, conversation_id)
                if row is None or row.folder is None:
                    return
                folder = row.folder
                title = row.title
                lines = [f"# {title}\n", f"会话标识：{row.id}\n"]
                outputs = []
                for message in session.scalars(
                    select(ChatMessage)
                    .where(ChatMessage.conversation_id == row.id)
                    .order_by(ChatMessage.sequence)
                ):
                    author = "你" if message.role == "user" else message.agent_name or "Agent"
                    lines.append(f"\n## {author}\n\n{message.content}\n")
                    if (
                        message.role == "assistant"
                        and message.status == "completed"
                        and message.content.strip()
                    ):
                        outputs.append((f"reply-{message.id}.md", message.content.encode("utf-8")))
                    for attachment in message.attachments:
                        lines.append(f"\n附件：{attachment.name}（原文件保存在应用中）\n")
                body = "\n".join(lines).encode("utf-8")
            error = None
            try:
                self.validate_folder(folder)
                if len(body) > 10 * 1024 * 1024 or any(
                    len(content) > 1024 * 1024 for _, content in outputs
                ):
                    raise ValueError("archive too large")
                with open_directory(self.tools.root, path_parts(folder, directory=True)) as fd:
                    atomic_text(fd, f"conversation-{conversation_id}.md", body)
                    for name, content in outputs:
                        atomic_text(fd, name, content)
            except (OSError, ValueError, HTTPException, ToolFailure):
                error = "会话已保存在应用中，文件夹中的记录或回复 MD 同步失败，请检查目录后重试。"
            with self.factory() as session, write_transaction(session):
                row = session.get(Conversation, conversation_id)
                if row:
                    row.archive_error = error
