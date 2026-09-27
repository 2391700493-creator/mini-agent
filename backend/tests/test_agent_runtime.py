"""直接调用 Runtime，验证模型循环、权限边界、事件与资源生命周期。"""

import asyncio
import json
import logging
import os
import sys
import threading
import time
from dataclasses import asdict
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import delete
from test_chat import MODEL, Stream, create, finished, frame, normal, send

from app.models import AgentTool, ChatGeneration, ChatMessage
from app.services.agent_runtime import (
    Cancellation,
    CapabilityLimits,
    RuntimeContext,
    RuntimeRequest,
    tool_name,
)


def tool_stream(calls, text="", *, usage=None):
    # 参数和名称跨 SSE 帧；多个工具交错出现。
    chunks = [frame(text)] if text else []
    for index, (name, args) in enumerate(calls):
        arguments = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
        for offset, part in enumerate((arguments[:2], arguments[2:])):
            function = {"arguments": part}
            fragment = {"index": index, "function": function}
            if offset == 0:
                fragment.update(id=f"call_{index}", type="function")
                function["name"] = name
            chunks.append(
                (
                    "data: "
                    + json.dumps(
                        {
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"tool_calls": [fragment]},
                                    "finish_reason": None,
                                }
                            ]
                        }
                    )
                    + "\n\n"
                ).encode()
            )
    chunks.append(frame(finish="tool_calls"))
    if usage is not None:
        chunks.append(("data: " + json.dumps({"choices": [], "usage": usage}) + "\n\n").encode())
    chunks.append(b"data: [DONE]\n\n")
    return Stream(chunks)


@pytest.fixture
def setup(client):
    model = client.post("/api/models", json={**MODEL, "context_length": 1000000}).json()
    data = {
        "name": "运行助手",
        "model_id": model["id"],
        "system_prompt": "系统指令",
        "tool_ids": ["current_time"],
        "max_rounds": 5,
    }
    response = client.post("/api/agents", json=data)
    assert response.status_code == 201, response.text
    return client, response.json(), data


def run(setup, streams, *, limits=None, hook=None, input="用户问题", history=None, context=None):
    client, agent, _ = setup
    requests, events = [], []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, stream=streams[len(requests) - 1])

    async def receive(event):
        events.append(event)
        if hook:
            await hook(event)

    async def execute():
        return await client.app.state.agent_runtime.run(
            RuntimeRequest(
                agent["id"],
                input,
                history or [],
                limits or CapabilityLimits(),
                context or RuntimeContext(),
            ),
            on_event=receive,
            transport=httpx.MockTransport(handler),
        )

    result = asyncio.run(execute())
    assert events[0].type == "run_start"
    assert events[-1].type == "run_end"
    assert len([e for e in events if e.type == "run_end"]) == 1
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))
    assert {e.run_id for e in events} == {result.run_id}
    for prefix, end in (("model_start", "model_end"), ("tool_start", "tool_result")):
        starts, ends = [e for e in events if e.type == prefix], [e for e in events if e.type == end]
        assert [e.call_id for e in starts] == [e.call_id for e in ends]
        assert [e.round for e in starts] == [e.round for e in ends]
    return result, requests, events


def skill(setup, content="完整指令：先查询时间，再解释结果。", name="writing"):
    client, agent, data = setup
    folder = client.app.state.skill_store.root / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: 整理文稿\n---\n{content}")
    client.get("/api/skills")
    data["skill_ids"] = [name]
    assert client.put(f"/api/agents/{agent['id']}", json=data).status_code == 200
    return folder


