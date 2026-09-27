import json
import threading
import time
from uuid import uuid4

import httpx
from sqlalchemy import event
from test_agent_runtime import tool_stream
from test_chat import MODEL, Stream, create, frame, normal, send

from app.models import ChatGeneration
from app.services.agent_runtime import RuntimeEvent


def usage_stream(text="完成", *, prompt=20, completion=5, cached=7):
    usage = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "prompt_tokens_details": {"cached_tokens": cached},
    }
    return Stream(
        [
            frame(text),
            frame(finish="stop"),
            ("data: " + json.dumps({"choices": [], "usage": usage}) + "\n\n").encode(),
            b"data: [DONE]\n\n",
        ]
    )


def configure(client, *, max_rounds=5, tools=None):
    model = client.post("/api/models", json=MODEL).json()
    if tools and "file" in tools:
        assert client.patch("/api/tools/file", json={"enabled": True}).status_code == 200
    agent = client.post(
        "/api/agents",
        json={
            "name": "可观察助手",
            "model_id": model["id"],
            "system_prompt": "安全地完成任务",
            "max_rounds": max_rounds,
            "tool_ids": tools or [],
        },
    ).json()
    streams = []

    def handler(_request):
        return httpx.Response(200, stream=streams.pop(0))

    client.app.state.chat_store.transport = httpx.MockTransport(handler)
    return agent, model, streams


def wait_detail(client, run_id):
    for _ in range(400):
        response = client.get(f"/api/runs/{run_id}")
        if response.status_code == 200 and response.json()["status"] != "running":
            return response.json()
        time.sleep(0.01)
    raise AssertionError("Run 未结束")


def start(client, streams, stream):
    streams.append(stream)
    conversation = create(client)
    response = send(client, conversation)
    assert response.status_code == 201, response.text
    return conversation, response.json()["id"]


def test_success_metrics_snapshots_first_output_and_chat_consistency(client):
    _agent, _model, streams = configure(client)
    conversation, run_id = start(client, streams, usage_stream())
    run = wait_detail(client, run_id)
    chat = client.get(f"/api/chat/conversations/{conversation}").json()["generation"]
    assert run["id"] == run_id and run["status"] == "success"
    assert chat["status"] == "completed"
    assert run["agent_name"] == "可观察助手" and run["model_name"] == "测试模型"
    assert run["model_call_count"] == 1 and run["tool_call_count"] == 0
    assert (run["input_tokens"], run["output_tokens"], run["total_tokens"]) == (20, 5, 25)
    assert run["cached_input_tokens"] == 7 and run["usage_status"] == "complete"
    assert run["first_output_ms"] is not None and run["first_output_ms"] >= 0
    assert [event["sequence"] for event in run["events"]] == list(range(1, len(run["events"]) + 1))
    starts = {event["call_id"] for event in run["events"] if event["type"] == "model_start"}
    ends = {event["call_id"] for event in run["events"] if event["type"] == "model_end"}
    assert starts == ends


def test_tool_failure_can_continue_and_counts_only_entered_execution(client):
    _agent, _model, streams = configure(client, tools=["file"])
    streams.extend(
        [
            tool_stream([("local__file", {"operation": "read", "path": "missing.txt"})]),
            normal("已处理工具失败并完成回答"),
        ]
    )
    conversation = create(client)
    response = send(client, conversation)
    run = wait_detail(client, response.json()["id"])
    tool = next(event for event in run["events"] if event["type"] == "tool_result")
    assert run["status"] == "success" and run["tool_call_count"] == 1
    assert tool["data"]["status"] == "failed" and tool["data"]["executed"] is True


def test_validation_rejection_does_not_count_as_execution(client):
    _agent, _model, streams = configure(client, tools=["file"])
    streams.extend(
        [
            tool_stream([("local__file", {"path": "missing-operation.txt"})]),
            normal("参数无效后仍完成"),
        ]
    )
    conversation = create(client)
    response = send(client, conversation)
    run = wait_detail(client, response.json()["id"])
    tool = next(event for event in run["events"] if event["type"] == "tool_result")
    assert run["status"] == "success" and run["tool_call_count"] == 0
    assert tool["data"]["executed"] is False


