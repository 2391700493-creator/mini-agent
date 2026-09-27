import asyncio
import json
import threading
import time
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.main import create_app
from app.models import ChatGeneration, ChatMessage, Conversation

MODEL = {
    "display_name": "测试模型",
    "model_id": "test",
    "base_url": "https://example.com/v1",
    "api_key": "secret-test-only-key",
    "context_length": 8192,
    "max_output_tokens": 512,
    "temperature": 0.5,
}


def frame(content=None, finish=None):
    return (
        "data: "
        + json.dumps(
            {"choices": [{"index": 0, "delta": {"content": content}, "finish_reason": finish}]}
        )
        + "\r\n\r\n"
    ).encode()


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks, gate=None, failure=None):
        self.chunks, self.gate, self.failure = chunks, gate, failure
        self.closed = False

    async def __aiter__(self):
        for index, chunk in enumerate(self.chunks):
            yield chunk
            if index == 0 and self.gate:
                while not self.gate.is_set():
                    await asyncio.sleep(0.005)
        if self.failure:
            raise self.failure

    async def aclose(self):
        self.closed = True


@pytest.fixture
def chat(client):
    config = client.post("/api/models", json=MODEL).json()
    agent = client.post(
        "/api/agents",
        json={
            "name": "原助手",
            "model_id": config["id"],
            "system_prompt": "原系统提示词",
        },
    ).json()
    calls = []
    streams = []

    def handler(request):
        calls.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer " + MODEL["api_key"]
        return httpx.Response(200, stream=streams.pop(0))

    client.app.state.chat_store.transport = httpx.MockTransport(handler)
    return client, agent, calls, streams


def create(client):
    response = client.post("/api/chat/conversations", json={})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def send(client, conversation, content="你好", request_id=None):
    return client.post(
        f"/api/chat/conversations/{conversation}/messages",
        json={
            "content": content,
            "request_id": request_id or str(uuid4()),
        },
    )


def detail(client, conversation):
    return client.get(f"/api/chat/conversations/{conversation}").json()


def finished(client, conversation):
    for _ in range(300):
        result = detail(client, conversation)
        if result.get("generation") and result["generation"]["status"] != "generating":
            return result
        time.sleep(0.01)
    pytest.fail("生成未结束")


def partial(client, conversation):
    for _ in range(200):
        result = detail(client, conversation)
        if len(result["messages"]) == 2:
            return result
        time.sleep(0.01)
    pytest.fail("未收到流式正文")


def normal(text="你好，世界"):
    return Stream([frame(text), frame(finish="stop"), b"data: [DONE]\n\n"])


def test_persistence_history_switch_snapshot_and_isolation(chat, migrated_database):
    client, agent, calls, streams = chat
    conversation = create(client)
    assert detail(client, conversation)["agent_id"] == agent["id"]
    streams.append(normal())
    assert send(client, conversation, "第一问").status_code == 201
    first = finished(client, conversation)
    assert first["title"] == "第一问"
    assert [m["sequence"] for m in first["messages"]] == [1, 2]
    assert first["generation"]["status"] == "completed"
    assert calls[0]["messages"] == [
        {"role": "system", "content": "原系统提示词"},
        {"role": "user", "content": "第一问"},
    ]
    assert calls[0]["stream"] is True and "tools" not in calls[0]
    summary = client.get("/api/chat/conversations").json()[0]
    assert "messages" not in summary
    assert detail(client, conversation)["updated_at"] == summary["updated_at"]
    other_model = client.post("/api/models", json={**MODEL, "model_id": "second-model"}).json()
    other_agent = client.post(
        "/api/agents",
        json={
            "name": "新助手",
            "model_id": other_model["id"],
            "system_prompt": "新系统提示词",
        },
    ).json()
    response = client.put(
        f"/api/chat/conversations/{conversation}/agent",
        json={
            "agent_id": other_agent["id"],
        },
    )
    assert response.status_code == 200
    assert response.json()["updated_at"] == summary["updated_at"]
    streams.append(normal("继续回答"))
    send(client, conversation, "追问")
    result = finished(client, conversation)
    assert calls[-1]["messages"] == [
        {"role": "system", "content": "新系统提示词"},
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "你好，世界"},
        {"role": "user", "content": "追问"},
    ]
    assert calls[-1]["model"] == "second-model"
    assert result["messages"][1]["agent_name"] == "原助手"
    client.request(
        "DELETE", f"/api/agents/{agent['id']}", json={"replacement_id": other_agent["id"]}
    )
    assert detail(client, conversation)["messages"][1]["agent_id"] == agent["id"]
    new = create(client)
    streams.append(normal())
    send(client, new, "隔离问题")
    finished(client, new)
    assert len(calls[-1]["messages"]) == 2
    client.request("DELETE", f"/api/agents/{other_agent['id']}", json={})
    assert detail(client, conversation)["agent_id"] is None
    assert send(client, conversation).status_code == 409
    with TestClient(
        create_app(
            migrated_database,
            key_path=migrated_database.with_suffix(".key"),
            skills_root=migrated_database.parent / "skills",
            tool_root=migrated_database.parent / "workspace",
        )
    ) as reopened:
        assert detail(reopened, conversation)["messages"] == result["messages"]