def test_loop_preserves_text_context_usage_events_and_no_chat_writes(setup, caplog):
    caplog.set_level(logging.INFO, logger="app.services.agent_runtime")
    streams = [
        tool_stream(
            [("local__current_time", {})],
            "查询前文",
            usage={"prompt_tokens": 31, "completion_tokens": 17, "total_tokens": 48},
        ),
        normal("查询后文"),
    ]
    result, requests, events = run(
        setup, streams, history=[{"role": "assistant", "content": "历史"}]
    )
    assert result.status == "completed" and result.content == "查询前文查询后文"
    assert requests[0]["messages"] == [
        {"role": "system", "content": "系统指令"},
        {"role": "assistant", "content": "历史"},
        {"role": "user", "content": "用户问题"},
    ]
    second = requests[1]["messages"]
    assert second[-2]["content"] == "查询前文"
    assert second[-1]["tool_call_id"] == second[-2]["tool_calls"][0]["id"]
    assert json.loads(second[-1]["content"])["data"]["timezone"] == "Asia/Shanghai"
    ends = [e for e in events if e.type == "model_end"]
    assert ends[0].data["usage"]["total_tokens"] == 48 and ends[1].data["usage"] is None
    assert all(e.data["duration_ms"] >= 0 for e in ends)
    assert "查询前文" not in caplog.text and result.run_id in caplog.text
    assert all(s.closed for s in streams)
    with setup[0].app.state.session_factory() as session:
        assert session.query(ChatGeneration).count() == session.query(ChatMessage).count() == 0


def test_skill_catalog_lazy_load_then_tools(setup, caplog):
    instruction = "PRIVATE_SKILL_INSTRUCTIONS 请用时间工具核实再回答。"
    skill(setup, instruction)
    result, requests, events = run(
        setup,
        [
            tool_stream([("load_skill", {"skill_id": "writing"})], "读取说明"),
            tool_stream([("local__current_time", {})], "查询时间"),
            normal("处理完成"),
        ],
    )
    assert result.content == "读取说明查询时间处理完成" and result.status == "completed"
    assert instruction not in json.dumps(requests[0], ensure_ascii=False)
    assert "writing" in requests[0]["messages"][0]["content"]
    assert json.loads(requests[1]["messages"][-1]["content"])["instructions"] == instruction
    assert instruction in json.dumps(requests[2], ensure_ascii=False)
    assert instruction not in caplog.text + json.dumps([asdict(e) for e in events])
    assert any(e.type == "tool_result" and e.data["tool_kind"] == "skill" for e in events)


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("disabled", "skill_disabled"),
        ("unbound", "permission_denied"),
        ("missing", "skill_unavailable"),
        ("invalid", "skill_unavailable"),
        ("large", "skill_too_large"),
        ("symlink", "skill_unavailable"),
    ],
)
def test_skill_rechecks_and_does_not_truncate(setup, mutation, expected, tmp_path):
    folder = skill(setup)
    client, agent, data = setup

    async def change(event):
        if event.type != "tool_start":
            return
        if mutation == "disabled":
            client.patch("/api/skills/writing", json={"enabled": False})
        elif mutation == "unbound":
            client.put(f"/api/agents/{agent['id']}", json={**data, "skill_ids": []})
        elif mutation == "missing":
            (folder / "SKILL.md").unlink()
        elif mutation == "invalid":
            (folder / "SKILL.md").write_bytes(b"bad")
        elif mutation == "large":
            (folder / "SKILL.md").write_text(
                "---\nname: writing\ndescription: 大说明\n---\n" + "x" * 140000
            )
        else:
            outside = tmp_path / "private.txt"
            outside.write_text("SECRET_OUTSIDE")
            (folder / "SKILL.md").unlink()
            (folder / "SKILL.md").symlink_to(outside)

    result, requests, events = run(
        setup,
        [
            tool_stream([("load_skill", {"skill_id": "writing"})]),
            normal("无法加载，继续处理"),
        ],
        hook=change,
    )
    error = json.loads(requests[-1]["messages"][-1]["content"])
    assert error["code"] == expected and result.status == "completed"
    assert "instructions" not in error and "SECRET_OUTSIDE" not in json.dumps(requests)
    assert next(e for e in events if e.type == "tool_result").data["status"] == "failed"


@pytest.mark.parametrize(
    "arguments,code",
    [
        ({"skill_id": "../private"}, "permission_denied"),
        ({"skill_id": "unbound"}, "permission_denied"),
        ({"path": "/etc/passwd"}, "invalid_arguments"),
        ({"skill_id": "writing", "path": "private"}, "invalid_arguments"),
    ],
)
def test_skill_cannot_accept_paths_or_unbound_ids(setup, arguments, code):
    skill(setup)
    _, requests, _ = run(setup, [tool_stream([("load_skill", arguments)]), normal()])
    assert json.loads(requests[1]["messages"][-1]["content"])["code"] == code


