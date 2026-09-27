from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.models import LanguageModel, ModelSecret
from app.repositories.agent_references import ensure_unreferenced
from app.repositories.mcp import has_secrets as database_has_secrets
from app.schemas.language_models import ModelSave, ModelView
from app.services.secrets import SecretStore


@contextmanager
def write_transaction(session: Session) -> Iterator[None]:
    # SQLite 在读之前取得写锁，使并发新增、切换和删除按顺序完成。
    try:
        session.execute(text("BEGIN IMMEDIATE"))
        yield
        session.commit()
    except Exception:
        session.rollback()
        raise


def get_model(session: Session, model_id: str) -> LanguageModel:
    model = session.get(LanguageModel, model_id)
    if model is None:
        raise HTTPException(404, "模型已不存在，请刷新列表。")
    return model


def view(session: Session, model: LanguageModel) -> ModelView:
    return ModelView(
        **{
            field: getattr(model, field)
            for field in ModelView.model_fields
            if field != "key_configured"
        },
        key_configured=session.get(ModelSecret, model.id) is not None,
    )


def list_models(session: Session) -> list[ModelView]:
    return [
        view(session, model)
        for model in session.scalars(
            select(LanguageModel).order_by(
                LanguageModel.is_default.desc(), LanguageModel.updated_at.desc(), LanguageModel.id
            )
        )
    ]


def save_model(
    session: Session, data: ModelSave, secrets: SecretStore, model_id: str | None = None
) -> ModelView:
    with write_transaction(session):
        if model_id:
            model = get_model(session, model_id)
        else:
            if data.api_key is None:
                raise HTTPException(422, {"fields": {"api_key": "请填写 API Key"}})
            first = session.scalar(select(LanguageModel.id).limit(1)) is None
            model = LanguageModel(id=str(uuid4()), is_default=first)
            session.add(model)
        for field, value in data.model_dump(exclude={"api_key"}).items():
            setattr(model, field, value)
        model.updated_at = datetime.now(UTC)
        session.flush()
        if data.api_key is not None:
            has_secrets = database_has_secrets(session)
            encrypted = secrets.encrypt(data.api_key.get_secret_value(), create=not has_secrets)
            credential = session.get(ModelSecret, model.id)
            if credential:
                credential.ciphertext = encrypted
            else:
                session.add(ModelSecret(model_id=model.id, ciphertext=encrypted))
        session.flush()
        result = view(session, model)
    return result


def switch_default(session: Session, model_id: str) -> None:
    now = datetime.now(UTC)
    session.execute(
        update(LanguageModel)
        .where(LanguageModel.is_default.is_(True))
        .values(is_default=False, updated_at=now)
    )
    session.execute(
        update(LanguageModel)
        .where(LanguageModel.id == model_id)
        .values(is_default=True, updated_at=now)
    )


def set_default(session: Session, model_id: str) -> ModelView:
    with write_transaction(session):
        model = get_model(session, model_id)
        if not model.is_default:
            switch_default(session, model_id)
        result = view(session, model)
    return result


def delete_model(session: Session, model_id: str, replacement_id: str | None) -> None:
    with write_transaction(session):
        model = get_model(session, model_id)
        ensure_unreferenced(session, "model", model_id)
        if model.is_default:
            other = session.scalar(select(LanguageModel.id).where(LanguageModel.id != model_id))
            if other:
                if not replacement_id or replacement_id == model_id:
                    raise HTTPException(409, "请先选择一个新的默认模型，再删除当前模型。")
                get_model(session, replacement_id)
                switch_default(session, replacement_id)
        # model_secrets 由外键 CASCADE 在同一事务清理。
        session.delete(model)
