import asyncio
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select
from test_chat import MODEL, Stream, frame

from app.models import Automation, ChatMessage, Conversation
from app.services.automations import next_time


def configure(client):
    model = client.post("/api/models", json=MODEL).json()
    agent = client.post(
        "/api/agents",
        json={"name": "定时助手", "model_id": model["id"], "system_prompt": "简洁回复"},
    ).json()
    return agent["id"]


def test_projects_membership_and_empty_reuse(client):
    p = client.post("/api/workspace/projects", json={"name": "项目一"}).json()
    a = client.post("/api/chat/conversations", json={}).json()
    b = client.post("/api/chat/conversations", json={"project_id": p["id"]}).json()
    assert a["id"] != b["id"]
    assert (
        client.post("/api/chat/conversations", json={"project_id": p["id"]}).json()["id"] == b["id"]
    )
    assert (
        client.patch(f"/api/chat/conversations/{a['id']}", json={"project_id": p["id"]}).json()[
            "project_id"
        ]
        == p["id"]
    )
    assert (
        client.patch(
            f"/api/chat/conversations/{a['id']}", json={"project_id": "missing"}
        ).status_code
        == 404
    )
    assert client.delete(f"/api/workspace/projects/{p['id']}").status_code == 204
    assert all(c["project_id"] is None for c in client.get("/api/chat/conversations").json())
    assert client.post("/api/workspace/projects", json={"name": "  "}).status_code == 422


def test_folder_authorization_binding_and_archive(client, tmp_path):
    root = client.app.state.tool_runtime.root
    root.mkdir(exist_ok=True)
    (root / "work").mkdir()
    (root / ".private").mkdir()
    (root / "outside").symlink_to(tmp_path)
    listing = client.get("/api/workspace/folders").json()
    assert [i["name"] for i in listing["items"]] == ["work"]
    for folder in ["../outside", "/etc", "outside", ".private", "missing"]:
        assert client.post("/api/chat/conversations", json={"folder": folder}).status_code == 422
    c = client.post("/api/chat/conversations", json={"folder": "work"}).json()
    store = client.app.state.workspace_store
    with client.app.state.session_factory() as session:
        session.add(
            ChatMessage(
                id=str(uuid4()),
                conversation_id=c["id"],
                sequence=1,
                role="user",
                content="持久化内容",
                status="completed",
                created_at=datetime.now(UTC),
            )
        )
        session.commit()
    store.archive(c["id"])
    file = root / "work" / f"conversation-{c['id']}.md"
    assert "持久化内容" in file.read_text()
    assert file.stat().st_mode & 0o777 == 0o600
    assert (
        client.patch(f"/api/chat/conversations/{c['id']}", json={"folder": "."}).status_code == 409
    )
    file.unlink()
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("untouched")
    file.symlink_to(sentinel)
    store.archive(c["id"])
    assert sentinel.read_text() == "untouched"
    assert client.get(f"/api/chat/conversations/{c['id']}").json()["archive_error"]
    file.unlink()
    store.archive(c["id"])
    assert client.get(f"/api/chat/conversations/{c['id']}").json()["archive_error"] is None


def test_automation_validation_lifecycle_and_result(client):
    agent = configure(client)
    calls = []

    async def handler(request):
        calls.append(__import__("json").loads(request.content))
        return httpx.Response(
            200, stream=Stream([frame("定时结果"), frame(finish="stop"), b"data: [DONE]\n\n"])
        )

    client.app.state.chat_store.transport = httpx.MockTransport(handler)
    data = {"name": "日报", "prompt": "总结今天", "agent_id": agent}
    assert client.post("/api/automations", json={**data, "time": "25:00"}).status_code == 422
    assert (
        client.post("/api/automations", json={**data, "timezone": "not/a/timezone"}).status_code
        == 422
    )
    task = client.post("/api/automations", json=data).json()
    assert task["allow_tools"] is False
    assert client.post(f"/api/automations/{task['id']}/run", json={}).status_code == 200
    for _ in range(200):
        task = client.get("/api/automations").json()[0]
        if task["status"] != "running":
            break
        time.sleep(0.01)
    assert task["status"] == "completed", task
    detail = client.get(f"/api/chat/conversations/{task['last_conversation_id']}").json()
    assert detail["messages"][-1]["content"] == "定时结果"
    assert not calls[0].get("tools")
    assert (
        client.patch(f"/api/automations/{task['id']}", json={"enabled": False}).json()["enabled"]
        is False
    )
    assert client.delete(f"/api/automations/{task['id']}").status_code == 204
    assert client.get(f"/api/chat/conversations/{task['last_conversation_id']}").status_code == 200


