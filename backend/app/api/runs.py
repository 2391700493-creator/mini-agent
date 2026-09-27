from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query, Request, Response

from app.schemas.runs import RunDetail, RunEventPayloadView, RunPage

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("", response_model=RunPage)
async def listing(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Literal["running", "success", "partial", "failed", "cancelled"] | None = None,
    agent_id: str | None = Query(None, min_length=1, max_length=36),
    model_id: str | None = Query(None, min_length=1, max_length=36),
    source: Literal["chat", "evaluation"] | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
):
    return request.app.state.run_store.listing(
        page, page_size, status, agent_id, model_id, source, started_after, started_before
    )


@router.get("/{run_id}", response_model=RunDetail)
async def detail(run_id: str, request: Request):
    return request.app.state.run_store.detail(run_id)


@router.get("/{run_id}/events/{sequence}/payload", response_model=RunEventPayloadView)
async def payload(run_id: str, sequence: int, request: Request):
    return request.app.state.run_store.payload(run_id, sequence)


@router.delete("/{run_id}", status_code=204)
async def delete(run_id: str, request: Request):
    request.app.state.run_store.delete(run_id)
    return Response(status_code=204)
