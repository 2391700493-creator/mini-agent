import io
import os
import stat
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.skills import MAX_FILE, MAX_ZIP, SkillStore


def document(
    name="会议纪要", description="整理会议结论和待办", body="# 步骤\n\n提取结论。", extra=""
):
    return f"---\nname: {name}\ndescription: {description}\n{extra}---\n\n{body}\n".encode()


def archive(files=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for path, content in (files or {"notes/SKILL.md": document()}).items():
            zipped.writestr(path, content)
    return output.getvalue()


def upload(client, data=None):
    return client.post(
        "/api/skills/import", content=data or archive(), headers={"Content-Type": "application/zip"}
    )


def manual(client, folder="manual", content=None):
    root = client.app.state.skill_store.root
    directory = root / folder
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_bytes(content or document("手动说明"))
    return directory


def save_data(item, **changes):
    return {
        **{key: item[key] for key in ("name", "description", "instructions", "revision")},
        **changes,
    }


def test_empty_list_and_default_location(client, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert SkillStore().root == Path(__file__).resolve().parents[2] / "workspace/skills"
    response = client.get("/api/skills")
    assert response.json() == {"items": [], "issues": []}
    assert response.headers["cache-control"] == "no-store"


def test_import_edit_attachments_refresh_and_delete(client):
    response = upload(
        client,
        archive(
            {
                "notes/SKILL.md": document(extra="license: MIT\nmetadata:\n  author: learner\n"),
                "notes/references/format.md": b"# format\n",
                "notes/example.py": b"raise Exception('must never execute')",
            }
        ),
    )
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["enabled"] is True
    assert item["name"] == "会议纪要"
    root = client.app.state.skill_store.root
    assert (root / "notes/references/format.md").read_text() == "# format\n"
    assert not (root / "notes/references/format.md").stat().st_mode & stat.S_IXUSR
    result = client.put(
        "/api/skills/notes",
        json=save_data(item, name="工作总结", instructions="# 结论\n\n保留事实。"),
    )
    assert result.status_code == 200, result.text
    updated = result.json()
    assert updated["id"] == "notes" and updated["revision"] != item["revision"]
    assert updated["updated_at"] >= item["updated_at"]
    text = (root / "notes/SKILL.md").read_text()
    assert (
        "工作总结" in text
        and "保留事实" in text
        and "license: MIT" in text
        and "author: learner" in text
    )
    assert client.post("/api/skills/refresh", json={}).json()["items"][0]["name"] == "工作总结"
    assert client.delete("/api/skills/notes").status_code == 204
    assert not (root / "notes").exists()
    assert client.get("/api/skills").json()["items"] == []


def test_root_zip_is_supported(client):
    result = upload(client, archive({"SKILL.md": document("meeting notes")}))
    assert result.status_code == 201
    assert result.json()["id"] == "meeting-notes"


def test_manual_changes_rescan_without_restart_and_invalid_diagnostics(client):
    assert client.get("/api/skills").json()["items"] == []
    folder = manual(client)
    manual(client, "broken", b"missing frontmatter")
    result = client.post("/api/skills/refresh", json={}).json()
    assert result["items"][0]["name"] == "手动说明"
    assert result["issues"][0]["directory"] == "broken"
    (folder / "SKILL.md").write_bytes(document("外部编辑"))
    assert client.post("/api/skills/refresh", json={}).json()["items"][0]["name"] == "外部编辑"
    (folder / "SKILL.md").unlink()
    assert client.get("/api/skills").json()["items"] == []
    (folder / "SKILL.md").write_bytes(document("重新修复"))
    assert len(client.get("/api/skills").json()["items"]) == 1


def test_toggle_survives_restart_and_agent_only_receives_enabled_valid_skills(
    client, migrated_database
):
    upload(client)
    assert client.patch("/api/skills/notes", json={"enabled": False}).status_code == 200
    manual(client, "active", document("启用说明"))
    manual(client, "broken", b"invalid")
    root = client.app.state.skill_store.root
    with TestClient(
        create_app(
            migrated_database,
            key_path=migrated_database.with_suffix(".key"),
            tool_root=migrated_database.parent / "workspace",
            skills_root=root,
        )
    ) as restarted:
        assert restarted.get("/api/skills/notes").json()["enabled"] is False
        with restarted.app.state.session_factory() as session:
            assert [item.id for item in restarted.app.state.skill_store.for_agent(session)] == [
                "active"
            ]
        assert (root / "notes/SKILL.md").exists()
        assert (
            restarted.patch("/api/skills/notes", json={"enabled": True}).json()["enabled"] is True
        )
        with restarted.app.state.session_factory() as session:
            assert len(restarted.app.state.skill_store.for_agent(session)) == 2


def test_edit_conflict_and_duplicate_name_do_not_overwrite(client):
    item = upload(client).json()
    manual(client, "other", document("其他任务"))
    assert client.put("/api/skills/notes", json=save_data(item, name="其他任务")).status_code == 409
    path = client.app.state.skill_store.root / "notes/SKILL.md"
    path.write_bytes(document("外部修改"))
    result = client.put("/api/skills/notes", json=save_data(item, name="旧页面"))
    assert result.status_code == 409
    assert "外部修改" in path.read_text()


def test_duplicate_name_or_directory_keeps_existing_content(client):
    upload(client)
    root = client.app.state.skill_store.root
    original = (root / "notes/SKILL.md").read_bytes()
    assert upload(client).status_code == 409
    assert upload(client, archive({"other/SKILL.md": document()})).status_code == 409
    assert upload(client, archive({"notes/SKILL.md": document("不同名称")})).status_code == 409
    (root / "reserved").mkdir()
    assert upload(client, archive({"reserved/SKILL.md": document("保留目录")})).status_code == 409
    assert (root / "notes/SKILL.md").read_bytes() == original
    assert not (root / "other").exists()


def test_concurrent_import_has_one_winner(client):
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _: upload(client).status_code, range(2)))
    assert sorted(statuses) == [201, 409]
    assert len(client.get("/api/skills").json()["items"]) == 1


