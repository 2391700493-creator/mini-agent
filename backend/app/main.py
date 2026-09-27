from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.api.agents import router as agents_router
from app.api.automations import router as automations_router
from app.api.chat import router as chat_router
from app.api.evaluations import router as evaluations_router
from app.api.health import router as health_router
from app.api.language_models import router as models_router
from app.api.mcp import router as mcp_router
from app.api.memories import router as memories_router
from app.api.runs import router as runs_router
from app.api.skills import router as skills_router
from app.api.tools import router as tools_router
from app.api.workspace import router as workspace_router
from app.config import resolve_database_path
from app.db import make_engine
from app.schemas.agents import AgentSave, DeleteAgent
from app.schemas.language_models import ModelSave
from app.schemas.skills import SkillSave, SkillToggle
from app.schemas.tools import ToolResult
from app.services.agent_runtime import AgentRuntime
from app.services.agents import AgentStore
from app.services.automations import AutomationStore
from app.services.chat import ChatStore
from app.services.evaluations import EvaluationStore
from app.services.mcp import McpStore
from app.services.memories import MemoryStore
from app.services.runs import RunStore
from app.services.secrets import SecretStorageError, SecretStore
from app.services.skills import SkillStore
from app.services.tool_execution import ToolRuntime
from app.services.workspace import WorkspaceStore


