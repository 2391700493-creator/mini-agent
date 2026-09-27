import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.models import McpSecret
from app.services.mcp_connection import ProbeResult, probe

SECRET = "test-sensitive-value-9381"
SERVER = r"""
import json, os, sys, time, subprocess, signal
from pathlib import Path
mode = sys.argv[1]
pidfile = os.environ.get("PIDFILE")
if pidfile:
    Path(pidfile).write_text(str(os.getpid()))
if mode == "child":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    Path(pidfile + ".child").write_text(str(child.pid))
    time.sleep(60)
if mode == "exit":
    print(os.environ.get("TOKEN", ""), file=sys.stderr)
    sys.exit(7)
if mode == "timeout":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(60)
if mode == "bad":
    print("not json " + os.environ.get("TOKEN", ""), flush=True)
    time.sleep(60)
initialized = False
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "notifications/initialized":
        initialized = True
        continue
    if method == "tools/call":
        raise RuntimeError("must never execute tools")
    if "id" not in message:
        continue
    result = {}
    if mode == "error":
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "error": {
            "code": -32001, "message": os.environ.get("TOKEN", "secret")}}), flush=True)
        continue
    if method == "initialize":
        version = "bad" if mode == "version" else message["params"]["protocolVersion"]
        result = {"protocolVersion": version,
                  "serverInfo": {"name": "fixture", "version": "1"},
                  "capabilities": {} if mode == "no-capability" else {"tools": {}}}
    if method == "tools/list":
        assert initialized
        if mode == "empty":
            result = {"tools": []}
        elif mode == "shape":
            schema = {"type": "object", "required": 5}
            result = {"tools": [{"name": "wrong", "inputSchema": schema}]}
        else:
            name = "second" if message.get("params", {}).get("cursor") else "first"
            description = "Find " + os.environ.get("TOKEN", "files")
            result = {"tools": [{"name": name, "description": description,
                "inputSchema": {"type": "object", "properties": {
                    "path": {"type": "string", "description": "文件路径"}},
                    "required": ["path"]}}]}
            if name == "first": result["nextCursor"] = "next"
            if mode == "cursor": result["nextCursor"] = "next"
        if mode == "args":
            assert sys.argv[2:] == ["with spaces", "$(touch never)", "", "--last"]
            assert "BACKEND_SECRET" not in os.environ
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
if pidfile:
    Path(pidfile + ".closed").write_text("closed")
"""


@pytest.fixture
def server_script(tmp_path):
    path = tmp_path / "server.py"
    path.write_text(SERVER)
    return path


def config(server_script, mode="success", **changes):
    return {
        "name": "本地测试",
        "description": "测试工具",
        "command": sys.executable,
        "args": [str(server_script), mode],
        "env": {"TOKEN": SECRET},
        **changes,
    }


def create(client, data):
    response = client.post("/api/mcp", json=data)
    assert response.status_code == 201, response.text
    return response.json()


def test_crud_encryption_restart_agent_filter(client, migrated_database, server_script):
    data = config(server_script)
    server = create(client, data)
    assert server["status"] == "untested" and server["message"] == "未测试"
    assert server["tool_count"] is None and server["tools"] == []
    assert server["env"] == {"TOKEN": "••••••••"}
    assert SECRET not in json.dumps(server)
    with client.app.state.session_factory() as session:
        ciphertext = session.scalar(select(McpSecret.ciphertext))
        assert SECRET not in ciphertext
        assert client.app.state.mcp_store.for_agent(session) == []
    url = f"/api/mcp/{server['id']}"
    assert client.patch(url, json={"enabled": True}).json()["enabled"]
    with client.app.state.session_factory() as session:
        enabled = client.app.state.mcp_store.for_agent(session)
        assert enabled[0].env["TOKEN"].get_secret_value() == SECRET
        assert SECRET not in repr(enabled)
    with TestClient(
        create_app(
            migrated_database,
            key_path=migrated_database.with_suffix(".key"),
            skills_root=migrated_database.parent / "skills",
            tool_root=migrated_database.parent / "workspace",
        )
    ) as reopened:
        assert reopened.get(url).json()["enabled"]
        assert reopened.get(url).headers["cache-control"] == "no-store"
    saved = client.put(url, json={**data, "env": {"TOKEN": None}})
    assert saved.status_code == 200
    with client.app.state.session_factory() as session:
        assert client.app.state.mcp_store.environment(session, server["id"])["TOKEN"] == SECRET
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
    with client.app.state.session_factory() as session:
        assert session.scalar(select(McpSecret)) is None


