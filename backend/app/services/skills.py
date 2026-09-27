"""以 SKILL.md 为内容源，所有访问通过不跟随符号链接的目录描述符完成。"""

import hashlib
import io
import os
import re
import shutil
import stat
import threading
import unicodedata
import zipfile
import zlib
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR
from app.repositories import skills as repository
from app.schemas.skills import ScanIssue, SkillContent, SkillDetail, SkillList, SkillSave

MAX_ZIP = 5 * 1024 * 1024
MAX_FILE = 1024 * 1024
MAX_TOTAL = 10 * 1024 * 1024
MAX_ENTRIES = 100
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class SkillError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message = message
        self.status = status


def identity(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def valid_id(value: str):
    if not re.fullmatch(r"[\w-]{1,100}", value) or value.startswith("_"):
        raise SkillError(
            "Skill 目录名须为 1–100 个字母、数字、中文、短横线或下划线，不能以下划线开头。"
        )


def parse(content: bytes) -> tuple[SkillContent, dict]:
    if len(content) > MAX_FILE:
        raise SkillError("SKILL.md 不能超过 1 MiB。")
    try:
        raw = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SkillError("SKILL.md 必须使用 UTF-8 编码。") from None
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise SkillError("SKILL.md 须以 --- 开始的 YAML 文件头声明 name 和 description。")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise SkillError("YAML 文件头缺少结束标记 ---。")
    header = "".join(lines[1:end])
    if len(header.encode("utf-8")) > 16 * 1024:
        raise SkillError("YAML 文件头不能超过 16 KiB。")
    try:
        # 禁止别名、锚点和重复字段，避免递归结构与有歧义的配置。
        if any(
            isinstance(token, (yaml.AliasToken, yaml.AnchorToken)) for token in yaml.scan(header)
        ):
            raise SkillError("YAML 文件头不支持锚点或别名。")
        node = yaml.compose(header, Loader=yaml.SafeLoader)
        if not isinstance(node, yaml.MappingNode):
            raise SkillError("YAML 文件头必须是包含 name 和 description 的键值对象。")
        keys = [key.value for key, _ in node.value]
        if len(keys) != len(set(keys)):
            raise SkillError("YAML 文件头不能包含重复字段。")
        metadata = yaml.safe_load(header)
        if not all(isinstance(key, str) for key in metadata):
            raise SkillError("YAML 文件头的字段名必须为文本。")
    except (yaml.YAMLError, RecursionError, ValueError, TypeError):
        raise SkillError("YAML 文件头格式无效，请检查缩进和字段。") from None
    try:
        result = SkillContent(
            name=metadata.get("name"),
            description=metadata.get("description"),
            instructions="".join(lines[end + 1 :]),
        )
    except ValidationError as error:
        labels = {
            "name": "名称（1–100 字）",
            "description": "用途说明（1–500 字）",
            "instructions": "详细指令",
        }
        field = str(error.errors()[0]["loc"][0])
        raise SkillError(f"{labels.get(field, field)}无效或为空，请填写有效文本。") from None
    return result, metadata


@contextmanager
def directory(name, *, parent=None):
    fd = os.open(name, DIR_FLAGS, dir_fd=parent)
    try:
        yield fd
    finally:
        os.close(fd)


class SkillStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else BACKEND_DIR.parent / "workspace" / "skills"
        if not self.root.is_absolute():
            self.root = BACKEND_DIR / self.root
        self.lock = threading.RLock()

    @contextmanager
    def open_root(self):
        fd = os.open("/", DIR_FLAGS)
        try:
            for part in self.root.parts[1:]:
                if part in {".", ".."}:
                    raise SkillError("Skills 目录配置无效。", 503)
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(part, DIR_FLAGS, dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd
        finally:
            os.close(fd)

    def read(self, root_fd: int, skill_id: str):
        valid_id(skill_id)
        try:
            with directory(skill_id, parent=root_fd) as folder:
                fd = os.open("SKILL.md", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
                with os.fdopen(fd, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise SkillError("SKILL.md 必须是普通文件，不能使用符号链接或硬链接。")
                    data = stream.read(MAX_FILE + 1)
            content, metadata = parse(data)
            return content, metadata, hashlib.sha256(data).hexdigest(), info.st_mtime
        except FileNotFoundError:
            raise SkillError("Skill 目录或 SKILL.md 不存在，请刷新列表。", 404) from None
        except OSError:
            raise SkillError(
                "无法读取 Skill，请检查权限；目录与 SKILL.md 不能是符号链接。"
            ) from None

    def scan(self, session: Session) -> tuple[list[SkillDetail], list[ScanIssue]]:
        found = {}
        issues = []
        with self.open_root() as root_fd:
            for name in sorted(os.listdir(root_fd)):
                if name.startswith("."):
                    continue
                try:
                    info = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode):
                        continue
                    found[name] = self.read(root_fd, name)
                except SkillError as error:
                    issues.append(ScanIssue(directory=name, message=error.message))
                except OSError:
                    issues.append(
                        ScanIssue(directory=name, message="目录暂不可读，请检查权限后刷新。")
                    )
        # 重名的全部排除，避免 Agent 选中同名但内容不同的说明。
        names: dict[str, list[str]] = {}
        for key, (content, *_) in found.items():
            names.setdefault(identity(content.name), []).append(key)
        duplicates = {key for group in names.values() if len(group) > 1 for key in group}
        for key in sorted(duplicates):
            issues.append(
                ScanIssue(
                    directory=key, message="名称与其他 Skill 重复，请在文件中修改名称后刷新。"
                )
            )
            del found[key]
        states = repository.ensure_states(session, list(found))
        items = []
        for key, (content, _, revision, modified) in found.items():
            state = states[key]
            changed = state.updated_at.replace(tzinfo=UTC)
            items.append(
                SkillDetail(
                    id=key,
                    **content.model_dump(),
                    revision=revision,
                    enabled=state.enabled,
                    updated_at=max(datetime.fromtimestamp(modified, UTC), changed),
                )
            )
        return sorted(items, key=lambda item: item.updated_at, reverse=True), issues

    def listing(self, session: Session) -> SkillList:
        items, issues = self.scan(session)
        return SkillList(items=items, issues=issues)

    def get(self, session: Session, skill_id: str) -> SkillDetail:
        valid_id(skill_id)
        items, issues = self.scan(session)
        for item in items:
            if item.id == skill_id:
                return item
        for issue in issues:
            if issue.directory == skill_id:
                raise SkillError(issue.message)
        raise SkillError("Skill 不存在，请刷新列表。", 404)

    def for_agent(self, session: Session) -> list[SkillDetail]:
        """Agent 的统一读取入口：只返回当前有效且启用的任务说明，不执行附件。"""
        with self.lock:
            items, _ = self.scan(session)
            return [item for item in items if item.enabled]

    def check_name(self, session: Session, name: str, exclude: str | None = None):
        # 包括扫描时因重名而被排除的文件。
        with self.open_root() as root_fd:
            for key in os.listdir(root_fd):
                if key == exclude or key.startswith("."):
                    continue
                try:
                    content, *_ = self.read(root_fd, key)
                except SkillError:
                    continue
                if identity(content.name) == identity(name):
                    raise SkillError(
                        "同名 Skill 已存在，请修改名称后重试；已有内容不会被覆盖。", 409
                    )

    def save(self, session: Session, skill_id: str, data: SkillSave) -> SkillDetail:
        self.get(session, skill_id)
        self.check_name(session, data.name, exclude=skill_id)
        with self.open_root() as root_fd, directory(skill_id, parent=root_fd) as folder:
            _, metadata, revision, _ = self.read(root_fd, skill_id)
            if revision != data.revision:
                raise SkillError("文件已在其他地方修改，请重新加载后再编辑。", 409)
            metadata.update(name=data.name, description=data.description)
            raw = (
                "---\n"
                + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
                + "---\n"
                + data.instructions
            ).encode("utf-8")
            parse(raw)
            temporary = f".save-{uuid4().hex}"
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=folder)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                # 检查写入期间的手动修改，尽量避免覆盖外部编辑。
                if self.read(root_fd, skill_id)[2] != revision:
                    raise SkillError("文件已在其他地方修改，请重新加载后再编辑。", 409)
                os.replace(temporary, "SKILL.md", src_dir_fd=folder, dst_dir_fd=folder)
            finally:
                try:
                    os.unlink(temporary, dir_fd=folder)
                except FileNotFoundError:
                    pass
        return self.get(session, skill_id)

    def toggle(self, session: Session, skill_id: str, enabled: bool) -> SkillDetail:
        self.get(session, skill_id)
        repository.set_enabled(session, skill_id, enabled)
        return self.get(session, skill_id)

    def delete(self, session: Session, skill_id: str):
        from app.repositories.agent_references import ensure_unreferenced

        valid_id(skill_id)
        ensure_unreferenced(session, "skill", skill_id)
        with self.open_root() as root_fd:
            try:
                with directory(skill_id, parent=root_fd):
                    pass
            except FileNotFoundError:
                raise SkillError("Skill 不存在，请刷新列表。", 404) from None
            # rmtree 的 fd 版本不会跟随目录内的符号链接。
            shutil.rmtree(skill_id, dir_fd=root_fd)
        repository.delete(session, skill_id)

    def import_zip(self, session: Session, payload: bytes) -> SkillDetail:
        if len(payload) > MAX_ZIP:
            raise SkillError("ZIP 文件不能超过 5 MiB。", 413)
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                files = self.unpack(archive)
        except (
            zipfile.BadZipFile,
            RuntimeError,
            NotImplementedError,
            EOFError,
            OSError,
            zlib.error,
        ):
            raise SkillError("ZIP 文件损坏、已加密或使用了不支持的压缩格式。") from None
        roots = [path for path in files if path == "SKILL.md" or path.endswith("/SKILL.md")]
        if len(roots) != 1 or len(roots[0].split("/")) > 2:
            raise SkillError("ZIP 须包含一个 Skill：SKILL.md 位于 ZIP 根目录或唯一的一级目录内。")
        entry = roots[0]
        content, _ = parse(files[entry])
        if "/" in entry:
            skill_id = entry.split("/")[0]
            if any(not path.startswith(skill_id + "/") for path in files):
                raise SkillError("ZIP 中的所有文件必须位于同一个 Skill 目录。")
            files = {path[len(skill_id) + 1 :]: data for path, data in files.items()}
        else:
            skill_id = re.sub(r"[^\w-]+", "-", content.name).strip("-_")[:100]
        valid_id(skill_id)
        self.check_name(session, content.name)
        with self.open_root() as root_fd:
            if any(identity(name) == identity(skill_id) for name in os.listdir(root_fd)):
                raise SkillError("同名 Skill 目录已存在，不能覆盖；请修改 ZIP 中的目录名。", 409)
            try:
                # 排他创建目标目录，不使用可能覆盖空目录的 rename/extractall。
                os.mkdir(skill_id, mode=0o700, dir_fd=root_fd)
            except FileExistsError:
                raise SkillError("同名 Skill 目录已存在，不能覆盖。", 409) from None
            try:
                with directory(skill_id, parent=root_fd) as folder:
                    # 最后写 SKILL.md，扫描不会看到未完成导入的有效 Skill。
                    for path in sorted(files, key=lambda path: path == "SKILL.md"):
                        self.write_import_file(folder, path, files[path])
                return self.get(session, skill_id)
            except Exception:
                session.rollback()
                shutil.rmtree(skill_id, dir_fd=root_fd)
                raise

    @staticmethod
    def unpack(archive: zipfile.ZipFile) -> dict[str, bytes]:
        entries = archive.infolist()
        if len(entries) > MAX_ENTRIES:
            raise SkillError("ZIP 最多包含 100 个文件或目录。")
        files = {}
        seen = set()
        total = 0
        for info in entries:
            path = info.filename.rstrip("/")
            parts = path.split("/")
            if (
                not path
                or "\\" in path
                or ":" in path
                or "\x00" in info.orig_filename
                or len(path) > 500
                or len(parts) > 12
                or any(part in {"", ".", ".."} or part.startswith(".") for part in parts)
            ):
                raise SkillError("ZIP 含不安全路径：禁止绝对路径、上级目录、隐藏路径或反斜杠。")
            key = identity(path)
            if key in seen:
                raise SkillError("ZIP 含重复或大小写冲突的文件路径。")
            seen.add(key)
            mode = info.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if kind not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise SkillError("ZIP 不允许符号链接或特殊文件。")
            if info.flag_bits & 1:
                raise SkillError("不支持加密 ZIP，请先解密。")
            if info.is_dir():
                continue
            total += info.file_size
            if info.file_size > MAX_FILE or total > MAX_TOTAL:
                raise SkillError("ZIP 解压后每个文件最多 1 MiB，总计最多 10 MiB。", 413)
            with archive.open(info) as stream:
                data = stream.read(MAX_FILE + 1)
            if len(data) > MAX_FILE or len(data) != info.file_size:
                raise SkillError("ZIP 文件大小校验失败。", 413)
            files[path] = data
        # 在写磁盘前验证文件与目录冲突，包含大小写折叠后的隐式目录。
        file_keys = {identity(path) for path in files}
        prefixes = {}
        for path in seen:
            parts = path.split("/")
            if any("/".join(parts[:i]) in file_keys for i in range(1, len(parts))):
                raise SkillError("ZIP 含文件与目录路径冲突。")
        for path in files:
            parts = path.split("/")
            for i in range(1, len(parts) + 1):
                prefix = "/".join(parts[:i])
                normalized = identity(prefix)
                if normalized in prefixes and prefixes[normalized] != prefix:
                    raise SkillError("ZIP 含大小写或 Unicode 冲突的目录路径。")
                prefixes[normalized] = prefix
        return files

    @staticmethod
    def write_import_file(folder: int, path: str, data: bytes):
        fd = os.dup(folder)
        try:
            parts = path.split("/")
            for part in parts[:-1]:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(part, DIR_FLAGS, dir_fd=fd)
                os.close(fd)
                fd = child
            output = os.open(
                parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
            )
            with os.fdopen(output, "wb") as stream:
                stream.write(data)
        finally:
            os.close(fd)