def test_background_cancel_and_exclude_partial(chat):
    client, agent, calls, streams = chat
    gate = threading.Event()
    stream = Stream(
        [frame("部分正文"), frame("余下正文"), frame(finish="stop"), b"data: [DONE]\n\n"], gate
    )
    streams.append(stream)
    conversation = create(client)
    result = send(client, conversation).json()
    running = partial(client, conversation)
    assert running["generation"]["status"] == "generating"
    assert running["messages"][1]["content"] == "部分正文"
    assert send(client, conversation).status_code == 409
    assert (
        client.put(
            f"/api/chat/conversations/{conversation}/agent", json={"agent_id": agent["id"]}
        ).status_code
        == 409
    )
    # 创建和读取其他会话不改变后台任务。
    other = create(client)
    assert detail(client, other)["messages"] == []
    stopped = client.post(
        f"/api/chat/conversations/{conversation}/generations/{result['id']}/stop", json={}
    )
    assert stopped.json()["status"] == "cancelled"
    assert stream.closed
    assert detail(client, conversation)["messages"][1]["status"] == "cancelled"
    streams.append(normal())
    send(client, conversation, "继续")
    finished(client, conversation)
    assert calls[-1]["messages"] == [
        {"role": "system", "content": "原系统提示词"},
        {"role": "user", "content": "你好"},
        {"role": "user", "content": "继续"},
    ]


def test_background_finishes_without_subscription_and_idempotency(chat):
    client, _, calls, streams = chat
    gate = threading.Event()
    streams.append(
        Stream([frame("一"), frame("二"), frame(finish="stop"), b"data: [DONE]\n\n"], gate)
    )
    conversation = create(client)
    key = str(uuid4())
    send(client, conversation, request_id=key)
    partial(client, conversation)
    assert send(client, conversation, request_id=key).status_code == 201
    assert send(client, conversation, "不同输入", key).status_code == 409
    create(client)
    gate.set()
    done = finished(client, conversation)
    assert done["messages"][1]["content"] == "一二"
    assert len(calls) == 1
    response = client.get(f"/api/chat/conversations/{conversation}/generations/{key}/events")
    events = [
        json.loads(block[6:]) for block in response.text.split("\n\n") if block.startswith("data: ")
    ]
    assert len(events) == 1 and events[0]["status"] == "completed"
    assert events[0]["message"]["content"] == "一二"


@pytest.mark.parametrize(
    "stream,reason,partial_text",
    [
        (Stream([frame(finish="stop"), b"data: [DONE]\n\n"]), "空内容", None),
        (Stream([frame("半句")]), "中断", "半句"),
        (Stream([frame("半句"), frame(finish="length"), b"data: [DONE]\n\n"]), "输出上限", "半句"),
        (Stream([frame("前文"), b"data: invalid\n\n"]), "格式", "前文"),
        (Stream([], failure=httpx.ReadTimeout("secret-test-only-key")), "超时", None),
        (Stream([], failure=httpx.ConnectError("secret-test-only-key")), "连接失败", None),
        (Stream([frame("   "), frame(finish="stop"), b"data: [DONE]\n\n"]), "空内容", None),
    ],
)
def test_failures_are_separate_and_no_empty_messages(chat, stream, reason, partial_text):
    client, _, _, streams = chat
    streams.append(stream)
    conversation = create(client)
    send(client, conversation)
    result = finished(client, conversation)
    assert result["generation"]["status"] == "failed"
    assert reason in result["generation"]["error"]
    assert MODEL["api_key"] not in json.dumps(result)
    assert len(result["messages"]) == (2 if partial_text else 1)
    if partial_text:
        assert result["messages"][1]["content"] == partial_text
        assert result["messages"][1]["status"] == "failed"
    assert stream.closed