def test_model_failure_keeps_partial_body_and_unknown_usage(client):
    _agent, _model, streams = configure(client)
    broken = Stream([frame("未完成正文")], failure=httpx.ReadError("private failure"))
    conversation, run_id = start(client, streams, broken)
    run = wait_detail(client, run_id)
    assert run["status"] == "failed" and run["final_answer"] == "未完成正文"
    assert run["model_call_count"] == 1 and run["usage_status"] == "unknown"
    assert run["error_summary"] and "private failure" not in run["error_summary"]
    assert any(event["type"] == "run_error" for event in run["events"])


def test_cancel_limit_background_and_interruption_recovery(client):
    _agent, _model, streams = configure(client)
    gate = threading.Event()
    conversation, run_id = start(client, streams, Stream([frame("部分"), frame("等待")], gate))
    for _ in range(200):
        if client.get(f"/api/runs/{run_id}").json()["first_output_ms"] is not None:
            break
        time.sleep(0.01)
    stopped = client.post(
        f"/api/chat/conversations/{conversation}/generations/{run_id}/stop", json={}
    )
    assert stopped.status_code == 200
    assert wait_detail(client, run_id)["status"] == "cancelled"

    # 未建立 SSE 订阅时任务仍在 Store 后台完成。
    _conversation, background_id = start(client, streams, normal("后台完成"))
    assert wait_detail(client, background_id)["status"] == "success"

    with client.app.state.session_factory() as session:
        row = session.get(ChatGeneration, background_id)
        row.status = "generating"
        row.ended_at = None
        row.duration_ms = None
        session.commit()
    client.app.state.chat_store.recover()
    recovered = client.get(f"/api/runs/{background_id}").json()
    assert recovered["status"] == "failed" and recovered["end_reason"] == "运行中断"

    limited_client = client
    # 新 Agent 使用单轮限制；最后一轮返回工具请求，Run 应为部分完成。
    second_model = client.post("/api/models", json={**MODEL, "model_id": "limited"}).json()
    limited_agent = client.post(
        "/api/agents",
        json={
            "name": "单轮助手",
            "model_id": second_model["id"],
            "system_prompt": "只运行一轮",
            "max_rounds": 1,
            "tool_ids": ["current_time"],
        },
    ).json()
    limited_conversation = create(limited_client)
    assert (
        client.put(
            f"/api/chat/conversations/{limited_conversation}/agent",
            json={"agent_id": limited_agent["id"]},
        ).status_code
        == 200
    )
    streams.append(tool_stream([("local__current_time", {})]))
    limited_id = send(client, limited_conversation).json()["id"]
    assert wait_detail(client, limited_id)["status"] == "partial"


def test_event_dedup_redaction_payload_and_constant_list_queries(client):
    _agent, _model, streams = configure(client)
    run_ids = []
    for _ in range(3):
        _conversation, run_id = start(client, streams, usage_stream())
        wait_detail(client, run_id)
        run_ids.append(run_id)
    run_id = run_ids[0]
    original = client.app.state.run_store.persisted_events_since(run_id, 0)
    model_start = next(event for event in original if event.type == "model_start")
    before = client.get(f"/api/runs/{run_id}").json()["model_call_count"]
    client.app.state.run_store.record(run_id, model_start)
    client.app.state.run_store.record(run_id, model_start)
    assert client.get(f"/api/runs/{run_id}").json()["model_call_count"] == before

    sequence = max(event.sequence for event in original) + 10
    client.app.state.run_store.record(
        run_id,
        RuntimeEvent(
            run_id,
            sequence,
            "tool_start",
            2,
            str(uuid4()),
            {
                "display_name": "文件",
                "input": {
                    "value": {
                        "path": "/Users/private/Documents/secret.txt",
                        "authorization": "Bearer top-secret",
                    },
                    "truncated": False,
                },
            },
        ),
    )
    detail = client.get(f"/api/runs/{run_id}").text
    payload = client.get(f"/api/runs/{run_id}/events/{sequence}/payload").text
    assert "top-secret" not in detail + payload and "/Users/private" not in detail + payload
    assert "[已隐藏]" in payload and "[路径已隐藏]" in payload

    engine = client.app.state.session_factory.kw["bind"]
    counts = []

    def count_queries(*_args):
        counts[-1] += 1

    event.listen(engine, "before_cursor_execute", count_queries)
    try:
        for size in (1, 20):
            counts.append(0)
            assert client.get(f"/api/runs?page=1&page_size={size}").status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", count_queries)
    assert counts[0] == counts[1] == 3