def create_app(
    database_path: Path | None = None,
    *,
    key_path: Path | None = None,
    model_transport=None,
    tool_root: Path | None = None,
    default_timezone: str | None = None,
    skills_root: Path | None = None,
) -> FastAPI:
    engine = make_engine(database_path)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        _app.state.chat_store.recover()
        _app.state.evaluation_store.recover()
        _app.state.evaluation_store.seed_example()
        _app.state.automation_store.launch()
        try:
            yield
        finally:
            await _app.state.automation_store.close()
            await _app.state.evaluation_store.close()
            await _app.state.chat_store.close()
            engine.dispose()

    application = FastAPI(title="mini-agent", version="0.1.0", lifespan=lifespan)
    application.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    application.state.secret_store = SecretStore(resolve_database_path(database_path), key_path)
    application.state.model_transport = model_transport
    application.state.active_model_tests = set()
    application.state.tool_runtime = ToolRuntime(
        database_path, root=tool_root, timezone=default_timezone, key_path=key_path
    )
    application.state.skill_store = SkillStore(skills_root)
    application.state.mcp_store = McpStore(application.state.secret_store)
    application.state.memory_store = MemoryStore(application.state.session_factory)
    application.state.agent_store = AgentStore(
        application.state.skill_store, application.state.mcp_store, application.state.tool_runtime
    )
    application.state.agent_runtime = AgentRuntime(
        application.state.session_factory,
        application.state.secret_store,
        application.state.tool_runtime,
        application.state.skill_store,
        application.state.mcp_store,
        model_transport,
    )
    application.state.run_store = RunStore(application.state.session_factory)
    application.state.chat_store = ChatStore(
        application.state.session_factory,
        application.state.agent_runtime,
        application.state.run_store,
        model_transport,
    )
    application.state.evaluation_store = EvaluationStore(
        application.state.session_factory,
        application.state.agent_runtime,
        application.state.run_store,
        application.state.secret_store,
        model_transport,
    )
    application.state.workspace_store = WorkspaceStore(
        application.state.session_factory, application.state.tool_runtime
    )
    application.state.chat_store.workspace = application.state.workspace_store
    application.state.automation_store = AutomationStore(
        application.state.session_factory, application.state.chat_store
    )
    application.include_router(workspace_router)
    application.include_router(automations_router)
    application.include_router(chat_router)
    application.include_router(evaluations_router)
    application.include_router(runs_router)
    application.include_router(agents_router)
    application.include_router(mcp_router)
    application.include_router(memories_router)
    application.include_router(skills_router)
    application.include_router(tools_router)
    application.include_router(health_router)
    application.include_router(models_router)

    @application.middleware("http")
    async def no_model_cache(request: Request, call_next):
        if request.url.path.startswith(
            (
                "/api/workspace",
                "/api/automations",
                "/api/tools",
                "/api/skills",
                "/api/mcp",
                "/api/agents",
                "/api/chat",
                "/api/runs",
                "/api/evaluations",
            )
        ):
            origin = request.headers.get("origin")
            host = request.url.hostname
            loopback_hosts = {"127.0.0.1", "localhost", "::1"}
            local = host in loopback_hosts or (
                host == "testserver" and request.client.host == "testclient"
            )
            cross_site = request.headers.get("sec-fetch-site") == "cross-site"
            try:
                origin_host = urlsplit(origin).hostname if origin else None
            except ValueError:
                origin_host = "invalid"
            # Vite changeOrigin 会改写 Host；localhost 与 127.0.0.1 均为本地开发入口。
            valid_origin = (
                not origin
                or origin_host == host
                or (host in loopback_hosts and origin_host in loopback_hosts)
            )
            if not local or cross_site or not valid_origin:
                return JSONResponse(
                    status_code=403, content={"detail": "本地管理接口仅允许本地同源访问。"}
                )
            zip_upload = request.url.path == "/api/skills/import"
            if (
                not zip_upload
                and request.method in {"POST", "PATCH", "PUT"}
                and not request.headers.get("content-type", "").startswith("application/json")
            ):
                return JSONResponse(
                    status_code=415, content={"detail": "请使用 application/json 请求。"}
                )
            if not zip_upload and request.method in {"POST", "PATCH", "PUT"}:
                attachment_message = request.url.path.startswith(
                    "/api/chat/conversations/"
                ) and request.url.path.endswith("/messages")
                limit = 15 * 1024 * 1024 if attachment_message else 2 * 1024 * 1024
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > limit:
                        return JSONResponse(
                            status_code=413, content={"detail": "请求过大，请减少附件或消息长度。"}
                        )
                request._body = bytes(body)
        response = await call_next(request)
        if request.url.path.startswith(
            (
                "/api/models",
                "/api/workspace",
                "/api/automations",
                "/api/tools",
                "/api/skills",
                "/api/mcp",
                "/api/agents",
                "/api/chat",
                "/api/runs",
                "/api/evaluations",
            )
        ):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, error: RequestValidationError):
        if _request.url.path.startswith(("/api/workspace", "/api/automations")):
            return JSONResponse(
                status_code=422, content={"detail": "请检查名称、任务内容与时间设置。"}
            )
        if _request.url.path.startswith("/api/chat"):
            return JSONResponse(
                status_code=422, content={"detail": "消息或 Agent 选择无效，请检查输入后重试。"}
            )
        if _request.url.path.startswith("/api/tools"):
            if _request.url.path.endswith("/execute"):
                result = ToolResult(
                    tool_id=_request.path_params.get("tool_id", ""),
                    success=False,
                    code="invalid_arguments",
                    message="请求格式不正确，请传入 arguments 对象。",
                )
                return JSONResponse(status_code=422, content=result.model_dump())
            return JSONResponse(
                status_code=422, content={"detail": "仅允许修改 enabled，且值必须为布尔值。"}
            )
        if _request.url.path.startswith("/api/mcp"):
            return JSONResponse(
                status_code=422,
                content={
                    "detail": (
                        "配置格式不正确：请检查名称、命令、参数列表和环境变量；"
                        "环境变量需填实际值或保留原值。"
                    )
                },
            )
        # FastAPI 默认错误包含 input，可能回显密钥或整个请求体。
        fields = {}
        for item in error.errors():
            field = str(item["loc"][-1])
            allowed = (
                SkillSave.model_fields | SkillToggle.model_fields
                if _request.url.path.startswith("/api/skills")
                else ModelSave.model_fields
            )
            if _request.url.path.startswith("/api/agents"):
                allowed = AgentSave.model_fields | DeleteAgent.model_fields
                field = str(item["loc"][1]) if len(item["loc"]) > 1 else "form"
            if field not in allowed:
                field = "form"
            kind = item["type"]
            message = "填写格式不正确，请检查该字段。"
            if kind == "value_error":
                message = item["msg"].removeprefix("Value error, ")
            elif kind == "missing":
                message = "请填写此项。"
            elif field in {"context_length", "max_output_tokens"}:
                message = "请输入 1 至 2147483647 的正整数。"
            elif field == "max_rounds":
                message = "请输入 1 至 100 的正整数。"
            elif field == "temperature":
                message = "温度应为 0 至 2 的数字。"
            elif field.endswith("price"):
                message = "价格应为非负有限数字；未知时请留空。"
            fields[field] = message
        return JSONResponse(status_code=422, content={"detail": {"fields": fields}})

    @application.exception_handler(SecretStorageError)
    async def secret_error(_request: Request, _error: SecretStorageError):
        return JSONResponse(
            status_code=503, content={"detail": "无法保存本地密钥，请检查主密钥文件与目录权限。"}
        )

    @application.exception_handler(SQLAlchemyError)
    async def database_error(_request: Request, _error: SQLAlchemyError):
        return JSONResponse(
            status_code=503, content={"detail": "数据库暂不可用，请确认迁移已完成，稍后重试。"}
        )

    return application


app = create_app()