def test_context_guard_keeps_user_and_never_drops_history(chat):
    client, _, calls, _ = chat
    conversation = create(client)
    assert send(client, conversation, "过长" * 4000).status_code == 201
    result = finished(client, conversation)
    assert "上下文容量" in result["generation"]["error"]
    assert len(result["messages"]) == 1 and not calls


def test_chat_runtime_persists_incremental_summary_without_removing_history(chat):
    client, agent, calls, streams = chat
    assert (
        client.put(
            f"/api/models/{agent['model_id']}",
            json={**MODEL, "context_length": 4096},
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/agents/{agent['id']}",
            json={
                "name": agent["name"],
                "model_id": agent["model_id"],
                "system_prompt": "原系统提示词",
                "compression_trigger_ratio": 0.5,
                "compression_keep_recent_turns": 1,
            },
        ).status_code
        == 200
    )
    conversation = create(client)
    streams.append(normal("第一答" * 300))
    send(client, conversation, "第一问")
    finished(client, conversation)
    streams.append(normal("第二答" * 300))
    send(client, conversation, "第二问")
    finished(client, conversation)
    streams.extend([normal("较早会话摘要"), normal("第三答")])
    send(client, conversation, "第三问")
    result = finished(client, conversation)
    assert result["generation"]["status"] == "completed"
    assert len(result["messages"]) == 6
    with client.app.state.session_factory() as session:
        row = session.get(Conversation, conversation)
        assert row.context_summary == "较早会话摘要"
        assert row.summarized_through_sequence == 2
    final_context = json.dumps(calls[-1]["messages"], ensure_ascii=False)
    assert "较早会话摘要" in final_context and "第二答" in final_context
    assert "第一答" not in final_context


def test_missing_key_and_provider_errors_are_sanitized(chat, caplog):
    client, _, _, _ = chat
    client.app.state.chat_store.transport = httpx.MockTransport(
        lambda _: httpx.Response(
            400,
            json={"error": {"code": "context_length_exceeded", "message": MODEL["api_key"]}},
        )
    )
    conversation = create(client)
    send(client, conversation)
    result = finished(client, conversation)
    assert "上下文容量" in result["generation"]["error"]
    client.app.state.secret_store.path.unlink()
    send(client, conversation, "下一问")
    result = finished(client, conversation)
    assert "密钥无法读取" in result["generation"]["error"]
    assert MODEL["api_key"] not in caplog.text + json.dumps(result)


def test_unbound_capabilities_and_failed_user_save(chat, monkeypatch):
    client, _, calls, streams = chat
    conversation = create(client)

    def forbidden(*args, **kwargs):
        raise AssertionError("禁止读取或执行能力")

    monkeypatch.setattr(client.app.state.skill_store, "for_agent", forbidden)
    monkeypatch.setattr(client.app.state.mcp_store, "for_agent", forbidden)
    monkeypatch.setattr(client.app.state.agent_store, "get", forbidden)
    streams.append(normal())
    send(client, conversation)
    assert finished(client, conversation)["generation"]["status"] == "completed"
    factory = client.app.state.chat_store.factory

    def broken():
        raise OperationalError("", {}, Exception("private"))

    monkeypatch.setattr(client.app.state.chat_store, "factory", broken)
    assert send(client, conversation, "不能保存").status_code == 503
    monkeypatch.setattr(client.app.state.chat_store, "factory", factory)
    assert len(detail(client, conversation)["messages"]) == 2 and len(calls) == 1


def test_final_save_failure_is_explicit_and_does_not_lock_chat(chat, monkeypatch):
    client, _, _, streams = chat
    store = client.app.state.chat_store
    original = store.save_progress

    def fail_final(generation, content, status, error):
        if status == "completed":
            raise OperationalError("", {}, Exception("private"))
        return original(generation, content, status, error)

    monkeypatch.setattr(store, "save_progress", fail_final)
    streams.append(normal())
    conversation = create(client)
    run_id = send(client, conversation).json()["id"]
    result = finished(client, conversation)
    assert result["generation"]["saved"] is False
    assert "保存失败" in result["generation"]["error"]
    assert result["generation"]["message"]["content"] == "你好，世界"
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "failed" and run["events"][-1]["data"]["status"] == "failed"
    monkeypatch.setattr(store, "save_progress", original)
    streams.append(normal("下一条"))
    assert send(client, conversation, "继续").status_code == 201
    assert finished(client, conversation)["generation"]["status"] == "completed"


