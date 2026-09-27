from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db import get_session
from app.schemas.skills import SkillDetail, SkillList, SkillSave, SkillToggle
from app.services.skills import MAX_ZIP, SkillError, SkillStore

router = APIRouter(prefix="/api/skills", tags=["skills"])
Database = Annotated[Session, Depends(get_session)]


def operation(request: Request, session: Session, method: str, *args):
    store: SkillStore = request.app.state.skill_store
    with store.lock:
        try:
            return getattr(store, method)(session, *args)
        except SkillError as error:
            session.rollback()
            raise HTTPException(error.status, error.message) from None
        except OSError:
            session.rollback()
            raise HTTPException(
                503, "Skills 文件操作失败，请检查目录权限和磁盘空间后重试。"
            ) from None


@router.get("", response_model=SkillList)
def list_skills(request: Request, session: Database):
    return operation(request, session, "listing")


@router.post("/refresh", response_model=SkillList)
def refresh_skills(request: Request, session: Database):
    return operation(request, session, "listing")


@router.post("/import", response_model=SkillDetail, status_code=201)
async def import_skill(request: Request, session: Database):
    if request.headers.get("content-type", "").split(";")[0] != "application/zip":
        raise HTTPException(415, "请上传 ZIP 文件，Content-Type 须为 application/zip。")
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > MAX_ZIP:
            raise HTTPException(413, "ZIP 文件不能超过 5 MiB。")
    return await run_in_threadpool(operation, request, session, "import_zip", bytes(payload))


@router.get("/{skill_id}", response_model=SkillDetail)
def get_skill(skill_id: str, request: Request, session: Database):
    return operation(request, session, "get", skill_id)


@router.put("/{skill_id}", response_model=SkillDetail)
def save_skill(skill_id: str, data: SkillSave, request: Request, session: Database):
    return operation(request, session, "save", skill_id, data)


@router.patch("/{skill_id}", response_model=SkillDetail)
def toggle_skill(skill_id: str, data: SkillToggle, request: Request, session: Database):
    return operation(request, session, "toggle", skill_id, data.enabled)


@router.delete("/{skill_id}", status_code=204)
def delete_skill(skill_id: str, request: Request, session: Database):
    operation(request, session, "delete", skill_id)
    return Response(status_code=204)
