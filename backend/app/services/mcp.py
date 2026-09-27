"""MCP 管理入口；同一配置测试期间禁止修改、删除及重复测试。"""

import json
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, SecretStr
from sqlalchemy.orm import Session

from app.models import McpSecret, McpServer
from app.repositories.agent_references import ensure_unreferenced
from app.repositories.language_models import write_transaction
from app.repositories.mcp import get_server, has_secrets, list_servers
from app.schemas.mcp import McpImportPreview, McpJsonImport, McpSave, McpView
from app.services.mcp_connection import probe, redact, redact_tools
from app.services.secrets import SecretStore


class AgentServer(BaseModel):
    id: str
    name: str
    command: str
    args: list[str]
    env: dict[str, SecretStr]


class McpStore:
    def __init__(self, secrets: SecretStore, timeout: float = 20):
        self.secrets = secrets
        self.timeout = timeout
        self.lock = RLock()
        self.active: set[str] = set()

    def environment(self, session: Session, server_id: str) -> dict[str, str]:
        secret = session.get(McpSecret, server_id)
        return json.loads(self.secrets.decrypt(secret.ciphertext)) if secret else {}

    def view(self, session: Session, server: McpServer) -> McpView:
        env = self.environment(session, server.id)
        public = {
            key: getattr(server, key)
            for key in (
                "id",
                "name",
                "description",
                "command",
                "args",
                "enabled",
                "status",
                "message",
                "diagnostic",
                "tested_at",
                "last_success_at",
            )
        }
        # Server 可能在工具说明中回显环境变量；所有公开文本再次脱敏。
        public.update(
            tools=server.tools or [],
            tool_count=None if server.tools is None else len(server.tools),
            testing=server.id in self.active,
            env={key: "••••••••" for key in env},
        )
        for key in ("name", "description", "command", "args", "message", "diagnostic"):
            public[key] = redact(public[key], list(env.values()))
        public["tools"] = redact_tools(public["tools"], list(env.values()))
        return McpView(**public)

    def listing(self, session: Session):
        return [self.view(session, server) for server in list_servers(session)]

    def get(self, session: Session, server_id: str):
        return self.view(session, get_server(session, server_id))

    def ensure_idle(self, server_id: str):
        if server_id in self.active:
            raise HTTPException(409, "该 Server 正在测试，请等待测试完成后再操作。")

    @staticmethod
    def imported_configuration(data: McpJsonImport) -> tuple[McpSave, McpImportPreview]:
        try:
            root = json.loads(data.configuration)
        except (TypeError, ValueError):
            raise HTTPException(422, "JSON 配置无法解析。") from None
        servers = root.get("mcpServers") if isinstance(root, dict) else None
        if not isinstance(servers, dict) or not servers:
            raise HTTPException(422, "需要包含至少一个 mcpServers 配置。")
        if data.server_name:
            selected = servers.get(data.server_name)
            if selected is None:
                raise HTTPException(422, "未找到指定的 MCP Server。")
            name = data.server_name
        elif len(servers) == 1:
            name, selected = next(iter(servers.items()))
        else:
            raise HTTPException(422, "配置含多个 MCP Server，请选择要导入的名称。")
        if not isinstance(name, str) or not isinstance(selected, dict):
            raise HTTPException(422, "MCP Server 配置格式无效。")
        payload = {
            "name": name,
            "description": str(selected.get("description") or ""),
            "command": selected.get("command"),
            "args": selected.get("args", []),
            "env": selected.get("env", {}),
        }
        try:
            saved = McpSave.model_validate(payload)
        except Exception:
            raise HTTPException(422, "MCP 配置字段无效；请检查命令、参数和环境变量。") from None
        return saved, McpImportPreview(
            name=saved.name,
            description=saved.description,
            command=saved.command,
            args=saved.args,
            env_keys=sorted(saved.env),
        )

    def import_preview(self, data: McpJsonImport):
        _saved, preview = self.imported_configuration(data)
        return preview

    def import_json(self, session: Session, data: McpJsonImport, server_id: str | None = None):
        saved, _preview = self.imported_configuration(data)
        return self.save(session, saved, server_id)

    def save(self, session: Session, data: McpSave, server_id: str | None = None):
        if server_id:
            self.ensure_idle(server_id)
            server = get_server(session, server_id)
            previous = self.environment(session, server_id)
        else:
            server = McpServer(id=str(uuid4()), enabled=False, status="untested", message="未测试")
            previous = {}
            session.add(server)
        environment = {}
        for key, value in data.env.items():
            if value is None:
                if key not in previous:
                    raise HTTPException(422, "新增环境变量必须填写实际值。")
                environment[key] = previous[key]
            else:
                environment[key] = value.get_secret_value()
        changed = server_id and (
            server.command != data.command or server.args != data.args or previous != environment
        )
        if changed:
            server.status = "stale"
            server.message = "配置已变更，待重新测试"
            server.diagnostic = None
        server.name, server.description = data.name, data.description
        server.command, server.args = data.command, data.args
        if environment != previous:
            # 在覆盖/删除之前检查整个数据库中的密文，避免主密钥丢失时生成新密钥。
            create_key = not has_secrets(session)
            ciphertext = self.secrets.encrypt(json.dumps(environment), create=create_key)
            session.flush()
            credential = session.get(McpSecret, server.id)
            if credential:
                credential.ciphertext = ciphertext
            else:
                session.add(McpSecret(server_id=server.id, ciphertext=ciphertext))
        session.flush()
        result = self.view(session, server)
        session.commit()
        return result

    def toggle(self, session: Session, server_id: str, enabled: bool):
        self.ensure_idle(server_id)
        server = get_server(session, server_id)
        server.enabled = enabled
        session.commit()
        return self.view(session, server)

    def delete(self, session: Session, server_id: str):
        self.ensure_idle(server_id)
        with write_transaction(session):
            server = get_server(session, server_id)
            ensure_unreferenced(session, "mcp", server_id)
            session.delete(server)

    def test(self, session: Session, server_id: str):
        with self.lock:
            self.ensure_idle(server_id)
            server = get_server(session, server_id)
            environment = self.environment(session, server_id)
            command, args = server.command, list(server.args)
            session.rollback()  # 测试进程等待期间不占用数据库事务。
            self.active.add(server_id)
        try:
            result = probe(command, args, environment, self.timeout)
            with self.lock:
                server = get_server(session, server_id)
                server.status = "success" if result.success else "error"
                server.message, server.diagnostic = result.message, result.diagnostic
                server.tested_at = datetime.now(UTC).isoformat()
                if result.success:
                    server.tools = result.tools
                    server.last_success_at = server.tested_at
                session.commit()
                self.active.discard(server_id)
                return self.view(session, server)
        finally:
            with self.lock:
                self.active.discard(server_id)

    def for_agent(self, session: Session, ids: set[str] | None = None) -> list[AgentServer]:
        """Agent 的唯一配置读取入口；只提供当前启用的 Server，不启动或执行工具。"""
        with self.lock:
            return [
                AgentServer(
                    id=server.id,
                    name=server.name,
                    command=server.command,
                    args=server.args,
                    env=self.environment(session, server.id),
                )
                for server in list_servers(session)
                if server.enabled and (ids is None or server.id in ids)
            ]