def test_limits_only_narrow_all_kinds_and_no_load_tool_without_skills(setup):
    skill(setup)
    limits = CapabilityLimits(
        tools=frozenset({"shell", "not_real"}),
        skills=frozenset(),
        mcp_servers=frozenset({"not_bound"}),
    )
    result, requests, events = run(
        setup,
        [
            tool_stream(
                [
                    ("local__shell", {"command": "echo forbidden"}),
                    ("load_skill", {"skill_id": "writing"}),
                    ("local__current_time", {}),
                ]
            ),
            normal("权限不足"),
        ],
        limits=limits,
    )
    assert "tools" not in requests[0] and "writing" not in requests[0]["messages"][0]["content"]
    assert result.status == "completed"
    assert all(
        json.loads(m["content"])["code"] == "permission_denied"
        for m in requests[-1]["messages"]
        if m["role"] == "tool"
    )
    assert len([e for e in events if e.type == "tool_result"]) == 3


@pytest.mark.parametrize("kind", ["disabled", "unbound", "invalid", "unknown"])
def test_tool_permission_rechecked_and_errors_return_to_model(setup, kind):
    client, agent, _ = setup

    async def change(event):
        if event.type != "tool_start":
            return
        if kind == "disabled":
            client.patch("/api/tools/current_time", json={"enabled": False})
        elif kind == "unbound":
            with client.app.state.session_factory() as session:
                session.execute(delete(AgentTool).where(AgentTool.agent_id == agent["id"]))
                session.commit()

    name = "untrusted_" + MODEL["api_key"] if kind == "unknown" else "local__current_time"
    arguments = {"timezone": 123} if kind == "invalid" else {}
    result, requests, events = run(setup, [tool_stream([(name, arguments)]), normal()], hook=change)
    expected = {
        "disabled": "tool_disabled",
        "unbound": "permission_denied",
        "invalid": "invalid_arguments",
        "unknown": "permission_denied",
    }[kind]
    assert json.loads(requests[-1]["messages"][-1]["content"])["code"] == expected
    assert result.status == "completed" and MODEL["api_key"] not in json.dumps(
        [asdict(e) for e in events]
    )


def test_round_limit_is_distinct_and_chat_keeps_partial(setup):
    client, agent, data = setup
    client.put(f"/api/agents/{agent['id']}", json={**data, "max_rounds": 1})
    result, requests, _ = run(setup, [tool_stream([("local__current_time", {})], "先查")])
    assert result.status == "limit_reached" and result.content == "先查" and len(requests) == 1
    client.app.state.chat_store.transport = httpx.MockTransport(
        lambda _: httpx.Response(200, stream=tool_stream([("local__current_time", {})], "先查"))
    )
    conversation = create(client)
    send(client, conversation)
    detail = finished(client, conversation)
    assert detail["generation"]["status"] == "limit_reached"
    assert detail["messages"][-1]["status"] == "failed"
    assert "轮数" in detail["generation"]["error"]


@pytest.mark.parametrize("phase", ["before", "model", "tool", "between"])
def test_cancel_independent_signal_and_event_pairing(setup, phase):
    client, agent, _ = setup
    events, requests = [], []
    cancellation = Cancellation()
    stream = (
        Stream([frame("部分")], threading.Event())
        if phase == "model"
        else tool_stream([("local__current_time", {}), ("local__current_time", {})], "前文")
    )

    async def receive(event):
        events.append(event)
        if (
            (phase == "model" and event.type == "text_delta")
            or (phase == "tool" and event.type == "tool_start")
            or (phase == "between" and event.type == "tool_result")
        ):
            cancellation.cancel()

    def handler(request):
        requests.append(request)
        return httpx.Response(200, stream=stream)

    async def execute():
        if phase == "before":
            cancellation.cancel()
        return await asyncio.wait_for(
            client.app.state.agent_runtime.run(
                RuntimeRequest(agent["id"], "问题"),
                cancellation,
                receive,
                transport=httpx.MockTransport(handler),
            ),
            3,
        )

    result = asyncio.run(execute())
    assert result.status == "cancelled"
    assert len(requests) == (0 if phase == "before" else 1)
    if phase != "before":
        assert stream.closed
    assert len([e for e in events if e.type == "run_end"]) == 1
    assert len([e for e in events if e.type == "tool_start"]) <= 1
    for start, end in (("model_start", "model_end"), ("tool_start", "tool_result")):
        assert [e.call_id for e in events if e.type == start] == [
            e.call_id for e in events if e.type == end
        ]


