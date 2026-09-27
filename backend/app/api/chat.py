import asyncio
import json
from dataclasses import asdict

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.models import Agent, ChatAttachment
from app.repositories import agents as agent_repository
from app.schemas.chat import (
    ChatAgent,
    ChatInput,
    ConversationCreate,
    ConversationDetail,
    ConversationUpdate,
    ConversationView,
    GenerationView,
    MessageFeedbackInput,
    MessageView,
    RegenerateInput,
    SelectAgent,
)
from app.services.attachments import prepare_attachments

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.get("/agents", response_model=list[ChatAgent])
async def agents(request: Request):
    with request.app.state.session_factory() as session:
        return [
            ChatAgent(
                id=item.id,
                name=item.name,
                is_default=item.is_default,
                description=item.description,
                is_ready=item.is_ready,
                unavailable_reason=item.unavailable_reason,
                tool_count=item.tool_count,
                skill_count=item.skill_count,
                mcp_server_count=item.mcp_server_count,
            )
            for item in (
                agent_repository.summary(session, agent)
                for agent in session.scalars(
                    select(Agent).order_by(Agent.is_default.desc(), Agent.name)
                )
            )
        ]


@router.get("/conversations", response_model=list[ConversationView])
async def listing(request: Request):
    return request.app.state.chat_store.listing()


@router.post("/conversations", response_model=ConversationView, status_code=201)
async def create(request: Request, data: ConversationCreate | None = None):
    data = data or ConversationCreate()
    return request.app.state.chat_store.create(data.project_id, data.folder)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def detail(conversation_id: str, request: Request):
    return request.app.state.chat_store.detail(conversation_id)


@router.put("/conversations/{conversation_id}/agent", response_model=ConversationView)
async def select_agent(conversation_id: str, data: SelectAgent, request: Request):
    return request.app.state.chat_store.select_agent(conversation_id, data.agent_id)


@router.post(
    "/conversations/{conversation_id}/messages", response_model=GenerationView, status_code=201
)
async def send(conversation_id: str, data: ChatInput, request: Request):
    prepared = await run_in_threadpool(prepare_attachments, data.attachments)
    return request.app.state.chat_store.start(conversation_id, data, prepared)


@router.get("/conversations/{conversation_id}/generations/{generation_id}/events")
async def events(conversation_id: str, generation_id: str, request: Request):
    store = request.app.state.chat_store
    store.snapshot(conversation_id, generation_id)

    async def subscribe():
        previous = None
        sequence = 0
        ticks = 0
        while True:
            if await request.is_disconnected():
                break
            # 正文仍使用累积快照替换；正式 Runtime 事件以独立 SSE 类型转发。
            result = store.snapshot(conversation_id, generation_id)
            for event in store.events_since(generation_id, sequence):
                payload = json.dumps(asdict(event), ensure_ascii=False)
                yield f"event: runtime\ndata: {payload}\n\n"
                sequence = event.sequence
            data = result.model_dump_json()
            if data != previous:
                yield f"data: {data}\n\n"
                previous = data
            if result.status != "generating":
                break
            ticks += 1
            if ticks % 100 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.1)

    return StreamingResponse(
        subscribe(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


@router.patch(
    "/conversations/{conversation_id}/messages/{message_id}/feedback",
    response_model=MessageView,
)
def feedback(conversation_id: str, message_id: str, data: MessageFeedbackInput, request: Request):
    return request.app.state.chat_store.feedback(conversation_id, message_id, data.rating)


@router.post(
    "/conversations/{conversation_id}/generations/{generation_id}/stop",
    response_model=GenerationView,
)
async def stop(conversation_id: str, generation_id: str, request: Request):
    return await request.app.state.chat_store.stop(conversation_id, generation_id)


@router.patch("/conversations/{conversation_id}", response_model=ConversationView)
async def update_conversation(conversation_id: str, data: ConversationUpdate, request: Request):
    return request.app.state.chat_store.update_conversation(conversation_id, data)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, request: Request):
    request.app.state.chat_store.delete_conversation(conversation_id)
    return Response(status_code=204)


@router.get("/attachments/{attachment_id}")
def attachment(attachment_id: str, request: Request):
    from fastapi import HTTPException

    with request.app.state.session_factory() as session:
        item = session.get(ChatAttachment, attachment_id)
        if item is None:
            raise HTTPException(404, "附件不存在。")
        return Response(
            content=item.data,
            media_type=item.mime_type,
            headers={
                "Content-Disposition": "inline"
                if item.mime_type.startswith("image/")
                else "attachment",
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )


@router.post(
    "/conversations/{conversation_id}/generations/{generation_id}/retry",
    response_model=GenerationView,
    status_code=201,
)
async def regenerate(
    conversation_id: str, generation_id: str, data: RegenerateInput, request: Request
):
    return request.app.state.chat_store.regenerate(conversation_id, generation_id, data.request_id)
