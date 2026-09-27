from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.main import create_app
from app.models import Agent, AgentMcp, AgentPrompt, AgentSkill, AgentTool, McpServer
from app.schemas.agents import AgentSave

MODEL = {
    "display_name": "日常模型",
    "model_id": "test-model",
    "base_url": "https://example.com/v1",
    "api_key": "test-only-key",
    "context_length": 8192,
    "max_output_tokens": 512,
    "temperature": 1,
}


@pytest.fixture
def resources(client):
    model = client.post("/api/models", json=MODEL).json()
    root = client.app.state.skill_store.root
    root.mkdir(parents=True, exist_ok=True)
    folder = root / "writing"
    folder.mkdir()
    (folder / "SKILL.md").write_text("---\nname: 写作\ndescription: 整理文稿\n---\n保留事实。\n")
    assert client.get("/api/skills").json()["items"][0]["id"] == "writing"
    server = client.post(
        "/api/mcp",
        json={"name": "检索", "description": "查询资料", "command": "node", "args": [], "env": {}},
    ).json()
    assert client.patch(f"/api/mcp/{server['id']}", json={"enabled": True}).status_code == 200
    return {
        "name": "研究助手",
        "description": "整理资料",
        "model_id": model["id"],
        "system_prompt": "保留来源。\n",
        "max_rounds": 10,
        "tool_ids": ["current_time"],
        "skill_ids": ["writing"],
        "mcp_server_ids": [server["id"]],
    }


def add(client, data):
    response = client.post("/api/agents", json=data)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_with_discovered_mcp_tools(client, resources):
    server_id = resources["mcp_server_ids"][0]
    with client.app.state.session_factory() as session:
        server = session.get(McpServer, server_id)
        server.tools = [
            {"name": "lookup", "description": "查询", "input_schema": {"type": "object"}}
        ]
        session.commit()
    agent = add(client, resources)
    with client.app.state.session_factory() as session:
        binding = session.scalar(select(AgentMcp).where(AgentMcp.agent_id == agent["id"]))
        assert binding.allowed_tools == ["lookup"]


def remove(client, agent_id, replacement=None):
    return client.request("DELETE", f"/api/agents/{agent_id}", json={"replacement_id": replacement})


def test_crud_versions_and_restart(client, resources, migrated_database):
    assert client.get("/api/agents").json() == []
    first = add(client, resources)
    assert first["is_default"] and first["prompt_version"] == 1
    assert first["auto_compress"] is True
    assert first["compression_trigger_ratio"] == 0.8
    assert first["compression_keep_recent_turns"] == 4
    assert first["compression_summary_target_tokens"] == 1000
    assert first["tool_count"] == first["skill_count"] == first["mcp_server_count"] == 1
    assert first["updated_at"].endswith("Z")
    options = client.get("/api/agents/options")
    assert options.headers["cache-control"] == "no-store"
    assert options.json()["models"][0]["name"] == "日常模型"
    assert options.json()["models"][0]["model_id"] == "test-model"
    assert options.json()["models"][0]["context_length"] == MODEL["context_length"]
    assert options.json()["models"][0]["max_output_tokens"] == MODEL["max_output_tokens"]
    assert "test-only-key" not in options.text
    path = f"/api/agents/{first['id']}"
    for changes in [
        {"name": "改名"},
        {"description": "新说明"},
        {"max_rounds": 1},
        {"tool_ids": []},
    ]:
        result = client.put(path, json=resources | changes)
        assert result.status_code == 200, result.text
        assert result.json()["prompt_version"] == 1
    updated = resources | {"system_prompt": resources["system_prompt"] + " "}
    assert client.put(path, json=updated).json()["prompt_version"] == 2
    assert client.put(path, json=updated).json()["prompt_version"] == 2
    assert client.put(path, json=resources).json()["prompt_version"] == 3
    with client.app.state.session_factory() as session:
        history = list(session.scalars(select(AgentPrompt).order_by(AgentPrompt.version)))
        assert [item.content for item in history] == [
            resources["system_prompt"],
            updated["system_prompt"],
            resources["system_prompt"],
        ]
    with TestClient(
        create_app(
            migrated_database,
            key_path=migrated_database.with_suffix(".key"),
            skills_root=client.app.state.skill_store.root,
            tool_root=migrated_database.parent / "workspace",
        )
    ) as restarted:
        detail = restarted.get(path).json()
        assert detail["prompt_version"] == 3 and detail["skills"][0]["name"] == "写作"
        assert restarted.get("/api/agents").json()[0]["is_default"]
    assert remove(client, first["id"]).status_code == 204
    assert client.get("/api/agents").json() == []
    with client.app.state.session_factory() as session:
        for table in [AgentPrompt, AgentTool, AgentSkill, AgentMcp]:
            assert session.scalar(select(func.count()).select_from(table)) == 0
    assert client.get("/api/models").json()
    assert add(client, resources)["is_default"]


@pytest.mark.parametrize(
    "change",
    [
        {"name": "  "},
        {"model_id": "missing"},
        {"max_rounds": 0},
        {"max_rounds": 101},
        {"max_rounds": 1.5},
        {"max_rounds": True},
        {"max_rounds": "10"},
        {"tool_ids": ["shell"]},
        {"tool_ids": ["current_time", "current_time"]},
        {"skill_ids": ["missing"]},
        {"mcp_server_ids": ["missing"]},
        {"system_prompt": "\x00"},
        {"system_prompt": "a" * 100001},
        {"compression_trigger_ratio": 0.49},
        {"compression_trigger_ratio": 0.951},
        {"compression_keep_recent_turns": 0},
        {"compression_summary_target_tokens": 127},
        {"is_default": True},
    ],
)
def test_validation_does_not_create_partial_agent(client, resources, change):
    response = client.post("/api/agents", json=resources | change)
    assert response.status_code == 422, response.text
    assert "input" not in response.json()["detail"]
    assert client.get("/api/agents").json() == []


