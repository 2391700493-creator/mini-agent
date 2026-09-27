from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import ModelSecret
from app.repositories import language_models as repository
from app.schemas.language_models import ConnectionResult, DeleteModel, ModelSave, ModelView
from app.services.model_connection import failed, test_connection
from app.services.secrets import SecretStorageError

router = APIRouter(prefix="/api/models", tags=["models"])
Database = Annotated[Session, Depends(get_session)]


@router.get("", response_model=list[ModelView])
def list_models(session: Database):
    return repository.list_models(session)


@router.post("", response_model=ModelView, status_code=201)
def create_model(data: ModelSave, request: Request, session: Database):
    return repository.save_model(session, data, request.app.state.secret_store)


@router.get("/{model_id}", response_model=ModelView)
def get_model(model_id: str, session: Database):
    return repository.view(session, repository.get_model(session, model_id))


@router.put("/{model_id}", response_model=ModelView)
def update_model(model_id: str, data: ModelSave, request: Request, session: Database):
    return repository.save_model(session, data, request.app.state.secret_store, model_id)


@router.put("/{model_id}/default", response_model=ModelView)
def set_default(model_id: str, session: Database):
    return repository.set_default(session, model_id)


@router.delete("/{model_id}", status_code=204)
def delete_model(model_id: str, data: DeleteModel, session: Database):
    repository.delete_model(session, model_id, data.replacement_id)
    return Response(status_code=204)


@router.post("/{model_id}/test", response_model=ConnectionResult)
async def test_model(model_id: str, request: Request, session: Database):
    active = request.app.state.active_model_tests
    if model_id in active:
        raise HTTPException(409, "该模型正在测试，请等待结果。")
    active.add(model_id)
    try:
        config = repository.view(session, repository.get_model(session, model_id))
        credential = session.get(ModelSecret, model_id)
        if not credential:
            return failed("missing_key", "尚未配置密钥", "请编辑模型并填写 API Key。")
        try:
            key = request.app.state.secret_store.decrypt(credential.ciphertext)
        except SecretStorageError:
            return failed(
                "key_unavailable",
                "无法读取本地密钥",
                "请检查主密钥文件及其权限，恢复原文件后重试。",
            )
        session.rollback()  # 网络等待不占用数据库读事务。
        return await test_connection(config, key, request.app.state.model_transport)
    finally:
        active.discard(model_id)