def test_next_schedule_and_claim_once(client):
    client.app.state.chat_store.transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, stream=Stream([frame("结果"), frame(finish="stop"), b"data: [DONE]\n\n"])
        )
    )
    now = datetime(2026, 9, 25, 2, 0, tzinfo=UTC)  # Friday 10am Shanghai
    row = SimpleNamespace(time="09:00", frequency="weekdays", weekday=0, timezone="Asia/Shanghai")
    assert next_time(row, now) == datetime(2026, 9, 28, 1, 0, tzinfo=UTC)
    agent = configure(client)
    task = client.post(
        "/api/automations", json={"name": "任务", "prompt": "测试", "agent_id": agent}
    ).json()
    store = client.app.state.automation_store

    async def scenario():
        with store.factory() as session:
            row = session.get(Automation, task["id"])
            row.next_run_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
        store.tick()
        store.tick()
        assert len(store.tasks) == 1
        with pytest.raises(HTTPException):
            store.start(task["id"])
        await asyncio.gather(*list(store.tasks.values()))

    client.portal.call(scenario)


def test_migration_roundtrip_keeps_conversation_messages(migration_config, migrated_database):
    from sqlalchemy.orm import Session

    from app.db import make_engine

    engine = make_engine(migrated_database)
    with Session(engine) as session:
        session.add(
            Conversation(
                id="keep", title="保留", created_at=datetime.now(UTC), updated_at=datetime.now(UTC)
            )
        )
        session.flush()
        session.add(
            ChatMessage(
                id="message",
                conversation_id="keep",
                sequence=1,
                role="user",
                content="保留正文",
                status="completed",
                created_at=datetime.now(UTC),
            )
        )
        session.commit()
    command.downgrade(migration_config, "4c1fef24e918")
    command.upgrade(migration_config, "head")
    command.check(migration_config)
    with Session(engine) as session:
        assert session.scalar(select(ChatMessage.content)) == "保留正文"
    engine.dispose()


def test_folder_scope_keeps_file_tool_in_selected_subdirectory(client):
    from app.services.tool_execution import execute_tool

    runtime = client.app.state.tool_runtime
    runtime.prepare_root()
    (runtime.root / "selected").mkdir()
    (runtime.root / "outside.txt").write_text("parent content")
    client.patch("/api/tools/file", json={"enabled": True})
    with client.app.state.session_factory() as session:
        result = execute_tool(
            session,
            runtime,
            "file",
            {"operation": "create", "path": "note.txt", "content": "inside"},
            scope="selected",
        )
        assert result.success, result
        assert (runtime.root / "selected" / "note.txt").read_text() == "inside"
        assert not (runtime.root / "note.txt").exists()
        result = execute_tool(
            session,
            runtime,
            "file",
            {"operation": "read", "path": "../outside.txt"},
            scope="selected",
        )
        assert not result.success
        result = execute_tool(
            session, runtime, "file", {"operation": "read", "path": "outside.txt"}, scope="selected"
        )
        assert not result.success
    assert runtime.root.name == "workspace"


def test_restart_skips_missed_schedule_and_recovers_running(client):
    from app.services.automations import AutomationStore

    agent = configure(client)
    task = client.post(
        "/api/automations", json={"name": "重启任务", "prompt": "测试", "agent_id": agent}
    ).json()
    old = client.app.state.automation_store

    async def restart():
        await old.close()
        with old.factory() as session:
            row = session.get(Automation, task["id"])
            row.status = "running"
            row.next_run_at = datetime.now(UTC) - timedelta(days=3)
            session.commit()
        fresh = AutomationStore(old.factory, old.chat)
        fresh.launch()
        item = fresh.listing()[0]
        assert item.status == "failed"
        assert item.next_run_at > datetime.now(UTC)
        assert not fresh.tasks
        await fresh.close()

    client.portal.call(restart)