MCP_PROGRAM = r"""
import json, os, sys, time
from pathlib import Path
Path(sys.argv[1]).write_text(str(os.getpid()))
for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if "id" not in request:
        continue
    if method == "initialize":
        result = {"protocolVersion": request["params"]["protocolVersion"],
                  "serverInfo": {"name": "test", "version": "1"}, "capabilities": {"tools": {}}}
    elif method == "tools/list":
        result = {"tools": [{"name": "current_time",
            "description": "MCP_DESCRIPTION " + os.environ["TOKEN"],
            "inputSchema": {"type": "object", "properties": {"wait": {"type": "boolean"}},
                            "additionalProperties": False}}]}
    else:
        Path(sys.argv[1] + ".called").write_text("called")
        if request["params"]["arguments"].get("wait"):
            time.sleep(60)
        result = {"content": [{"type": "text", "text": "RAW_MCP_RESULT " + os.environ["TOKEN"]}]}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
Path(sys.argv[1] + ".closed").write_text("closed")
"""


def mcp(setup, tmp_path):
    client, agent, data = setup
    script = tmp_path / "runtime_mcp.py"
    script.write_text(MCP_PROGRAM)
    pidfile = tmp_path / "mcp.pid"
    response = client.post(
        "/api/mcp",
        json={
            "name": "runtime_mcp",
            "command": sys.executable,
            "args": [str(script), str(pidfile)],
            "env": {"TOKEN": "MCP_PRIVATE_SECRET"},
        },
    )
    assert response.status_code == 201, response.text
    server = response.json()
    client.patch(f"/api/mcp/{server['id']}", json={"enabled": True})
    data["mcp_server_ids"] = [server["id"]]
    assert client.put(f"/api/agents/{agent['id']}", json=data).status_code == 200
    return server, pidfile