@pytest.mark.parametrize(
    "path",
    [
        "../sentinel",
        "/sentinel",
        "C:/sentinel",
        "notes/../../sentinel",
        "notes\\..\\sentinel",
        "notes/.hidden",
        "notes//file",
        "notes/./file",
    ],
)
def test_unsafe_zip_paths_never_write_outside_root(client, tmp_path, path):
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("untouched")
    result = upload(client, archive({"notes/SKILL.md": document(), path: b"changed"}))
    assert result.status_code == 400, result.text
    assert "路径" in result.json()["detail"]
    assert sentinel.read_text() == "untouched"
    root = client.app.state.skill_store.root
    assert not root.exists() or not list(root.iterdir())


def test_zip_symlink_is_rejected(client):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        zipped.writestr("notes/SKILL.md", document())
        info = zipfile.ZipInfo("notes/linked")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zipped.writestr(info, "../../sentinel")
    response = upload(client, output.getvalue())
    assert response.status_code == 400 and "符号链接" in response.text


@pytest.mark.parametrize(
    "files",
    [
        {"readme.md": b"no skill"},
        {"a/SKILL.md": document(), "b/SKILL.md": document("two")},
        {"deep/nested/SKILL.md": document()},
        {"a/SKILL.md": document(), "outside.txt": b"x"},
        {"a/SKILL.md": document(), "a/file": b"x", "a/file/child": b"x"},
        {"a/SKILL.md": document(), "a/A": b"x", "a/a": b"y"},
        {"a/SKILL.md": document(), "a/Ref/a": b"x", "a/ref/b": b"y"},
    ],
)
def test_invalid_zip_structure(client, files):
    response = upload(client, archive(files))
    assert response.status_code == 400, response.text
    assert client.get("/api/skills").json()["items"] == []


@pytest.mark.parametrize(
    "raw",
    [
        b"not frontmatter",
        b"---\nname: x\n---\nbody",
        b"---\nname: x\ndescription: y\n---\n  ",
        b"---\nname: [x]\ndescription: y\n---\nbody",
        b"---\nname: x\nname: y\n---\nbody",
        b"---\nname: &x [*x]\n---\nbody",
        b"---\nname: !!python/object/apply:os.system ['echo bad']\n---\nbody",
        b"\xff\xfe",
        b"---\nname: [unclosed\n---\nbody",
        document(name=" "),
    ],
)
def test_invalid_skill_content_has_readable_reason(client, raw):
    response = upload(client, archive({"SKILL.md": raw}))
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)
    assert "Traceback" not in response.text


