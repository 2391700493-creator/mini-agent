from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_session
from app.repositories import tools as repository
from app.schemas.tools import ToolCall, ToolResult, ToolToggle, ToolView
from app.services.tool_execution import execute_tool
from app.services.tool_registry import REGISTRY

router = APIRouter(prefix="/api/tools", tags=["tools"])
Database = Annotated[Session, Depends(get_session)]


def require_tool(tool_id):
    if tool_id not in REGISTRY:
        raise HTTPException(404, "工具不存在。")


@router.get("", response_model=list[ToolView])
def list_tools(request: Request, session: Database):
    states = repository.states(session)
    return [request.app.state.tool_runtime.view(key, states.get(key, False)) for key in REGISTRY]


@router.get("/{tool_id}", response_model=ToolView)
def get_tool(tool_id: str, request: Request, session: Database):
    require_tool(tool_id)
    return request.app.state.tool_runtime.view(tool_id, repository.enabled(session, tool_id))


@router.patch("/{tool_id}", response_model=ToolView)
def toggle_tool(tool_id: str, data: ToolToggle, request: Request, session: Database):
    require_tool(tool_id)
    runtime = request.app.state.tool_runtime
    if not runtime.lock.acquire(blocking=False):
        raise HTTPException(409, "本地工具正在执行，请等待完成后切换状态。")
    try:
        try:
            repository.set_enabled(session, tool_id, data.enabled)
        except LookupError:
            raise HTTPException(503, "工具状态未初始化，请执行数据库迁移。") from None
        return runtime.view(tool_id, data.enabled)
    finally:
        runtime.lock.release()


@router.delete("/{tool_id}")
def delete_tool(tool_id: str):
    require_tool(tool_id)
    raise HTTPException(403, "系统内置工具不能删除，只能启用或停用。")


@router.post("/{tool_id}/execute", response_model=ToolResult)
def run_tool(tool_id: str, data: ToolCall, request: Request, session: Database):
    return execute_tool(session, request.app.state.tool_runtime, tool_id, data.arguments)
