from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import McpSecret, McpServer, ModelSecret


def get_server(session: Session, server_id: str) -> McpServer:
    server = session.get(McpServer, server_id)
    if server is None:
        raise HTTPException(404, "MCP Server 已不存在，请刷新列表。")
    return server


def list_servers(session: Session) -> list[McpServer]:
    return list(session.scalars(select(McpServer).order_by(McpServer.name, McpServer.id)))


def has_secrets(session: Session) -> bool:
    return (
        session.scalar(select(McpSecret.server_id).limit(1)) is not None
        or session.scalar(select(ModelSecret.model_id).limit(1)) is not None
    )