def assert_dead(pidfile):
    pid = int(pidfile.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_mcp_fresh_discovery_namespacing_results_and_cleanup(setup, tmp_path, caplog):
    server, pidfile = mcp(setup, tmp_path)
    name = tool_name("mcp", server["id"], "current_time")
    result, requests, events = run(setup, [tool_stream([(name, {})]), normal("MCP 已完成")])
    assert result.status == "completed"
    names = [tool["function"]["name"] for tool in requests[0]["tools"]]
    assert names == ["local__current_time", name]
    assert "RAW_MCP_RESULT" in requests[1]["messages"][-1]["content"]
    assert (
        "MCP_PRIVATE_SECRET" not in json.dumps(requests + [asdict(e) for e in events]) + caplog.text
    )
    tool_event = next(event for event in events if event.type == "tool_result")
    assert tool_event.data["summary"].startswith("RAW_MCP_RESULT")
    assert "MCP_PRIVATE_SECRET" not in json.dumps(tool_event.data)
    assert pidfile.with_suffix(".pid.closed").exists()
    assert_dead(pidfile)


@pytest.mark.parametrize("end", ["cancel", "error", "limit", "direct"])
def test_mcp_cleanup_all_exit_paths(setup, tmp_path, end):
    server, pidfile = mcp(setup, tmp_path)
    client, agent, data = setup
    name = tool_name("mcp", server["id"], "current_time")
    if end == "limit":
        client.put(f"/api/agents/{agent['id']}", json={**data, "max_rounds": 1})
    if end == "cancel":
        cancellation, events = Cancellation(), []

        async def receive(event):
            events.append(event)

        async def stop_when_called():
            while not pidfile.with_suffix(".pid.called").exists():
                await asyncio.sleep(0.01)
            cancellation.cancel()

        async def execute():
            stopper = asyncio.create_task(stop_when_called())
            try:
                return await asyncio.wait_for(
                    client.app.state.agent_runtime.run(
                        RuntimeRequest(agent["id"], "问题"),
                        cancellation,
                        receive,
                        transport=httpx.MockTransport(
                            lambda _: httpx.Response(
                                200, stream=tool_stream([(name, {"wait": True})])
                            )
                        ),
                    ),
                    4,
                )
            finally:
                stopper.cancel()
                await asyncio.gather(stopper, return_exceptions=True)

        started = time.monotonic()
        result = asyncio.run(execute())
        assert time.monotonic() - started < 4
        assert result.status == "cancelled"
        assert next(e for e in events if e.type == "tool_result").data["status"] == "cancelled"
    else:
        streams = (
            [Stream([b"data: invalid\n\n"])]
            if end == "error"
            else [tool_stream([(name, {})]) if end == "limit" else normal()]
        )
        result, _, _ = run(setup, streams)
        assert (
            result.status
            == {"error": "failed", "limit": "limit_reached", "direct": "completed"}[end]
        )
    assert_dead(pidfile)


def test_mcp_rechecks_disabled_and_run_tool_restriction(setup, tmp_path):
    server, pidfile = mcp(setup, tmp_path)
    name = tool_name("mcp", server["id"], "current_time")

    async def disable(event):
        if event.type == "tool_start":
            setup[0].patch(f"/api/mcp/{server['id']}", json={"enabled": False})

    _, requests, _ = run(setup, [tool_stream([(name, {})]), normal()], hook=disable)
    assert json.loads(requests[1]["messages"][-1]["content"])["code"] == "tool_disabled"
    assert not pidfile.with_suffix(".pid.called").exists()
    assert_dead(pidfile)
    setup[0].patch(f"/api/mcp/{server['id']}", json={"enabled": True})
    _, requests, _ = run(
        setup, [tool_stream([(name, {})]), normal()], limits=CapabilityLimits(mcp_tools=frozenset())
    )
    assert [tool["function"]["name"] for tool in requests[0]["tools"]] == ["local__current_time"]
    assert json.loads(requests[1]["messages"][-1]["content"])["code"] == "permission_denied"
    assert_dead(pidfile)


def test_sse_disconnect_signals_runtime_cancel(setup):
    from app.api.chat import events as subscribe
    from app.schemas.chat import ChatInput

    client, _, _ = setup
    store = client.app.state.chat_store
    stream = Stream([frame("部分正文")], threading.Event())
    store.transport = httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))

    async def execute():
        from uuid import uuid4

        conversation = store.create()
        generation = store.start(
            conversation.id, ChatInput(content="问题", request_id=str(uuid4()))
        )

        async def connected():
            return False

        request = SimpleNamespace(app=client.app, is_disconnected=connected)
        response = await subscribe(conversation.id, generation.id, request)
        iterator = response.body_iterator
        await anext(iterator)
        while not stream.closed and store.snapshot(conversation.id, generation.id).message is None:
            await asyncio.sleep(0.01)
        await iterator.aclose()
        task = store.tasks.get(generation.id)
        if task:
            await asyncio.wait_for(task, 3)
        assert store.snapshot(conversation.id, generation.id).status == "cancelled"
        assert stream.closed

    asyncio.run(execute())


def test_shell_cancellation_stops_pending_side_effect(setup):
    from app.services.tool_shell import available

    if not available():
        pytest.skip("需要 macOS sandbox-exec")
    client, agent, data = setup
    client.patch("/api/tools/shell", json={"enabled": True})
    client.put(f"/api/agents/{agent['id']}", json={**data, "tool_ids": ["shell"]})
    root = client.app.state.tool_runtime.root
    cancellation = Cancellation()
    events = []

    async def receive(event):
        events.append(event)

    async def stop_after_start():
        while not (root / "started.txt").exists():
            await asyncio.sleep(0.01)
        cancellation.cancel()

    async def execute():
        stopper = asyncio.create_task(stop_after_start())
        try:
            return await asyncio.wait_for(
                client.app.state.agent_runtime.run(
                    RuntimeRequest(agent["id"], "问题"),
                    cancellation,
                    receive,
                    transport=httpx.MockTransport(
                        lambda _: httpx.Response(
                            200,
                            stream=tool_stream(
                                [
                                    (
                                        "local__shell",
                                        {
                                            "command": (
                                                "echo yes > started.txt; "
                                                "sleep 30; echo no > late.txt"
                                            ),
                                            "timeout_seconds": 30,
                                        },
                                    ),
                                ]
                            ),
                        )
                    ),
                ),
                5,
            )
        finally:
            stopper.cancel()
            await asyncio.gather(stopper, return_exceptions=True)

    result = asyncio.run(execute())
    assert result.status == "cancelled"
    assert not (root / "late.txt").exists()
    assert not client.app.state.tool_runtime.lock.locked()
    assert next(e for e in events if e.type == "tool_result").data["status"] == "cancelled"


