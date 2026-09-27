from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import make_engine
from app.main import create_app
from app.models import AppMetadata


def test_health_reads_initialized_database(client: TestClient):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected", "project": "mini-agent"}


def test_unmigrated_database_returns_503(database_path: Path):
    with TestClient(create_app(database_path)) as client:
        response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"
    assert str(database_path) not in response.text


def test_missing_metadata_is_not_reported_as_healthy(migrated_database: Path):
    engine = make_engine(migrated_database)
    with Session(engine) as session:
        session.delete(session.get(AppMetadata, "project_name"))
        session.commit()
    engine.dispose()
    with TestClient(create_app(migrated_database)) as client:
        assert client.get("/api/health").status_code == 503


def test_unknown_api_does_not_return_html(client: TestClient):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
