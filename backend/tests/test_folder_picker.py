import subprocess
from types import SimpleNamespace

import pytest

from app.services import folder_picker


def picker_result(monkeypatch, value, returncode=0):
    monkeypatch.setattr(folder_picker.sys, "platform", "darwin")
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout=value, returncode=returncode)

    monkeypatch.setattr(folder_picker.subprocess, "run", run)
    return calls


def test_native_selection_returns_only_authorized_relative_path(client, monkeypatch):
    runtime = client.app.state.tool_runtime
    runtime.prepare_root()
    selected = runtime.root / "资料 folder"
    selected.mkdir()
    calls = picker_result(monkeypatch, str(selected) + "/\n")
    response = client.post("/api/workspace/folders/choose", json={})
    assert response.status_code == 200
    assert response.json() == {"folder": "资料 folder"}
    args, config = calls[0]
    assert args[:3] == ["/usr/bin/osascript", "-l", "JavaScript"]
    assert args[-1] == str(runtime.root.absolute())
    assert config["timeout"] == 120
    assert config["stderr"] == subprocess.DEVNULL
    assert config["env"] == {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}
    assert "allowsMultipleSelection = false" in args[4]
    assert client.get("/api/chat/conversations").json() == []


def test_native_root_and_cancel_are_distinct(client, monkeypatch):
    runtime = client.app.state.tool_runtime
    runtime.prepare_root()
    picker_result(monkeypatch, str(runtime.root) + "\n")
    assert client.post("/api/workspace/folders/choose", json={}).json() == {"folder": "."}
    picker_result(monkeypatch, "\n")
    assert client.post("/api/workspace/folders/choose", json={}).json() == {"folder": None}


@pytest.mark.parametrize("kind", ["outside", "symlink", "hidden", "traversal", "control"])
def test_native_selection_does_not_expand_permissions(client, monkeypatch, tmp_path, kind):
    runtime = client.app.state.tool_runtime
    runtime.prepare_root()
    outside = tmp_path / "outside-native"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("untouched")
    if kind == "outside":
        selected = str(outside)
    elif kind == "symlink":
        linked = runtime.root / "linked"
        linked.symlink_to(outside)
        selected = str(linked)
    elif kind == "hidden":
        selected = str(runtime.root / ".hidden")
    elif kind == "traversal":
        selected = str(runtime.root) + "/../outside-native"
    else:
        selected = str(runtime.root) + "/invalid\npath"
    picker_result(monkeypatch, selected + "\n")
    response = client.post("/api/workspace/folders/choose", json={})
    assert response.status_code == 422
    assert str(tmp_path) not in response.text
    assert sentinel.read_text() == "untouched"


def test_native_failure_and_timeout_release_lock(client, monkeypatch):
    picker_result(monkeypatch, "private path", returncode=1)
    assert client.post("/api/workspace/folders/choose", json={}).status_code == 503

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("private input", 120)

    monkeypatch.setattr(folder_picker.subprocess, "run", timeout)
    response = client.post("/api/workspace/folders/choose", json={})
    assert response.status_code == 503
    assert "private" not in response.text
    picker_result(monkeypatch, "\n")
    assert client.post("/api/workspace/folders/choose", json={}).status_code == 200


def test_native_concurrent_selection_is_rejected(client, monkeypatch):
    picker_result(monkeypatch, "\n")
    folder_picker._picker_lock.acquire()
    try:
        assert client.post("/api/workspace/folders/choose", json={}).status_code == 409
    finally:
        folder_picker._picker_lock.release()