def test_file_cancellation_before_replace_preserves_original(setup, monkeypatch):
    from app.services import tool_files

    client, agent, data = setup
    client.patch("/api/tools/file", json={"enabled": True})
    client.put(f"/api/agents/{agent['id']}", json={**data, "tool_ids": ["file"]})
    root = client.app.state.tool_runtime.root
    root.mkdir()
    target = root / "original.txt"
    target.write_text("original")
    cancellation = Cancellation()
    original = tool_files.os.fsync

    def cancel_after_flush(fd):
        original(fd)
        cancellation.cancel()

    monkeypatch.setattr(tool_files.os, "fsync", cancel_after_flush)

    async def execute():
        return await client.app.state.agent_runtime.run(
            RuntimeRequest(agent["id"], "写文件"),
            cancellation,
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    stream=tool_stream(
                        [
                            (
                                "local__file",
                                {
                                    "operation": "write",
                                    "path": "original.txt",
                                    "content": "replaced",
                                },
                            ),
                        ]
                    ),
                )
            ),
        )

    result = asyncio.run(execute())
    assert result.status == "cancelled" and target.read_text() == "original"
    assert list(root.iterdir()) == [target]


def test_cancel_during_mcp_initialization_cleans_process(setup, tmp_path):
    _, pidfile = mcp(setup, tmp_path)
    program = tmp_path / "runtime_mcp.py"
    program.write_text(
        program.read_text().replace(
            'if method == "initialize":', 'if method == "initialize":\n        time.sleep(60)'
        )
    )
    client, agent, _ = setup
    cancellation, events = Cancellation(), []

    async def receive(event):
        events.append(event)

    async def stop_after_start():
        while not pidfile.exists():
            await asyncio.sleep(0.01)
        cancellation.cancel()

    async def execute():
        stopper = asyncio.create_task(stop_after_start())
        try:
            return await asyncio.wait_for(
                client.app.state.agent_runtime.run(
                    RuntimeRequest(agent["id"], "问题"), cancellation, receive
                ),
                4,
            )
        finally:
            stopper.cancel()
            await asyncio.gather(stopper, return_exceptions=True)

    result = asyncio.run(execute())
    assert result.status == "cancelled"
    assert [event.type for event in events] == ["run_start", "run_end"]
    assert_dead(pidfile)


@pytest.mark.parametrize("ids", [["same", "same"], [None]])
def test_model_invalid_call_identifiers_never_execute(setup, ids):
    calls = [
        {
            "index": index,
            "id": value,
            "function": {"name": "local__current_time", "arguments": "{}"},
        }
        for index, value in enumerate(ids)
    ]
    data = (
        "data: "
        + json.dumps(
            {
                "choices": [
                    {"index": 0, "delta": {"tool_calls": calls}, "finish_reason": "tool_calls"}
                ]
            }
        )
        + "\n\n"
    ).encode()
    result, _, events = run(setup, [Stream([data, b"data: [DONE]\n\n"])])
    assert result.status == "failed"
    assert not any(e.type == "tool_start" for e in events)


def test_context_guard_accounts_for_full_skill_result(setup):
    client, _, data = setup
    # 首轮目录能容纳；加载后的正文不能容纳，必须明确结束而非丢弃指令。
    client.put(f"/api/models/{data['model_id']}", json={**MODEL, "context_length": 4096})
    skill(setup, "Instruction body. " * 1000)
    result, requests, events = run(setup, [tool_stream([("load_skill", {"skill_id": "writing"})])])
    assert result.status == "failed" and "上下文容量" in result.reason and len(requests) == 1
    assert any(e.type == "tool_result" and e.data["status"] == "completed" for e in events)


