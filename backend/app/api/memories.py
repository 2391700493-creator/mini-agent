from fastapi import APIRouter, Request, Response

from app.schemas.memories import MemorySave, MemoryView

router = APIRouter(prefix="/api/agents/{agent_id}/memories", tags=["memories"])


@router.get("", response_model=list[MemoryView])
def listing(agent_id: str, request: Request):
    return request.app.state.memory_store.listing(agent_id)


@router.post("", response_model=MemoryView, status_code=201)
def create(agent_id: str, data: MemorySave, request: Request):
    return request.app.state.memory_store.save(agent_id, data)


@router.put("/{memory_id}", response_model=MemoryView)
def save(agent_id: str, memory_id: str, data: MemorySave, request: Request):
    return request.app.state.memory_store.save(agent_id, data, memory_id)


@router.delete("/{memory_id}", status_code=204)
def delete(agent_id: str, memory_id: str, request: Request):
    request.app.state.memory_store.delete(agent_id, memory_id)
    return Response(status_code=204)
