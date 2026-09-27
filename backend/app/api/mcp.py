from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.mcp import (
    McpImportPreview,
    McpJsonImport,
    McpSave,
    McpToggle,
    McpView,
)

router = APIRouter(prefix="/api/mcp", tags=["mcp"])
Database = Annotated[Session, Depends(get_session)]


def operation(request: Request, session: Session, method: str, *args):
    store = request.app.state.mcp_store
    with store.lock:
        try:
            return getattr(store, method)(session, *args)
        except Exception:
            session.rollback()
            raise


@router.get("", response_model=list[McpView])
def listing(request: Request, session: Database):
    return operation(request, session, "listing")


@router.post("", response_model=McpView, status_code=201)
def create(data: McpSave, request: Request, session: Database):
    return operation(request, session, "save", data)


@router.post("/import/preview", response_model=McpImportPreview)
def import_preview(data: McpJsonImport, request: Request, session: Database):
    return operation(request, session, "import_preview", data)


@router.post("/import", response_model=McpView, status_code=201)
def import_json(data: McpJsonImport, request: Request, session: Database):
    return operation(request, session, "import_json", data)


@router.put("/{server_id}/import", response_model=McpView)
def update_from_json(server_id: str, data: McpJsonImport, request: Request, session: Database):
    return operation(request, session, "import_json", data, server_id)


@router.get("/{server_id}", response_model=McpView)
def get(server_id: str, request: Request, session: Database):
    return operation(request, session, "get", server_id)


@router.put("/{server_id}", response_model=McpView)
def save(server_id: str, data: McpSave, request: Request, session: Database):
    return operation(request, session, "save", data, server_id)


@router.patch("/{server_id}", response_model=McpView)
def toggle(server_id: str, data: McpToggle, request: Request, session: Database):
    return operation(request, session, "toggle", server_id, data.enabled)


@router.delete("/{server_id}", status_code=204)
def delete(server_id: str, request: Request, session: Database):
    operation(request, session, "delete", server_id)
    return Response(status_code=204)


@router.post("/{server_id}/test", response_model=McpView)
def test(server_id: str, request: Request, session: Database):
    return request.app.state.mcp_store.test(session, server_id)