def test_context_compression_batches_persists_boundary_and_counts_model_calls(setup):
    client, _, data = setup
    client.put(
        f"/api/models/{data['model_id']}",
        json={**MODEL, "context_length": 4096},
    )
    client.put(
        f"/api/agents/{setup[1]['id']}",
        json={
            **data,
            "compression_trigger_ratio": 0.5,
            "compression_keep_recent_turns": 1,
            "compression_summary_target_tokens": 1000,
        },
    )
    history = [
        {"role": role, "content": f"{label}-" + "较早内容" * 220, "sequence": sequence}
        for sequence, (role, label) in enumerate(
            [
                ("user", "问一"),
                ("assistant", "答一"),
                ("user", "问二"),
                ("assistant", "答二"),
                ("user", "最近问"),
                ("assistant", "最近答"),
            ],
            1,
        )
    ]
    saved = []
    context = RuntimeContext(
        save_summary=lambda new, boundary, old, old_boundary: saved.append(
            (new, boundary, old, old_boundary)
        )
    )
    result, requests, events = run(
        setup,
        [normal("阶段摘要"), normal("合并摘要"), normal("最终回答")],
        history=history,
        context=context,
    )
    assert result.status == "completed" and result.content == "最终回答"
    assert saved == [("合并摘要", 4, None, None)]
    assert len(requests) == 3
    assert requests[0]["max_tokens"] < 1000  # 小窗口会动态降低摘要目标。
    assert requests[-1]["messages"][1]["content"].endswith("合并摘要")
    assert "问一" not in json.dumps(requests[-1]["messages"], ensure_ascii=False)
    assert "最近问" in json.dumps(requests[-1]["messages"], ensure_ascii=False)
    purposes = [e.data.get("purpose") for e in events if e.type == "model_end"]
    assert purposes == ["context_compression", "context_compression", "agent_loop"]
    success = next(e for e in events if e.type == "compression_success")
    assert success.data["processed_message_count"] == 4
    assert success.data["estimated_tokens_after"] < success.data["estimated_tokens_before"]
    assert success.data["estimation"] is True


def test_compression_failure_uses_request_only_fallback_without_advancing_boundary(setup):
    client, _, data = setup
    client.put(
        f"/api/models/{data['model_id']}",
        json={**MODEL, "context_length": 4096},
    )
    client.put(
        f"/api/agents/{setup[1]['id']}",
        json={**data, "compression_trigger_ratio": 0.5, "compression_keep_recent_turns": 1},
    )
    history = [
        {
            "role": "user" if sequence % 2 else "assistant",
            "content": "历史" * 700,
            "sequence": sequence,
        }
        for sequence in range(1, 7)
    ]
    saved = []
    broken = Stream([b"data: invalid\n\n"])
    result, requests, events = run(
        setup,
        [broken, normal("备用后继续")],
        history=history,
        context=RuntimeContext(
            save_summary=lambda *values: saved.append(values),
        ),
    )
    assert result.status == "completed" and not saved
    assert any(e.type == "compression_failure" for e in events)
    fallback = next(e for e in events if e.type == "context_fallback")
    assert fallback.data["processed_message_count"] > 0
    assert len(requests[-1]["messages"]) < len(history) + 2


def test_disabled_compression_reports_overflow_without_model_call(setup):
    client, _, data = setup
    client.put(
        f"/api/models/{data['model_id']}",
        json={**MODEL, "context_length": 4096},
    )
    client.put(
        f"/api/agents/{setup[1]['id']}",
        json={**data, "auto_compress": False},
    )
    history = [
        {"role": "user", "content": "历史" * 2000},
        {"role": "assistant", "content": "回答" * 2000},
    ]
    result, requests, _ = run(setup, [], history=history)
    assert result.status == "failed" and "自动压缩已关闭" in result.reason
    assert not requests


