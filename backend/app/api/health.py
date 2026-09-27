from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.health import HealthResponse
from app.services.health import check_health

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
def health(response: Response, session: Annotated[Session, Depends(get_session)]) -> HealthResponse:
    result = check_health(session)
    if result.status != "ok":
        response.status_code = 503
    return result