def test_recovery_marks_abandoned_reply_failed(chat):
    client, _, _, streams = chat
    conversation = create(client)
    streams.append(normal())
    send(client, conversation)
    finished(client, conversation)
    with client.app.state.session_factory() as session:
        session.scalar(select(ChatGeneration)).status = "generating"
        session.scalar(
            select(ChatMessage).where(ChatMessage.role == "assistant")
        ).status = "generating"
        session.commit()
    client.app.state.chat_store.recover()
    result = detail(client, conversation)
    assert result["generation"]["status"] == "failed"
    assert result["messages"][1]["status"] == "failed"


def test_validation_and_local_origin(chat):
    client, _, calls, _ = chat
    conversation = create(client)
    for content in ["", "   ", "\x00", "x" * 100001]:
        response = send(client, conversation, content)
        assert response.status_code == 422
        assert "input" not in response.text
    assert not detail(client, conversation)["messages"] and not calls
    assert (
        client.post(
            "/api/chat/conversations", json={}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )


def test_provider_key_echo_is_redacted_across_stream_frames(chat):
    client, _, _, streams = chat
    streams.append(
        Stream(
            [
                frame("正文 secret-test-"),
                frame("only-key 结尾"),
                frame(finish="stop"),
                b"data: [DONE]\n\n",
            ]
        )
    )
    conversation = create(client)
    send(client, conversation)
    result = finished(client, conversation)
    assert result["messages"][1]["content"] == "正文 [已隐藏] 结尾"
    assert MODEL["api_key"] not in json.dumps(result)


def test_pin_rename_order_and_custom_title_survive_send(chat):
    client, _, _, streams = chat
    older = create(client)
    before = detail(client, older)
    response = client.patch(
        f"/api/chat/conversations/{older}",
        json={
            "pinned": True,
            "title": "  我的计划  ",
        },
    )
    assert response.status_code == 200
    assert response.json()["title"] == "我的计划"
    assert response.json()["updated_at"] == before["updated_at"]
    newer = create(client)
    assert [row["id"] for row in client.get("/api/chat/conversations").json()] == [older, newer]
    client.patch(f"/api/chat/conversations/{older}", json={"pinned": False})
    assert [row["id"] for row in client.get("/api/chat/conversations").json()] == [newer, older]
    streams.append(normal())
    send(client, older, "不能覆盖我设置的名称")
    result = finished(client, older)
    assert result["title"] == "我的计划" and result["pinned"] is False
    for data in [
        {"title": " "},
        {"title": "x" * 101},
        {"title": "a\nb"},
        {"title": None},
        {"pinned": None},
        {"pinned": "true"},
        {"agent_id": "bad"},
    ]:
        assert client.patch(f"/api/chat/conversations/{older}", json=data).status_code == 422
    assert detail(client, older)["title"] == "我的计划"


def test_delete_cleans_only_own_history_and_rejects_active_generation(chat):
    client, _, _, streams = chat
    first = create(client)
    gate = threading.Event()
    streams.append(Stream([frame("部分正文"), frame("剩余正文")], gate))
    send(client, first)
    running = partial(client, first)
    other = create(client)
    assert client.delete(f"/api/chat/conversations/{first}").status_code == 409
    assert len(detail(client, first)["messages"]) == 2
    generation = running["generation"]["id"]
    client.post(f"/api/chat/conversations/{first}/generations/{generation}/stop", json={})
    assert client.delete(f"/api/chat/conversations/{first}").status_code == 204
    assert client.get(f"/api/chat/conversations/{first}").status_code == 404
    assert client.get(f"/api/chat/conversations/{other}").status_code == 200
    with client.app.state.session_factory() as session:
        assert not session.scalars(
            select(ChatMessage).where(ChatMessage.conversation_id == first)
        ).all()
        assert not session.scalars(
            select(ChatGeneration).where(ChatGeneration.conversation_id == first)
        ).all()
    assert len(client.get("/api/agents").json()) == 1
    assert len(client.get("/api/models").json()) == 1


def test_delete_failure_rolls_back_messages_and_generation(chat, monkeypatch):
    from sqlalchemy.orm import Session

    from app.models import Conversation

    client, _, _, streams = chat
    conversation = create(client)
    streams.append(normal())
    send(client, conversation)
    before = finished(client, conversation)
    original = Session.delete

    def fail(session, row):
        if isinstance(row, Conversation):
            raise OperationalError("", {}, Exception("private"))
        return original(session, row)

    monkeypatch.setattr(Session, "delete", fail)
    assert client.delete(f"/api/chat/conversations/{conversation}").status_code == 503
    assert detail(client, conversation) == before


def test_pinning_migration_round_trip_preserves_existing_history(chat, migration_config):
    from alembic import command

    client, _, _, streams = chat
    conversation = create(client)
    streams.append(normal())
    send(client, conversation)
    before = finished(client, conversation)
    client.patch(f"/api/chat/conversations/{conversation}", json={"pinned": True})
    command.downgrade(migration_config, "db0a193ebc09")
    command.upgrade(migration_config, "head")
    command.check(migration_config)
    after = detail(client, conversation)
    assert after["messages"] == before["messages"]
    assert after["generation"] == before["generation"]
    assert after["title"] == before["title"] and after["pinned"] is False


def test_create_reuses_unused_conversation_and_preserves_selection(chat):
    client, agent, calls, streams = chat
    first = create(client)
    assert create(client) == first
    assert len(client.get("/api/chat/conversations").json()) == 1
    assert detail(client, first)["agent_id"] == agent["id"]
    streams.append(normal())
    send(client, first)
    finished(client, first)
    second = create(client)
    assert second != first and create(client) == second
    assert len(client.get("/api/chat/conversations").json()) == 2


def test_create_preserves_named_and_pinned_empty_conversations(chat):
    client, _, _, _ = chat
    named = create(client)
    client.patch(f"/api/chat/conversations/{named}", json={"title": "准备中的任务"})
    pinned = create(client)
    assert pinned != named
    client.patch(f"/api/chat/conversations/{pinned}", json={"pinned": True})
    unused = create(client)
    assert unused not in {named, pinned} and create(client) == unused


def complete_stream(text):
    return Stream([frame(text), frame(finish="stop"), b"data: [DONE]\n\n"])


def image_attachment(name="image.png"):
    import base64
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(buffer, format="PNG")
    return {
        "name": name,
        "mime_type": "image/png",
        "data": base64.b64encode(buffer.getvalue()).decode(),
    }


def send_attachments(client, conversation, items, content="", request_id=None):
    return client.post(
        f"/api/chat/conversations/{conversation}/messages",
        json={
            "content": content,
            "attachments": items,
            "request_id": request_id or str(uuid4()),
        },
    )


def test_image_only_input_persists_bytes_and_multimodal_history(chat, caplog):
    import base64

    from app.models import ChatAttachment

    client, _, calls, streams = chat
    conversation = create(client)
    attachment = image_attachment()
    streams.extend([complete_stream("图片答复"), complete_stream("第二答")])
    response = send_attachments(client, conversation, [attachment])
    assert response.status_code == 201, response.text
    result = finished(client, conversation)
    assert result["generation"]["status"] == "completed"
    metadata = result["messages"][0]["attachments"][0]
    assert "data" not in metadata and "digest" not in metadata
    assert metadata["name"] == "image.png" and metadata["width"] == 16
    downloaded = client.get(f"/api/chat/attachments/{metadata['id']}")
    assert downloaded.content == base64.b64decode(attachment["data"])
    assert downloaded.headers["cache-control"] == "no-store"
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert calls[0]["messages"][-1]["content"][-1]["type"] == "image_url"
    assert calls[0]["messages"][-1]["content"][-1]["image_url"]["detail"] == "low"
    assert send(client, conversation, "再看看这张图片").status_code == 201
    finished(client, conversation)
    assert calls[1]["messages"][1]["content"][-1]["image_url"]["url"].endswith(attachment["data"])
    run = client.get(f"/api/runs/{response.json()['id']}")
    assert run.status_code == 200
    events = run.text
    assert attachment["data"] not in events and attachment["data"] not in caplog.text
    assert client.delete(f"/api/chat/conversations/{conversation}").status_code == 204
    assert client.get(f"/api/chat/attachments/{metadata['id']}").status_code == 404
    with client.app.state.session_factory() as session:
        assert session.scalar(select(ChatAttachment)) is None


def test_attachment_idempotency_includes_contents(chat):
    client, _, calls, streams = chat
    conversation = create(client)
    request_id = str(uuid4())
    streams.append(complete_stream("答复"))
    item = image_attachment()
    first = send_attachments(client, conversation, [item], request_id=request_id)
    finished(client, conversation)
    again = send_attachments(client, conversation, [item], request_id=request_id)
    assert again.status_code == 201 and again.json()["id"] == first.json()["id"]
    assert len(calls) == 1
    mismatch = send_attachments(
        client, conversation, [image_attachment("other.png")], request_id=request_id
    )
    assert mismatch.status_code == 409
    assert len(detail(client, conversation)["messages"]) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"data": "not-base64"},
        {"mime_type": "image/jpeg"},
        {"name": "../private.png"},
        {"mime_type": "image/svg+xml"},
        {"data": "c2VjcmV0"},
    ],
)
def test_invalid_attachments_never_commit_or_leak_input(chat, change, caplog):
    client, _, calls, _ = chat
    conversation = create(client)
    attachment = {**image_attachment(), **change}
    result = send_attachments(client, conversation, [attachment])
    assert result.status_code == 422
    assert "input" not in result.text and attachment["data"] not in caplog.text
    assert detail(client, conversation)["messages"] == [] and not calls


