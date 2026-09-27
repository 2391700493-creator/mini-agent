from datetime import UTC, datetime
from uuid import uuid4

from app.models import ChatMessage


def seed_messages(client):
    cid = client.post("/api/chat/conversations", json={}).json()["id"]
    ids = {}
    with client.app.state.session_factory() as session:
        for sequence, (role, status) in enumerate(
            [("user", "completed"), ("assistant", "completed"), ("assistant", "generating")],
            start=1,
        ):
            mid = str(uuid4())
            ids[(role, status)] = mid
            session.add(
                ChatMessage(
                    id=mid,
                    conversation_id=cid,
                    sequence=sequence,
                    role=role,
                    content="临时测试正文",
                    status=status,
                    created_at=datetime.now(UTC),
                    agent_id=None,
                    agent_name="测试助手" if role == "assistant" else None,
                )
            )
        session.commit()
    return cid, ids


def test_feedback_persists_replaces_and_can_be_cleared(client):
    cid, ids = seed_messages(client)
    mid = ids[("assistant", "completed")]
    path = f"/api/chat/conversations/{cid}/messages/{mid}/feedback"
    for rating in ["helpful", "unhelpful", None]:
        response = client.patch(path, json={"rating": rating})
        assert response.status_code == 200
        assert response.json()["feedback_rating"] == rating
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        reply = next(message for message in detail["messages"] if message["id"] == mid)
        assert reply["feedback_rating"] == rating
        assert reply["content"] == "临时测试正文"


def test_feedback_rejects_wrong_message_state_and_conversation(client):
    cid, ids = seed_messages(client)
    for key, status in [(("user", "completed"), 400), (("assistant", "generating"), 409)]:
        path = f"/api/chat/conversations/{cid}/messages/{ids[key]}/feedback"
        assert client.patch(path, json={"rating": "helpful"}).status_code == status
    other = client.post("/api/chat/conversations", json={}).json()["id"]
    mid = ids[("assistant", "completed")]
    assert (
        client.patch(
            f"/api/chat/conversations/{other}/messages/{mid}/feedback", json={"rating": "helpful"}
        ).status_code
        == 404
    )
    path = f"/api/chat/conversations/{cid}/messages/{mid}/feedback"
    assert client.patch(path, json={"rating": "unknown"}).status_code == 422
    assert client.patch(path, json={"rating": "helpful", "content": "修改正文"}).status_code == 422
