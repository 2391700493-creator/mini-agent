from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.repositories.agents import listing
from app.schemas.agents import AgentDetail, AgentOptions, AgentSave, AgentSummary, DeleteAgent

router = APIRouter(prefix="/api/agents", tags=["agents"])
Database = Annotated[Session, Depends(get_session)]


@router.get("", response_model=list[AgentSummary])
def list_agents(session: Database):
    return listing(session)


@router.get("/options", response_model=AgentOptions)
def options(request: Request, session: Database):
    store = request.app.state.agent_store
    with store.capability_lock():
        return store.options(session)


@router.post("", response_model=AgentDetail, status_code=201)
def create(data: AgentSave, request: Request, session: Database):
    return request.app.state.agent_store.save(session, data)


@router.get("/{agent_id}", response_model=AgentDetail)
def get(agent_id: str, request: Request, session: Database):
    return request.app.state.agent_store.get(session, agent_id)


@router.put("/{agent_id}", response_model=AgentDetail)
def save(agent_id: str, data: AgentSave, request: Request, session: Database):
    return request.app.state.agent_store.save(session, data, agent_id)


@router.put("/{agent_id}/default", response_model=AgentSummary)
def set_default(agent_id: str, request: Request, session: Database):
    return request.app.state.agent_store.set_default(session, agent_id)


@router.delete("/{agent_id}", status_code=204)
def delete(agent_id: str, data: DeleteAgent, request: Request, session: Database):
    request.app.state.agent_store.delete(session, agent_id, data.replacement_id)
    return Response(status_code=204)
