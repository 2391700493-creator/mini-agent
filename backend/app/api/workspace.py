from fastapi import APIRouter, Query, Request, Response

from app.schemas.workspace import FolderListing, FolderSelection, ProjectSave, ProjectView
from app.services.folder_picker import choose_folder

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


@router.get("/projects", response_model=list[ProjectView])
def projects(request: Request):
    return request.app.state.workspace_store.projects()


@router.post("/projects", response_model=ProjectView, status_code=201)
def create(data: ProjectSave, request: Request):
    return request.app.state.workspace_store.save_project(data.name)


@router.put("/projects/{project_id}", response_model=ProjectView)
def rename(project_id: str, data: ProjectSave, request: Request):
    return request.app.state.workspace_store.save_project(data.name, project_id)


@router.delete("/projects/{project_id}", status_code=204)
def delete(project_id: str, request: Request):
    request.app.state.workspace_store.delete_project(project_id)
    return Response(status_code=204)


@router.get("/folders", response_model=FolderListing)
def folders(request: Request, parent: str = Query(default=".", max_length=1024)):
    return request.app.state.workspace_store.folders(parent)


@router.post("/archive/{conversation_id}", status_code=204)
def archive(conversation_id: str, request: Request):
    request.app.state.chat_store.detail(conversation_id)
    request.app.state.workspace_store.archive(conversation_id)
    return Response(status_code=204)


@router.post("/folders/choose", response_model=FolderSelection)
def select_folder(request: Request):
    return choose_folder(request.app.state.workspace_store)