def test_resource_limits_and_corrupted_zip(client):
    assert upload(client, b"not zip").status_code == 400
    assert upload(client, b"x" * (MAX_ZIP + 1)).status_code == 413
    assert (
        upload(
            client, archive({"SKILL.md": document(), "large.txt": b"x" * (MAX_FILE + 1)})
        ).status_code
        == 413
    )
    files = {"SKILL.md": document(), **{f"file-{i}": b"x" for i in range(100)}}
    assert upload(client, archive(files)).status_code == 400
    files = {"SKILL.md": document(), **{f"file-{i}": b"x" * MAX_FILE for i in range(11)}}
    assert upload(client, archive(files)).status_code == 413


def test_manual_links_are_excluded_and_cannot_edit_outside(client, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "SKILL.md"
    sentinel.write_bytes(document("外部内容"))
    root = client.app.state.skill_store.root
    root.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    folder = root / "filelink"
    folder.mkdir()
    (folder / "SKILL.md").symlink_to(sentinel)
    hard = root / "hardlink"
    hard.mkdir()
    os.link(sentinel, hard / "SKILL.md")
    result = client.get("/api/skills").json()
    assert result["items"] == [] and len(result["issues"]) == 3
    assert client.delete("/api/skills/linked").status_code == 503
    assert sentinel.read_bytes() == document("外部内容")


def test_delete_unlinks_attachment_symlink_without_touching_target(client, tmp_path):
    folder = manual(client)
    sentinel = tmp_path / "outside.txt"
    sentinel.write_text("keep")
    (folder / "attachment").symlink_to(sentinel)
    assert client.delete("/api/skills/manual").status_code == 204
    assert sentinel.read_text() == "keep"


def test_root_symlink_rejected_before_any_writes(client, tmp_path):
    root = client.app.state.skill_store.root
    target = tmp_path / "other-directory"
    target.mkdir()
    root.symlink_to(target, target_is_directory=True)
    assert upload(client).status_code == 503
    assert list(target.iterdir()) == []


def test_duplicate_manual_names_are_unavailable_until_fixed(client):
    manual(client, "one", document("same"))
    two = manual(client, "two", document("SAME"))
    result = client.get("/api/skills").json()
    assert result["items"] == [] and len(result["issues"]) == 2
    assert upload(client, archive({"SKILL.md": document("Same")})).status_code == 409
    (two / "SKILL.md").write_bytes(document("different"))
    assert len(client.post("/api/skills/refresh", json={}).json()["items"]) == 2


def test_validation_missing_resource_and_local_access(client):
    assert client.get("/api/skills/missing").status_code == 404
    assert client.delete("/api/skills/missing").status_code == 404
    assert client.patch("/api/skills/missing", json={"enabled": "false"}).status_code == 422
    assert client.put("/api/skills/missing", json={"name": "secret-input"}).status_code == 422
    assert (
        "secret-input" not in client.put("/api/skills/missing", json={"name": "secret-input"}).text
    )
    assert client.post("/api/skills/import", json={}).status_code == 415
    for method in ("get", "delete"):
        assert (
            getattr(client, method)(
                "/api/skills/notes", headers={"Origin": "https://evil.example"}
            ).status_code
            == 403
        )
    assert (
        client.post(
            "/api/skills/import",
            content=archive(),
            headers={"Content-Type": "application/zip", "Sec-Fetch-Site": "cross-site"},
        ).status_code
        == 403
    )


def test_failed_import_cleans_partial_files(client, monkeypatch):
    def fail(*args):
        raise OSError("private-system-path")

    monkeypatch.setattr(client.app.state.skill_store, "write_import_file", fail)
    response = upload(client)
    assert response.status_code == 503
    assert "private-system-path" not in response.text
    assert list(client.app.state.skill_store.root.iterdir()) == []


def test_markdown_whitespace_round_trip_and_summary_shape(client):
    item = upload(client).json()
    markdown = "    indented code block\n\nA hard break  \nnext line  "
    response = client.put("/api/skills/notes", json=save_data(item, instructions=markdown))
    assert response.status_code == 200
    assert response.json()["instructions"] == markdown
    response = client.put("/api/skills/notes", json=save_data(response.json()))
    assert response.json()["instructions"] == markdown
    summary = client.get("/api/skills").json()["items"][0]
    assert "instructions" not in summary and "revision" not in summary


def test_invalid_unicode_is_validation_error(client):
    item = upload(client).json()
    data = save_data(item, instructions="\ud800")
    import json

    response = client.put(
        "/api/skills/notes", content=json.dumps(data), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
