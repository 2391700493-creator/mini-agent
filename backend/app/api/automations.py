from fastapi import APIRouter, Request, Response

from app.schemas.automations import AutomationSave, AutomationToggle, AutomationView

router = APIRouter(prefix="/api/automations", tags=["automations"])


@router.get("", response_model=list[AutomationView])
async def listing(request: Request):
    return request.app.state.automation_store.listing()


@router.post("", response_model=AutomationView, status_code=201)
async def create(data: AutomationSave, request: Request):
    return request.app.state.automation_store.save(data)


@router.put("/{task_id}", response_model=AutomationView)
async def save(task_id: str, data: AutomationSave, request: Request):
    return request.app.state.automation_store.save(data, task_id)


@router.patch("/{task_id}", response_model=AutomationView)
async def toggle(task_id: str, data: AutomationToggle, request: Request):
    return request.app.state.automation_store.toggle(task_id, data.enabled)


@router.delete("/{task_id}", status_code=204)
async def delete(task_id: str, request: Request):
    request.app.state.automation_store.delete(task_id)
    return Response(status_code=204)


@router.post("/{task_id}/run", response_model=AutomationView)
async def run(task_id: str, request: Request):
    return request.app.state.automation_store.start(task_id)


@router.post("/{task_id}/stop", response_model=AutomationView)
async def stop(task_id: str, request: Request):
    return await request.app.state.automation_store.stop(task_id)