def test_stop_before_execution_prevents_model_call(client):
    agent = configure(client)
    task = client.post(
        "/api/automations", json={"name": "停止任务", "prompt": "测试", "agent_id": agent}
    ).json()
    store = client.app.state.automation_store

    async def scenario():
        store.start(task["id"])
        await store.stop(task["id"])
        assert store.listing()[0].status == "cancelled"
        assert not store.chat.listing()

    client.portal.call(scenario)


def test_complete_reply_exports_md_and_regeneration_preserves_old_file(client):
    agent = configure(client)
    root = client.app.state.tool_runtime.root
    root.mkdir(exist_ok=True)
    (root / "outputs").mkdir()
    calls = []

    async def handler(request):
        calls.append(True)
        return httpx.Response(
            200,
            stream=Stream(
                [
                    frame(f"# 回复 {len(calls)}\n\n完整正文"),
                    frame(finish="stop"),
                    b"data: [DONE]\n\n",
                ]
            ),
        )

    client.app.state.chat_store.transport = httpx.MockTransport(handler)
    conversation = client.post("/api/chat/conversations", json={"folder": "outputs"}).json()
    cid = conversation["id"]
    client.put(f"/api/chat/conversations/{cid}/agent", json={"agent_id": agent})
    generation = client.post(
        f"/api/chat/conversations/{cid}/messages",
        json={"content": "写一段 MD", "request_id": str(uuid4())},
    ).json()

    def complete():
        for _ in range(200):
            detail = client.get(f"/api/chat/conversations/{cid}").json()
            if detail["generation"]["status"] != "generating":
                return detail
            time.sleep(0.01)
        pytest.fail("generation did not finish")

    detail = complete()
    assert detail["generation"]["status"] == "completed", detail
    first = detail["messages"][-1]
    file = root / "outputs" / f"reply-{first['id']}.md"
    assert file.read_text() == first["content"]
    assert file.stat().st_mode & 0o777 == 0o600
    regenerated = client.post(
        f"/api/chat/conversations/{cid}/generations/{generation['id']}/retry",
        json={"request_id": str(uuid4())},
    )
    assert regenerated.status_code == 201, regenerated.text
    detail = complete()
    second = detail["messages"][-1]
    assert second["id"] != first["id"]
    assert file.read_text() == first["content"]
    assert (root / "outputs" / f"reply-{second['id']}.md").read_text() == second["content"]
    assert len(list((root / "outputs").glob("reply-*.md"))) == 2


def test_reply_export_skips_unfinished_and_rejects_links_and_oversize(client, tmp_path):
    import os

    root = client.app.state.tool_runtime.root
    root.mkdir(exist_ok=True)
    (root / "outputs").mkdir()
    c = client.post("/api/chat/conversations", json={"folder": "outputs"}).json()
    ids = []
    with client.app.state.session_factory() as session:
        for sequence, status in enumerate(["completed", "generating", "failed", "cancelled"], 1):
            mid = str(uuid4())
            ids.append(mid)
            session.add(
                ChatMessage(
                    id=mid,
                    conversation_id=c["id"],
                    sequence=sequence,
                    role="assistant",
                    content="输出正文",
                    status=status,
                    created_at=datetime.now(UTC),
                )
            )
        session.commit()
    store = client.app.state.workspace_store
    store.archive(c["id"])
    exported = root / "outputs" / f"reply-{ids[0]}.md"
    assert [f.name for f in (root / "outputs").glob("reply-*.md")] == [exported.name]
    exported.unlink()
    sentinel = tmp_path / "reply-sentinel.md"
    sentinel.write_text("untouched")
    for linked in ["symlink", "hardlink"]:
        if linked == "symlink":
            exported.symlink_to(sentinel)
        else:
            os.link(sentinel, exported)
        store.archive(c["id"])
        assert sentinel.read_text() == "untouched"
        assert client.get(f"/api/chat/conversations/{c['id']}").json()["archive_error"]
        exported.unlink()
    store.archive(c["id"])
    assert client.get(f"/api/chat/conversations/{c['id']}").json()["archive_error"] is None
    with client.app.state.session_factory() as session:
        session.get(ChatMessage, ids[0]).content = "大" * (1024 * 1024 // 3 + 1)
        session.commit()
    store.archive(c["id"])
    assert exported.read_text() == "输出正文"
    assert client.get(f"/api/chat/conversations/{c['id']}").json()["archive_error"]
