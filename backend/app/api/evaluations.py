from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.evaluations import (
    CaseReviewSave,
    CaseSave,
    CaseView,
    DatasetDetail,
    DatasetSave,
    DatasetView,
    EvaluationOptions,
    TaskDetail,
    TaskSave,
    TaskView,
)

router = APIRouter(prefix="/api/evaluations", tags=["evaluations"])
Database = Annotated[Session, Depends(get_session)]


@router.get("/datasets", response_model=list[DatasetView])
def datasets(request: Request):
    return request.app.state.evaluation_store.datasets()


@router.post("/datasets", response_model=DatasetView, status_code=201)
def create_dataset(data: DatasetSave, request: Request):
    return request.app.state.evaluation_store.save_dataset(data)


@router.get("/datasets/{dataset_id}", response_model=DatasetDetail)
def dataset(dataset_id: str, request: Request):
    return request.app.state.evaluation_store.dataset(dataset_id)


@router.put("/datasets/{dataset_id}", response_model=DatasetView)
def save_dataset(dataset_id: str, data: DatasetSave, request: Request):
    return request.app.state.evaluation_store.save_dataset(data, dataset_id)


@router.delete("/datasets/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: str, request: Request):
    request.app.state.evaluation_store.delete_dataset(dataset_id)
    return Response(status_code=204)


@router.post("/datasets/{dataset_id}/cases", response_model=CaseView, status_code=201)
def create_case(dataset_id: str, data: CaseSave, request: Request):
    return request.app.state.evaluation_store.save_case(dataset_id, data)


@router.put("/datasets/{dataset_id}/cases/{case_id}", response_model=CaseView)
def save_case(dataset_id: str, case_id: str, data: CaseSave, request: Request):
    return request.app.state.evaluation_store.save_case(dataset_id, data, case_id)


@router.delete("/datasets/{dataset_id}/cases/{case_id}", status_code=204)
def delete_case(dataset_id: str, case_id: str, request: Request):
    request.app.state.evaluation_store.delete_case(dataset_id, case_id)
    return Response(status_code=204)


@router.get("/options", response_model=EvaluationOptions)
def options(request: Request):
    return request.app.state.evaluation_store.options()


@router.get("/tasks", response_model=list[TaskView])
def tasks(request: Request):
    return request.app.state.evaluation_store.tasks_view()


@router.post("/tasks", response_model=TaskView, status_code=201)
def create_task(data: TaskSave, request: Request):
    return request.app.state.evaluation_store.create_task(data)


@router.get("/tasks/{task_id}", response_model=TaskDetail)
def task(task_id: str, request: Request):
    return request.app.state.evaluation_store.task(task_id)


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: str, request: Request):
    request.app.state.evaluation_store.delete_task(task_id)
    return Response(status_code=204)


@router.patch("/tasks/{task_id}/cases/{case_id}/review", response_model=TaskDetail)
def review_case(task_id: str, case_id: str, data: CaseReviewSave, request: Request):
    return request.app.state.evaluation_store.review_case(task_id, case_id, data)


@router.post("/tasks/{task_id}/retry-failed", response_model=TaskDetail)
async def retry_failed(task_id: str, request: Request):
    return request.app.state.evaluation_store.retry_failed(task_id)


@router.post("/tasks/{task_id}/start", response_model=TaskDetail)
async def start(task_id: str, request: Request):
    return request.app.state.evaluation_store.start(task_id)


@router.post("/tasks/{task_id}/stop", response_model=TaskDetail)
async def stop(task_id: str, request: Request):
    return await request.app.state.evaluation_store.stop(task_id)
