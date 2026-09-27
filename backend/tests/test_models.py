import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.main import create_app
from app.models import ModelSecret
from app.repositories.language_models import delete_model, save_model, set_default
from app.schemas.language_models import ModelSave
from app.services.secrets import SecretStorageError

KEY = "test-only-key-do-not-use"
DATA = {
    "display_name": "测试模型",
    "model_id": "test-model",
    "base_url": "https://example.com/v1/",
    "api_key": KEY,
    "context_length": 8192,
    "max_output_tokens": 512,
    "temperature": 1,
    "input_price": None,
    "output_price": 0,
    "cached_input_price": 0.125,
}


def add(client, **updates):
    response = client.post("/api/models", json=DATA | updates)
    assert response.status_code == 201, response.text
    return response.json()


def test_crud_secrets_and_restart(client, migrated_database: Path):
    model = add(client)
    assert model["is_default"] and model["key_configured"]
    assert model["input_price"] is None and model["output_price"] == 0
    assert model["base_url"] == "https://example.com/v1"
    assert model["updated_at"].endswith("Z")
    detail = client.get(f"/api/models/{model['id']}")
    assert detail.json() == model
    assert detail.headers["cache-control"] == "no-store"
    for response in [detail, client.get("/api/models")]:
        assert KEY not in response.text and "ciphertext" not in response.text
        assert "api_key" not in response.text
    with client.app.state.session_factory() as session:
        ciphertext = session.get(ModelSecret, model["id"]).ciphertext
        assert KEY not in ciphertext
        assert client.app.state.secret_store.decrypt(ciphertext) == KEY
    key_path = client.app.state.secret_store.path
    assert key_path.stat().st_mode & 0o777 == 0o600
    for key_value in [None, "", "   "]:
        response = client.put(
            f"/api/models/{model['id']}",
            json=DATA
            | {
                "api_key": key_value,
                "display_name": "改名",
            },
        )
        assert response.status_code == 200 and response.json()["key_configured"]
        with client.app.state.session_factory() as session:
            assert session.get(ModelSecret, model["id"]).ciphertext == ciphertext
    response = client.put(f"/api/models/{model['id']}", json=DATA | {"api_key": "new-secret"})
    assert "new-secret" not in response.text
    with TestClient(create_app(migrated_database, key_path=key_path)) as restarted:
        assert restarted.get("/api/models").json()[0]["key_configured"]
        with restarted.app.state.session_factory() as session:
            assert (
                restarted.app.state.secret_store.decrypt(
                    session.get(ModelSecret, model["id"]).ciphertext
                )
                == "new-secret"
            )
    assert KEY.encode() not in migrated_database.read_bytes()


def test_defaults_delete_and_atomic_secret_cleanup(client):
    a, b, c = add(client), add(client), add(client)
    assert not b["is_default"] and not c["is_default"]
    assert client.request("DELETE", f"/api/models/{a['id']}", json={}).status_code == 409
    assert (
        client.request(
            "DELETE",
            f"/api/models/{a['id']}",
            json={
                "replacement_id": a["id"],
            },
        ).status_code
        == 409
    )
    assert (
        client.request(
            "DELETE",
            f"/api/models/{a['id']}",
            json={
                "replacement_id": "missing",
            },
        ).status_code
        == 404
    )
    assert client.put("/api/models/missing/default").status_code == 404
    assert client.get("/api/models").json()[0]["id"] == a["id"]
    switched = client.put(f"/api/models/{b['id']}/default")
    assert switched.status_code == 200 and switched.json()["is_default"]
    assert sum(m["is_default"] for m in client.get("/api/models").json()) == 1
    assert client.request("DELETE", f"/api/models/{a['id']}", json={}).status_code == 204
    assert (
        client.request(
            "DELETE",
            f"/api/models/{b['id']}",
            json={
                "replacement_id": c["id"],
            },
        ).status_code
        == 204
    )
    assert client.get("/api/models").json()[0]["is_default"]
    with client.app.state.session_factory() as session:
        assert list(session.scalars(select(ModelSecret.model_id))) == [c["id"]]
    assert client.request("DELETE", f"/api/models/{c['id']}", json={}).status_code == 204
    assert client.get("/api/models").json() == []
    with client.app.state.session_factory() as session:
        assert not list(session.scalars(select(ModelSecret)))
    assert add(client)["is_default"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("display_name", ""),
        ("model_id", " "),
        ("display_name", "x" * 101),
        ("api_key", None),
        ("api_key", "bad\nkey"),
        ("api_key", "中文"),
        ("context_length", 0),
        ("context_length", 2.3),
        ("context_length", True),
        ("context_length", 2147483648),
        ("max_output_tokens", -1),
        ("max_output_tokens", 9000),
        ("temperature", -0.1),
        ("temperature", 2.1),
        ("temperature", "NaN"),
        ("input_price", -1),
        ("output_price", "Infinity"),
        ("cached_input_price", -0.01),
        ("base_url", "example.com"),
        ("base_url", "ftp://example.com"),
        ("base_url", "http://"),
        ("base_url", "https://user:password@example.com"),
        ("base_url", "https://example.com/v1/chat/completions/"),
        ("base_url", "https://example.com?key=private"),
        ("base_url", "https://example.com#fragment"),
        ("base_url", "http://example.com:bad"),
    ],
)
def test_field_validation_never_echoes_inputs(client, field, value):
    response = client.post("/api/models", json=DATA | {field: value})
    assert response.status_code == 422
    assert field in response.json()["detail"]["fields"]
    assert KEY not in response.text
    assert client.get("/api/models").json() == []