def test_external_caller_cancellation_waits_for_cleanup(setup):
    client, agent, _ = setup
    events = []
    stream = Stream([frame("部分")], threading.Event())
    started = asyncio.Event()

    async def receive(event):
        events.append(event)
        if event.type == "text_delta":
            started.set()

    async def execute():
        task = asyncio.create_task(
            client.app.state.agent_runtime.run(
                RuntimeRequest(agent["id"], "问题"),
                on_event=receive,
                transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)),
            )
        )
        await started.wait()
        task.cancel()
        return await asyncio.wait_for(task, 3)

    result = asyncio.run(execute())
    assert result.status == "cancelled" and stream.closed
    assert events[-1].type == "run_end"


def test_mcp_schema_external_ref_cannot_read_files(setup, tmp_path, monkeypatch):
    from app.services.agent_runtime import Capabilities

    server, pidfile = mcp(setup, tmp_path)
    name = tool_name("mcp", server["id"], "current_time")
    original = Capabilities.add

    def external_schema(self, tool, kind, resource, raw, description, schema):
        if kind == "mcp":
            schema = {"type": "object", "$ref": "file:///does-not-exist-private-schema"}
        return original(self, tool, kind, resource, raw, description, schema)

    monkeypatch.setattr(Capabilities, "add", external_schema)
    _, requests, _ = run(setup, [tool_stream([(name, {})]), normal()])
    assert not json.loads(requests[1]["messages"][-1]["content"])["success"]
    assert not pidfile.with_suffix(".pid.called").exists()
    assert_dead(pidfile)


def test_known_key_echo_cannot_leak_across_tool_rounds(setup):
    first, second = MODEL["api_key"][:8], MODEL["api_key"][8:]
    result, requests, events = run(
        setup,
        [
            tool_stream([("local__current_time", {})], "前" + first),
            normal(second + "后"),
        ],
    )
    assert result.content == "前[已隐藏]后"
    assert MODEL["api_key"] not in json.dumps([asdict(e) for e in events])
    assert MODEL["api_key"] not in json.dumps(requests)


@pytest.mark.parametrize("arguments", ['{"timezone":NaN}', '{"timezone":"UTC","timezone":"UTC"}'])
def test_invalid_json_parameters_are_tool_errors(setup, arguments):
    result, requests, _ = run(setup, [tool_stream([("local__current_time", arguments)]), normal()])
    assert result.status == "completed"
    assert json.loads(requests[1]["messages"][-1]["content"])["code"] == "invalid_arguments"


def test_mcp_binding_revoked_during_preparation_does_not_start_process(
    setup, tmp_path, monkeypatch
):
    from app.models import AgentMcp

    _, pidfile = mcp(setup, tmp_path)
    client, agent, _ = setup
    tools = client.app.state.tool_runtime
    original = tools.view

    def revoke_during_prepare(*args):
        with client.app.state.session_factory() as session:
            session.execute(delete(AgentMcp).where(AgentMcp.agent_id == agent["id"]))
            session.commit()
        return original(*args)

    monkeypatch.setattr(tools, "view", revoke_during_prepare)
    result, requests, _ = run(setup, [normal()])
    assert result.status == "completed" and not pidfile.exists()
    assert [tool["function"]["name"] for tool in requests[0]["tools"]] == ["local__current_time"]


def test_stream_replay_buffer_keeps_lifecycle_pairs_when_text_rolls_over():
    from app.services.agent_runtime import RuntimeEvent
    from app.services.chat import RunEventBuffer

    buffer = RunEventBuffer()
    buffer.append(RuntimeEvent("run", 1, "run_start"))
    buffer.append(RuntimeEvent("run", 2, "model_start", 1, "model"))
    for sequence in range(3, 1500):
        buffer.append(RuntimeEvent("run", sequence, "text_delta", 1, "model", {"content": "a"}))
    buffer.append(RuntimeEvent("run", 1500, "model_end", 1, "model"))
    buffer.append(RuntimeEvent("run", 1501, "run_end"))
    events = buffer.since(0)
    assert len(buffer.text) == 512
    assert [event.type for event in events if event.type != "text_delta"] == [
        "run_start",
        "model_start",
        "model_end",
        "run_end",
    ]
    assert [event.sequence for event in events] == sorted(event.sequence for event in events)
    assert buffer.since(1500)[0].type == "run_end"
