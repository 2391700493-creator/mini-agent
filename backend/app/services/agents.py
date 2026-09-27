"""只管理 Agent 配置，不执行模型、工具、Skill 或 MCP。"""

from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent, AgentPrompt, LanguageModel, McpServer
from app.repositories import agents as repository
from app.repositories import tools as tool_repository
from app.repositories.language_models import write_transaction
from app.schemas.agents import AgentDetail, AgentOptions, AgentSave, Capability, ModelOption
from app.services.skills import SkillError
from app.services.tool_registry import REGISTRY


class AgentStore:
    def __init__(self, skills, mcp, runtime):
        self.skills, self.mcp, self.runtime = skills, mcp, runtime

    @contextmanager
    def capability_lock(self):
        # 固定锁顺序；资源管理只持有自己的锁，避免交叉死锁。
        with self.skills.lock, self.mcp.lock:
            if not self.runtime.lock.acquire(blocking=False):
                raise HTTPException(409, "本地工具正在执行，请稍后重试。")
            try:
                yield
            finally:
                self.runtime.lock.release()

    def options(self, session: Session) -> AgentOptions:
        try:
            skills = self.skills.listing(session)
        except SkillError as error:
            raise HTTPException(error.status, error.message) from None
        except OSError:
            raise HTTPException(503, "Skills 目录暂不可读，请检查权限后重试。") from None
        states = tool_repository.states(session)
        servers = self.mcp.listing(session)
        return AgentOptions(
            models=[
                ModelOption(
                    id=m.id,
                    name=m.display_name,
                    model_id=m.model_id,
                    is_default=m.is_default,
                    context_length=m.context_length,
                    max_output_tokens=m.max_output_tokens,
                )
                for m in session.scalars(
                    select(LanguageModel).order_by(
                        LanguageModel.is_default.desc(), LanguageModel.display_name
                    )
                )
            ],
            tools=[
                Capability(
                    id=key,
                    name=item.name,
                    description=item.description,
                    enabled=states.get(key, False),
                    unavailable_reason=None if states.get(key, False) else "已停用，不可用",
                )
                for key, item in REGISTRY.items()
            ],
            skills=[
                Capability(
                    id=item.id,
                    name=item.name,
                    description=item.description,
                    enabled=item.enabled,
                    unavailable_reason=None if item.enabled else "已停用，不可用",
                )
                for item in skills.items
            ],
            mcp_servers=[
                Capability(
                    id=item.id,
                    name=item.name,
                    description=item.description,
                    enabled=item.enabled,
                    unavailable_reason=None if item.enabled else "已停用，不可用",
                )
                for item in servers
            ],
            skill_issues=skills.issues,
        )

    def detail(self, session: Session, agent: Agent, options: AgentOptions) -> AgentDetail:
        current = repository.prompt(session, agent.id)
        groups = {}
        for kind in repository.BINDINGS:
            available = {item.id: item for item in getattr(options, kind)}
            groups[kind] = [
                available.get(item.resource_id)
                or Capability(
                    id=item.resource_id,
                    name=item.name,
                    description=item.description,
                    enabled=False,
                    unavailable_reason="文件缺失或无效，不可用",
                )
                for item in repository.bindings(session, agent.id, kind)
            ]
        return AgentDetail(
            **repository.summary(session, agent).model_dump(),
            system_prompt=current.content if current else "",
            prompt_version=current.version if current else 0,
            **groups,
        )

    def get(self, session: Session, agent_id: str):
        with self.capability_lock():
            options = self.options(session)
            return self.detail(session, repository.get(session, agent_id), options)

    def save(self, session: Session, data: AgentSave, agent_id: str | None = None):
        with self.capability_lock():
            # scan 会初始化新发现的 Skill 状态；必须在 Agent 写事务前完成。
            options = self.options(session)
            session.rollback()
            with write_transaction(session):
                if session.get(LanguageModel, data.model_id) is None:
                    raise HTTPException(
                        422, {"fields": {"model_id": "模型不存在，请先添加或重新选择模型。"}}
                    )
                if agent_id:
                    agent = repository.get(session, agent_id)
                    current = repository.prompt(session, agent.id)
                else:
                    first = session.scalar(select(Agent.id).limit(1)) is None
                    agent = Agent(id=str(uuid4()), is_default=first)
                    current = None
                # 只校验新增绑定；原来已保存的停用或失效绑定可以继续保留。
                additions = {}
                for kind, field in [
                    ("tools", "tool_ids"),
                    ("skills", "skill_ids"),
                    ("mcp_servers", "mcp_server_ids"),
                ]:
                    existing = (
                        {
                            item.resource_id: item
                            for item in repository.bindings(session, agent.id, kind)
                        }
                        if agent_id
                        else {}
                    )
                    chosen = set(getattr(data, field))
                    available = {item.id: item for item in getattr(options, kind)}
                    new = chosen - existing.keys()
                    if any(key not in available or not available[key].enabled for key in new):
                        raise HTTPException(
                            422,
                            {"fields": {field: "仅能新增当前启用且有效的能力，请刷新选项后重试。"}},
                        )
                    additions[kind] = (existing, chosen, available, new)
                for field in (
                    "name",
                    "description",
                    "model_id",
                    "max_rounds",
                    "max_runtime_seconds",
                    "max_tool_calls",
                    "max_total_tokens",
                    "auto_compress",
                    "compression_trigger_ratio",
                    "compression_keep_recent_turns",
                    "compression_summary_target_tokens",
                ):
                    setattr(agent, field, getattr(data, field))
                agent.updated_at = datetime.now(UTC)
                session.add(agent)
                session.flush()
                if current is None or current.content != data.system_prompt:
                    session.add(
                        AgentPrompt(
                            agent_id=agent.id,
                            version=1 if current is None else current.version + 1,
                            content=data.system_prompt,
                            created_at=agent.updated_at,
                        )
                    )
                for kind, (existing, chosen, available, new) in additions.items():
                    for key in existing.keys() - chosen:
                        session.delete(existing[key])
                    for key in new:
                        item = available[key]
                        values = {
                            "agent_id": agent.id,
                            "resource_id": key,
                            "name": item.name,
                            "description": item.description,
                        }
                        if kind == "mcp_servers":
                            server = session.get(McpServer, key)
                            # 尚未成功发现工具时不能伪造空白名单；运行时仍会按
                            # Server 当前启用状态和 Agent 绑定复核。首次成功发现后，
                            # 下一次保存会冻结实际工具清单。
                            values["allowed_tools"] = (
                                [tool["name"] for tool in server.tools]
                                if server and server.tools is not None
                                else None
                            )
                        session.add(repository.BINDINGS[kind](**values))
                    for key in chosen & existing.keys() & available.keys():
                        existing[key].name = available[key].name
                        existing[key].description = available[key].description
                session.flush()
                result = self.detail(session, agent, options)
            return result

    def set_default(self, session: Session, agent_id: str):
        with write_transaction(session):
            agent = repository.get(session, agent_id)
            if not agent.is_default:
                repository.switch_default(session, agent_id)
            result = repository.summary(session, agent)
        return result

    def delete(self, session: Session, agent_id: str, replacement_id: str | None):
        with self.capability_lock(), write_transaction(session):
            agent = repository.get(session, agent_id)
            if agent.is_default and session.scalar(
                select(Agent.id).where(Agent.id != agent_id).limit(1)
            ):
                if not replacement_id or replacement_id == agent_id:
                    raise HTTPException(409, "请先选择新的默认 Agent，再删除当前 Agent。")
                repository.get(session, replacement_id)
                repository.switch_default(session, replacement_id)
            session.delete(agent)
