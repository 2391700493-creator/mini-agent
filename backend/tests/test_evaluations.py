import json
import time

import httpx
import pytest
from test_chat import MODEL, Stream, frame, normal

from app.models import EvaluationDataset, EvaluationTask, EvaluationTaskCase


def wait_task(client, task_id):
    for _ in range(300):
        result = client.get(f"/api/evaluations/tasks/{task_id}").json()
        if result["status"] != "running":
            return result
        time.sleep(0.01)
    pytest.fail("评测任务未结束")


@pytest.fixture
def evaluation(client):
    model = client.post("/api/models", json={**MODEL, "context_length": 1_000_000}).json()
    agent = client.post(
        "/api/agents",
        json={
            "name": "评测目标",
            "model_id": model["id"],
            "system_prompt": "只回答用户的问题。",
            "tool_ids": ["current_time"],
        },
    ).json()
    calls, streams = [], []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, stream=streams.pop(0))

    client.app.state.evaluation_store.transport = httpx.MockTransport(handler)
    return client, model, agent, calls, streams


def create_dataset(client, cases):
    dataset = client.post(
        "/api/evaluations/datasets", json={"name": "测试集", "description": ""}
    ).json()
    for item in cases:
        response = client.post(f"/api/evaluations/datasets/{dataset['id']}/cases", json=item)
        assert response.status_code == 201, response.text
    return dataset


def create_task(client, dataset, agent, model, **extra):
    response = client.post(
        "/api/evaluations/tasks",
        json={
            "dataset_id": dataset["id"],
            "agent_id": agent["id"],
            "scoring_model_id": model["id"],
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_normal_scoring_isolated_context_and_tools_default_off(evaluation):
    client, model, agent, calls, streams = evaluation
    dataset = create_dataset(
        client, [{"question": "只回答 3", "expected_answer": "3", "grading_criteria": "正确"}]
    )
    task = create_task(client, dataset, agent, model)
    streams.extend([normal("3"), normal('{"score": 60, "reason": "答案正确"}')])
    started = client.post(f"/api/evaluations/tasks/{task['id']}/start", json={})
    assert started.status_code == 200
    detail = wait_task(client, task["id"])
    item = detail["cases"][0]
    assert detail["status"] == "completed" and item["status"] == "passed" and item["score"] == 60
    assert "tools" not in calls[0] and calls[0]["messages"][-1]["content"] == "只回答 3"
    assert "expected_answer" not in json.dumps(calls[0], ensure_ascii=False)
    assert calls[1].get("tools") is None and item["run_id"]
    assert client.post(f"/api/evaluations/tasks/{task['id']}/start", json={}).status_code == 409


def test_invalid_grade_retries_then_continues_and_statistics(evaluation):
    client, model, agent, calls, streams = evaluation
    dataset = create_dataset(
        client,
        [
            {"question": "第一题", "expected_answer": "a", "grading_criteria": "正确"},
            {"question": "第二题", "expected_answer": "b", "grading_criteria": "正确"},
        ],
    )
    task = create_task(client, dataset, agent, model, passing_score=80)
    streams.extend(
        [
            normal("a"),
            normal("不是 JSON"),
            normal('{"score": 101, "reason": "越界"}'),
            normal("b"),
            normal('{"score": 80, "reason": "边界通过"}'),
        ]
    )
    client.post(f"/api/evaluations/tasks/{task['id']}/start", json={})
    detail = wait_task(client, task["id"])
    assert [item["status"] for item in detail["cases"]] == ["grading_failed", "passed"]
    assert detail["stats"] == {
        "total": 2,
        "completed": 2,
        "passed": 1,
        "failed": 0,
        "execution_failed": 0,
        "grading_failed": 1,
        "average_score": 80,
    }
    assert detail["cases"][0]["grading_attempts"] == 2
    assert [message["role"] for message in calls[3]["messages"]] == ["system", "user"]
    assert calls[3]["messages"][-1]["content"] == "第二题"
    assert len(calls) == 5


def test_execution_failure_does_not_score_and_example_seed_is_idempotent(evaluation):
    client, model, agent, calls, streams = evaluation
    seeded = [
        x for x in client.get("/api/evaluations/datasets").json() if x["name"] == "基础能力示例"
    ]
    assert len(seeded) == 1 and seeded[0]["case_count"] == 3
    dataset = create_dataset(
        client, [{"question": "题目", "expected_answer": "x", "grading_criteria": "正确"}]
    )
    task = create_task(client, dataset, agent, model)
    streams.append(Stream([frame("未完成")]))
    client.post(f"/api/evaluations/tasks/{task['id']}/start", json={})
    detail = wait_task(client, task["id"])
    assert detail["cases"][0]["status"] == "execution_failed" and len(calls) == 1
    with client.app.state.session_factory() as session:
        assert session.query(EvaluationTask).count() >= 1
        assert session.query(EvaluationTaskCase).filter_by(task_id=task["id"]).count() == 1
        assert (
            session.query(EvaluationDataset)
            .filter_by(stable_key="mini-agent-basic-evaluation-v1")
            .count()
            == 1
        )


def test_recover_interrupted_task_keeps_finished_results(evaluation):
    client, model, agent, _calls, _streams = evaluation
    dataset = create_dataset(
        client, [{"question": "题目", "expected_answer": "x", "grading_criteria": "正确"}]
    )
    task = create_task(client, dataset, agent, model)
    with client.app.state.session_factory() as session:
        row = session.get(EvaluationTask, task["id"])
        case = session.query(EvaluationTaskCase).filter_by(task_id=row.id).one()
        row.status = "running"
        case.status = "executing"
        session.commit()
    client.app.state.evaluation_store.recover()
    detail = client.get(f"/api/evaluations/tasks/{task['id']}").json()
    assert detail["status"] == "interrupted"
    assert detail["cases"][0]["status"] == "execution_failed"
    assert "服务重启" in detail["cases"][0]["error"]