def test_attachment_byte_limit_is_checked_after_decoding(chat):
    import base64

    client, _, calls, _ = chat
    conversation = create(client)
    attachment = {
        "name": "large.txt",
        "mime_type": "text/plain",
        "data": base64.b64encode(b"x" * (5 * 1024 * 1024 + 1)).decode(),
    }
    response = send_attachments(client, conversation, [attachment])
    assert response.status_code == 422
    assert not calls and not detail(client, conversation)["messages"]


def pdf_attachment(text=None):
    import base64
    import io

    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    if text:
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return {
        "name": "document.pdf",
        "mime_type": "application/pdf",
        "data": base64.b64encode(output.getvalue()).decode(),
    }


def test_pdf_extracts_text_and_preserves_original(chat):
    client, _, calls, streams = chat
    conversation = create(client)
    streams.append(complete_stream("PDF 答复"))
    response = send_attachments(client, conversation, [pdf_attachment("Hello PDF")], "总结文件")
    assert response.status_code == 201, response.text
    result = finished(client, conversation)
    assert result["generation"]["status"] == "completed"
    content = calls[0]["messages"][-1]["content"]
    assert any("Hello PDF" in part.get("text", "") for part in content)
    metadata = result["messages"][0]["attachments"][0]
    response = client.get(f"/api/chat/attachments/{metadata['id']}")
    assert response.content.startswith(b"%PDF-")
    assert response.headers["content-disposition"] == "attachment"