def test_json_import_creates_and_updates_while_preserving_existing_secret(client, server_script):
    created_config = {
        "mcpServers": {
            "JSON Server": {
                "description": "从 JSON 导入",
                "command": sys.executable,
                "args": [str(server_script), "success"],
                "env": {"TOKEN": SECRET},
            }
        }
    }
    response = client.post("/api/mcp/import", json={"configuration": json.dumps(created_config)})
    assert response.status_code == 201
    server = response.json()
    assert server["name"] == "JSON Server"
    assert server["env"] == {"TOKEN": "••••••••"}

    updated_config = {
        "mcpServers": {
            "改名后的 Server": {
                "command": sys.executable,
                "args": [str(server_script), "empty"],
                "env": {"TOKEN": None},
            }
        }
    }
    response = client.put(
        f"/api/mcp/{server['id']}/import",
        json={"configuration": json.dumps(updated_config)},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["name"] == "改名后的 Server"
    assert updated["status"] == "stale"
    with client.app.state.session_factory() as session:
        assert client.app.state.mcp_store.environment(session, server["id"])["TOKEN"] == SECRET


def test_success_stale_history_and_environment_changes(client, server_script):
    data = config(server_script)
    server = create(client, data)
    url = f"/api/mcp/{server['id']}"
    tested = client.post(url + "/test", json={}).json()
    assert tested["status"] == "success" and tested["tool_count"] == 2
    assert not tested["enabled"] and not tested["testing"]
    assert tested["tools"][0]["input_schema"]["required"] == ["path"]
    assert SECRET not in json.dumps(tested)
    unchanged = client.put(url, json={**data, "name": "改名", "env": {"TOKEN": None}}).json()
    assert unchanged["status"] == "success"
    changed = client.put(url, json={**data, "env": {"TOKEN": "replacement"}}).json()
    assert changed["status"] == "stale" and changed["tool_count"] == 2
    assert changed["message"] == "配置已变更，待重新测试"
    client.put(url, json=config(server_script, "exit"))
    failed = client.post(url + "/test", json={}).json()
    assert failed["status"] == "error" and failed["tool_count"] == 2
    assert failed["last_success_at"] == tested["last_success_at"]
    assert "提前退出" in failed["message"]
    assert SECRET not in json.dumps(failed)
    removed = client.put(url, json={**data, "env": {}}).json()
    assert removed["env"] == {} and removed["status"] == "stale"


@pytest.mark.parametrize(
    "mode,code",
    [
        ("success", "success"),
        ("empty", "success"),
        ("no-capability", "success"),
        ("exit", "exited"),
        ("timeout", "timeout"),
        ("bad", "incompatible"),
        ("version", "incompatible"),
        ("shape", "incompatible"),
        ("cursor", "incompatible"),
        ("error", "server_error"),
        ("child", "timeout"),
    ],
)
def test_real_stdio_outcomes_and_cleanup(server_script, tmp_path, mode, code, caplog):
    pidfile = tmp_path / "pid"
    result = probe(
        sys.executable,
        [str(server_script), mode],
        {"TOKEN": SECRET, "PIDFILE": str(pidfile)},
        timeout=0.5,
    )
    assert result.code == code
    assert SECRET not in repr(result) + caplog.text
    pid = int(pidfile.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    if mode in {"success", "empty", "no-capability"}:
        assert pidfile.with_suffix(".closed").exists()
    if mode in {"empty", "no-capability"}:
        assert result.message == "连接成功，未发现工具"
    if mode == "child":
        child = int(Path(str(pidfile) + ".child").read_text())
        # 被收养的子进程可能短暂处于待回收状态。
        for _ in range(50):
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        else:
            pytest.fail("测试子进程未清理")


def test_missing_permission_and_direct_arguments(server_script, monkeypatch, tmp_path):
    assert probe("/not-present-mini-agent-mcp", [], {}).code == "command_not_found"
    assert probe(str(server_script), [], {}).code == "start_failed"
    monkeypatch.setenv("BACKEND_SECRET", SECRET)
    assert probe(
        sys.executable,
        [str(server_script), "args", "with spaces", "$(touch never)", "", "--last"],
        {},
    ).success
    assert not (tmp_path / "never").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"command": "https://example.test/mcp"},
        {"command": " "},
        {"command": "a\x00b"},
        {"args": "a b"},
        {"args": [3]},
        {"env": {"BAD-NAME": SECRET}},
        {"env": {"TOKEN": "••••••••"}},
        {"env": {"TOKEN": "********"}},
        {"env": {"TOKEN": None}},
        {"env": {"TOKEN": 5}},
        {"unexpected": SECRET},
    ],
)
def test_validation_no_secret_echo(client, server_script, changes):
    response = client.post("/api/mcp", json=config(server_script, **changes))
    assert response.status_code == 422
    assert SECRET not in response.text