def test_disabled_bindings_preserved_and_new_rejected(client, resources):
    first = add(client, resources)
    client.patch("/api/tools/current_time", json={"enabled": False})
    client.patch("/api/skills/writing", json={"enabled": False})
    client.patch(f"/api/mcp/{resources['mcp_server_ids'][0]}", json={"enabled": False})
    path = f"/api/agents/{first['id']}"
    detail = client.get(path).json()
    for kind in ["tools", "skills", "mcp_servers"]:
        assert detail[kind][0]["enabled"] is False
        assert detail[kind][0]["unavailable_reason"] == "已停用，不可用"
    kept = client.put(path, json=resources | {"name": "继续保留"})
    assert kept.status_code == 200
    assert kept.json()["prompt_version"] == 1
    assert (
        kept.json()["tool_count"]
        == kept.json()["skill_count"]
        == kept.json()["mcp_server_count"]
        == 1
    )
    assert client.post("/api/agents", json=resources).status_code == 422
    empty = resources | {"tool_ids": [], "skill_ids": [], "mcp_server_ids": []}
    assert client.put(path, json=empty).status_code == 200
    assert client.put(path, json=resources).status_code == 422
    assert client.get(path).json()["skill_count"] == 0


def test_invalid_external_skill_stays_bound(client, resources):
    agent = add(client, resources)
    (client.app.state.skill_store.root / "writing" / "SKILL.md").write_text("invalid")
    path = f"/api/agents/{agent['id']}"
    skill = client.get(path).json()["skills"][0]
    assert skill["name"] == "写作" and not skill["enabled"]
    assert "无效" in skill["unavailable_reason"]
    assert client.put(path, json=resources).status_code == 200
    assert client.delete("/api/skills/writing").status_code == 409


def test_defaults_deletion_and_database_constraints(client, resources):
    one = add(client, resources)
    two = add(client, resources | {"name": "备选"})
    three = add(client, resources | {"name": "第三个"})
    assert not two["is_default"] and not three["is_default"]
    assert remove(client, one["id"]).status_code == 409
    assert remove(client, one["id"], one["id"]).status_code == 409
    assert remove(client, one["id"], "missing").status_code == 404
    assert sum(item["is_default"] for item in client.get("/api/agents").json()) == 1
    assert client.put(f"/api/agents/{two['id']}/default", json={}).json()["is_default"]
    assert remove(client, one["id"]).status_code == 204
    assert remove(client, two["id"], three["id"]).status_code == 204
    assert client.get("/api/agents").json()[0]["is_default"]
    add(client, resources)
    with client.app.state.session_factory() as session:
        with pytest.raises(IntegrityError):
            session.execute(text("UPDATE agents SET is_default = 1"))
        session.rollback()
        with pytest.raises(IntegrityError):
            session.execute(text("DELETE FROM language_models"))
        session.rollback()


def test_resource_delete_protection_and_release(client, resources):
    one = add(client, resources)
    two = add(client, resources | {"name": "校对助手"})
    backup = client.post("/api/models", json=MODEL | {"display_name": "备选模型"}).json()
    for path in [
        f"/api/models/{resources['model_id']}",
        "/api/skills/writing",
        f"/api/mcp/{resources['mcp_server_ids'][0]}",
    ]:
        response = client.request("DELETE", path, json={})
        assert response.status_code == 409
        assert "研究助手" in response.text and "校对助手" in response.text
    # 引用检查先于默认模型替换校验，失败不改变模型或文件。
    assert client.get("/api/models").json()[0]["id"] == resources["model_id"]
    assert (client.app.state.skill_store.root / "writing" / "SKILL.md").exists()
    assert remove(client, two["id"]).status_code == 204
    freed = resources | {"model_id": backup["id"], "skill_ids": [], "mcp_server_ids": []}
    assert client.put(f"/api/agents/{one['id']}", json=freed).status_code == 200
    assert (
        client.request("DELETE", f"/api/models/{resources['model_id']}", json={}).status_code == 409
    )
    assert (
        client.request(
            "DELETE", f"/api/models/{resources['model_id']}", json={"replacement_id": backup["id"]}
        ).status_code
        == 204
    )
    assert client.delete("/api/skills/writing").status_code == 204
    assert client.delete(f"/api/mcp/{resources['mcp_server_ids'][0]}").status_code == 204


def test_concurrent_creates_switches_and_prompt_updates(client, resources):
    store = client.app.state.agent_store
    factory = client.app.state.session_factory

    def create(index):
        with factory() as session:
            return store.save(session, AgentSave(**(resources | {"name": f"助手 {index}"})))

    with ThreadPoolExecutor(max_workers=4) as executor:
        agents = list(executor.map(create, range(6)))
    assert sum(item["is_default"] for item in client.get("/api/agents").json()) == 1

    def switch(agent):
        with factory() as session:
            store.set_default(session, agent.id)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(switch, agents))
    assert sum(item["is_default"] for item in client.get("/api/agents").json()) == 1

    def edit(index):
        with factory() as session:
            store.save(
                session, AgentSave(**(resources | {"system_prompt": f"版本 {index}"})), agents[0].id
            )

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(edit, range(4)))
    with factory() as session:
        assert list(
            session.scalars(
                select(AgentPrompt.version)
                .where(AgentPrompt.agent_id == agents[0].id)
                .order_by(AgentPrompt.version)
            )
        ) == [1, 2, 3, 4, 5]
        assert session.scalar(select(func.count()).select_from(Agent).where(Agent.is_default)) == 1