def test_scanned_pdf_is_rejected_with_actionable_reason(chat):
    client, _, calls, _ = chat
    conversation = create(client)
    response = send_attachments(client, conversation, [pdf_attachment()])
    assert response.status_code == 422
    assert "扫描件" in response.json()["detail"]
    assert not calls and not detail(client, conversation)["messages"]


def test_regenerate_preserves_old_reply_reuses_user_and_disables_tools(chat):
    client, agent, calls, streams = chat
    assert (
        client.put(
            f"/api/agents/{agent['id']}",
            json={
                "name": agent["name"],
                "model_id": agent["model_id"],
                "system_prompt": "提示词",
                "tool_ids": ["current_time"],
            },
        ).status_code
        == 200
    )
    conversation = create(client)
    streams.extend(
        [
            complete_stream("旧答"),
            complete_stream("新答"),
            complete_stream("后续"),
        ]
    )
    original = send(client, conversation)
    finished(client, conversation)
    retry_id = str(uuid4())
    url = f"/api/chat/conversations/{conversation}/generations/{original.json()['id']}/retry"
    result = client.post(url, json={"request_id": retry_id})
    assert result.status_code == 201, result.text
    messages = finished(client, conversation)["messages"]
    assert [m["content"] for m in messages] == ["你好", "旧答", "新答"]
    assert "tools" in calls[0] and "tools" not in calls[1]
    assert "旧答" not in json.dumps(calls[1])
    assert client.post(url, json={"request_id": retry_id}).json()["id"] == retry_id
    assert len(calls) == 2
    assert send(client, conversation, "下一问").status_code == 201
    finished(client, conversation)
    history = json.dumps(calls[2]["messages"], ensure_ascii=False)
    assert "新答" in history and "旧答" not in history
    assert client.post(url, json={"request_id": str(uuid4())}).status_code == 409


def test_attachment_migration_round_trip_only_on_temporary_database(chat, migration_config):
    from alembic import command
    from sqlalchemy import inspect

    client, _, _, _ = chat
    command.downgrade(migration_config, "d452e338028f")
    with client.app.state.session_factory() as session:
        assert "chat_attachments" not in inspect(session.bind).get_table_names()
    command.upgrade(migration_config, "head")
    command.check(migration_config)