def test_missing_key_never_recreated(client, server_script, migrated_database):
    server = create(client, config(server_script))
    key = migrated_database.with_suffix(".key")
    key.unlink()
    response = client.put(
        f"/api/mcp/{server['id']}", json=config(server_script, env={"TOKEN": "new"})
    )
    assert response.status_code == 503 and not key.exists()
    assert SECRET not in response.text


def test_concurrency_busy_visible_and_mutations_rejected(client, server_script, monkeypatch):
    server = create(client, config(server_script))
    url = f"/api/mcp/{server['id']}"
    entered, release = threading.Event(), threading.Event()

    def paused(*args):
        entered.set()
        assert release.wait(5)
        return ProbeResult(True, "success", "连接成功，未发现工具")

    monkeypatch.setattr("app.services.mcp.probe", paused)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(client.post, url + "/test", json={})
        try:
            assert entered.wait(5)
            assert client.get(url).json()["testing"]
            assert client.post(url + "/test", json={}).status_code == 409
            assert client.put(url, json=config(server_script)).status_code == 409
            assert client.patch(url, json={"enabled": True}).status_code == 409
            assert client.delete(url).status_code == 409
        finally:
            release.set()
        assert future.result().status_code == 200
    assert not client.get(url).json()["testing"]


def test_local_origin_and_content_type(client):
    assert (
        client.post("/api/mcp", json={}, headers={"Origin": "https://evil.test"}).status_code == 403
    )
    assert client.post("/api/mcp", content="{}").status_code == 415


def test_short_environment_values_do_not_corrupt_response_fields(client, server_script):
    server = create(client, config(server_script, env={"TOKEN": "name"}))
    response = client.post(f"/api/mcp/{server['id']}/test", json={})
    assert response.status_code == 200
    assert response.json()["tools"][0]["name"] == "first"
    assert response.json()["tools"][0]["description"] == "Find [已隐藏]"


def test_unknown_error_diagnostic_hides_raw_exception(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr("app.services.mcp_connection.subprocess.Popen", fail)
    result = probe("command", [], {"TOKEN": SECRET})
    assert result.code == "unknown"
    assert "阶段：启动" in result.diagnostic
    assert SECRET not in repr(result)