def test_bad_json_and_unknown_fields_do_not_echo_secret(client):
    response = client.post(
        "/api/models",
        content='{"api_key":"secret-body",',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422 and "secret-body" not in response.text
    response = client.post("/api/models", json=DATA | {KEY: KEY})
    assert response.status_code == 422 and KEY not in response.text


def test_key_failure_rolls_back_model_and_default(client, monkeypatch):
    def fail(*args, **kwargs):
        raise SecretStorageError

    monkeypatch.setattr(client.app.state.secret_store, "encrypt", fail)
    response = client.post("/api/models", json=DATA)
    assert response.status_code == 503 and KEY not in response.text
    assert client.get("/api/models").json() == []


def test_missing_master_key_is_not_silently_replaced(client):
    model = add(client)
    client.app.state.secret_store.path.unlink()
    response = client.post(f"/api/models/{model['id']}/test")
    assert response.json()["code"] == "key_unavailable"
    response = client.post("/api/models", json=DATA)
    assert response.status_code == 503
    assert not client.app.state.secret_store.path.exists()
    assert len(client.get("/api/models").json()) == 1


def test_sqlite_unique_default_and_concurrent_operations(client):
    state = client.app.state

    def create(_):
        with state.session_factory() as session:
            return save_model(session, ModelSave(**DATA), state.secret_store).id

    with ThreadPoolExecutor(max_workers=5) as pool:
        ids = list(pool.map(create, range(5)))
    assert sum(m["is_default"] for m in client.get("/api/models").json()) == 1

    def switch(model_id):
        with state.session_factory() as session:
            set_default(session, model_id)

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(switch, ids))
    with state.session_factory() as session:
        with pytest.raises(IntegrityError):
            session.execute(text("UPDATE language_models SET is_default = 1"))
        session.rollback()
    # 并发删除与切换后也只能有一个默认模型。
    models = client.get("/api/models").json()
    ordinary = next(m["id"] for m in models if not m["is_default"])
    remaining = [i for i in ids if i != ordinary]

    def remove():
        with state.session_factory() as session:
            delete_model(session, ordinary, None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(remove), pool.submit(switch, remaining[0])
        a.result()
        b.result()
    listed = client.get("/api/models").json()
    assert len(listed) == 4 and sum(m["is_default"] for m in listed) == 1


def test_real_request_contract_and_key_redaction(client, caplog):
    model = add(client)
    calls = []

    def provider(request):
        calls.append(request)
        assert str(request.url) == "https://example.com/v1/chat/completions"
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        payload = json.loads(request.content)
        assert payload["model"] == DATA["model_id"]
        assert payload["max_tokens"] == 64 and payload["temperature"] == 1
        assert payload["stream"] is False and payload["messages"][0]["role"] == "user"
        return httpx.Response(200, json={"choices": [{"message": {"content": f"你好 {KEY}"}}]})

    client.app.state.model_transport = httpx.MockTransport(provider)
    response = client.post(f"/api/models/{model['id']}/test")
    assert response.json()["success"] and response.json()["reply"].startswith("你好")
    assert KEY not in response.text and KEY not in caplog.text
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, {"error": {"message": KEY}}, "invalid_key"),
        (403, {}, "forbidden"),
        (404, {}, "not_found"),
        (404, {"error": {"code": "model_not_found", "message": KEY}}, "invalid_model"),
        (400, {"error": {"code": "invalid_api_key"}}, "invalid_key"),
        (400, {"error": {"message": KEY}}, "request_rejected"),
        (429, {}, "rate_limited"),
        (503, {}, "provider_error"),
        (302, {}, "redirect"),
        (200, {}, "invalid_response"),
        (200, {"choices": []}, "invalid_response"),
        (200, {"choices": [{"message": {"content": None}}]}, "invalid_response"),
        (200, {"choices": [{"message": {"content": "  "}}]}, "invalid_response"),
        (200, "<html>not JSON</html>", "invalid_response"),
    ],
)
def test_provider_failures_are_explained_without_secret(client, status, body, expected, caplog):
    model = add(client)

    def provider(request):
        return httpx.Response(status, json=body, headers={"location": "https://elsewhere.example"})

    client.app.state.model_transport = httpx.MockTransport(provider)
    response = client.post(f"/api/models/{model['id']}/test")
    assert response.status_code == 200 and not response.json()["success"]
    assert response.json()["code"] == expected and response.json()["suggestion"]
    assert KEY not in response.text and KEY not in caplog.text


@pytest.mark.parametrize(
    ("exception", "code"),
    [
        (httpx.ConnectError, "unreachable"),
        (httpx.ReadTimeout, "timeout"),
        (httpx.RemoteProtocolError, "invalid_response"),
    ],
)
def test_network_failures(client, exception, code):
    model = add(client)

    def provider(request):
        raise exception(KEY)

    client.app.state.model_transport = httpx.MockTransport(provider)
    result = client.post(f"/api/models/{model['id']}/test")
    assert result.json()["code"] == code and KEY not in result.text


def test_duplicate_connection_test_is_rejected(client):
    model = add(client)

    async def provider(request):
        await asyncio.sleep(0.15)
        return httpx.Response(200, json={"choices": [{"message": {"content": "你好"}}]})

    client.app.state.model_transport = httpx.MockTransport(provider)

    async def concurrently():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://test"
        ) as api:
            return await asyncio.gather(
                *[api.post(f"/api/models/{model['id']}/test") for _ in range(2)]
            )

    responses = asyncio.run(concurrently())
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert not client.app.state.active_model_tests
