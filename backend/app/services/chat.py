"""聊天消息持久化与运行事件转发；执行和取消交给 Agent Runtime。"""

import asyncio
from collections import OrderedDict, deque
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, inspect, select, update

from app.models import (
    Agent,
    AgentPrompt,
    ChatAttachment,
    ChatGeneration,
    ChatMessage,
    Conversation,
    LanguageModel,
    ModelSecret,
    Project,
)
from app.repositories.language_models import write_transaction
from app.schemas.chat import ConversationDetail, ConversationView, GenerationView, MessageView
from app.services.agent_runtime import (
    Cancellation,
    CapabilityLimits,
    RuntimeContext,
    RuntimeRequest,
)
from app.services.attachments import model_content, prepare_attachments
from app.services.runs import safe_value

ACTIVE = "generating"


class RunEventBuffer:
    """元事件保留完整配对；正文重放有界，聊天正文以数据库累积快照为准。"""

    def __init__(self):
        # 100 轮 × (2 模型事件 + 32 × 2 工具事件) + 2 运行事件最多 6602 条。
        self.lifecycle = deque(maxlen=8192)
        self.text = deque(maxlen=512)

    def append(self, event):
        (self.text if event.type == "text_delta" else self.lifecycle).append(event)

    def since(self, sequence):
        return sorted(
            (
                event
                for group in (self.lifecycle, self.text)
                for event in group
                if event.sequence > sequence
            ),
            key=lambda event: event.sequence,
        )


class ChatStore:
    def __init__(self, factory, runtime, runs, transport=None):
        self.factory, self.transport = factory, transport
        self.runtime, self.runs = runtime, runs
        self.signals = {}
        self.runtime_events = OrderedDict()
        self.tasks: dict[str, asyncio.Task] = {}
        self.workspace = None
        self.unsaved: dict[str, GenerationView] = {}

    def recover(self):
        with self.factory() as session:
            if not inspect(session.bind).has_table("chat_generations"):
                return
            session.rollback()
            with write_transaction(session):
                now = datetime.now(UTC)
                interrupted = list(
                    session.scalars(select(ChatGeneration).where(ChatGeneration.status == ACTIVE))
                )
                for run in interrupted:
                    run.status = "failed"
                    run.error = "运行中断。服务异常退出，回复未完成。"
                    run.end_reason = "运行中断"
                    run.ended_at = now
                    run.duration_ms = max(
                        0, int((now - run.created_at.replace(tzinfo=UTC)).total_seconds() * 1000)
                    )
                session.execute(
                    update(ChatMessage).where(ChatMessage.status == ACTIVE).values(status="failed")
                )

    async def close(self):
        for cancel in list(self.signals.values()):
            cancel.cancel()
        await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)

    @staticmethod
    def conversation(session, conversation_id):
        row = session.get(Conversation, conversation_id)
        if row is None:
            raise HTTPException(404, "会话不存在，请刷新列表。")
        return row

    @staticmethod
    def available_agent(session, agent_id):
        agent = session.get(Agent, agent_id) if agent_id else None
        if agent is None or session.get(ModelSecret, agent.model_id) is None:
            raise HTTPException(409, "当前 Agent 已删除或模型不可用，请重新选择 Agent。")
        if (
            session.scalar(
                select(AgentPrompt.agent_id).where(AgentPrompt.agent_id == agent.id).limit(1)
            )
            is None
        ):
            raise HTTPException(409, "当前 Agent 缺少系统提示词，请编辑 Agent 后重试。")
        return agent

    def listing(self):
        with self.factory() as session:
            return [
                ConversationView.model_validate(row)
                for row in session.scalars(
                    select(Conversation).order_by(
                        Conversation.pinned.desc(), Conversation.updated_at.desc(), Conversation.id
                    )
                )
            ]

    def create(self, project_id=None, folder=None, *, fresh=False):
        if self.workspace:
            self.workspace.validate_folder(folder)
        with self.factory() as session, write_transaction(session):
            if project_id is not None and session.get(Project, project_id) is None:
                raise HTTPException(404, "项目不存在。")
            # 重复新建复用最近未使用的空会话；不改名、不清空选择，也不触碰已有历史。
            unused = session.scalar(
                select(Conversation)
                .where(
                    Conversation.project_id == project_id,
                    Conversation.folder == folder,
                    Conversation.title_custom.is_(False),
                    Conversation.pinned.is_(False),
                    ~select(ChatMessage.id)
                    .where(ChatMessage.conversation_id == Conversation.id)
                    .exists(),
                    ~select(ChatGeneration.id)
                    .where(ChatGeneration.conversation_id == Conversation.id)
                    .exists(),
                )
                .order_by(Conversation.updated_at.desc(), Conversation.id)
                .limit(1)
            )
            if unused is not None and not fresh:
                return ConversationView.model_validate(unused)
            default = session.scalar(select(Agent).where(Agent.is_default.is_(True)))
            now = datetime.now(UTC)
            row = Conversation(
                id=str(uuid4()),
                title="新会话",
                project_id=project_id,
                folder=folder,
                agent_id=default.id if default else None,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            result = ConversationView.model_validate(row)
        if self.workspace:
            self.workspace.archive(result.id)
        return result

    def update_conversation(self, conversation_id, data):
        if "folder" in data.model_fields_set and self.workspace:
            self.workspace.validate_folder(data.folder)
        with self.factory() as session, write_transaction(session):
            row = self.conversation(session, conversation_id)
            if "project_id" in data.model_fields_set:
                if data.project_id is not None and session.get(Project, data.project_id) is None:
                    raise HTTPException(404, "项目不存在。")
                row.project_id = data.project_id
            if "folder" in data.model_fields_set:
                if session.scalar(
                    select(ChatMessage.id).where(ChatMessage.conversation_id == row.id).limit(1)
                ) or self.active(session, row.id):
                    raise HTTPException(409, "开始对话后不能更换文件夹，请新建对话。")
                row.folder = data.folder
            if "title" in data.model_fields_set:
                row.title = data.title
                row.title_custom = True
            if "pinned" in data.model_fields_set:
                row.pinned = data.pinned
            # 管理操作不改最后消息时间；置顶组内仍按消息时间排序。
            session.flush()
            result = ConversationView.model_validate(row)
        if self.workspace:
            self.workspace.archive(result.id)
        return result

    def delete_conversation(self, conversation_id):
        with self.factory() as session, write_transaction(session):
            row = self.conversation(session, conversation_id)
            if self.active(session, conversation_id):
                raise HTTPException(409, "此会话正在生成，请先打开会话并停止生成，再删除。")
            # 先清理生成记录对用户消息的外键引用，同一事务删除全部历史。
            session.execute(
                delete(ChatGeneration).where(ChatGeneration.conversation_id == conversation_id)
            )
            session.execute(
                delete(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
            )
            session.delete(row)
        for generation_id, value in list(self.unsaved.items()):
            if value.conversation_id == conversation_id:
                self.unsaved.pop(generation_id, None)

    def generation_view(self, session, row):
        if row.id in self.unsaved:
            return self.unsaved[row.id]
        message = session.get(ChatMessage, row.assistant_message_id)
        return GenerationView(
            id=row.id,
            conversation_id=row.conversation_id,
            status=row.status,
            error=row.error,
            message=MessageView.model_validate(message) if message else None,
        )

    def detail(self, conversation_id):
        with self.factory() as session:
            row = self.conversation(session, conversation_id)
            messages = list(
                session.scalars(
                    select(ChatMessage)
                    .where(ChatMessage.conversation_id == conversation_id)
                    .order_by(ChatMessage.sequence)
                )
            )
            generation = session.scalar(
                select(ChatGeneration)
                .where(ChatGeneration.conversation_id == conversation_id)
                .order_by(ChatGeneration.sequence.desc())
                .limit(1)
            )
            event_rows = self.runs.persisted_events_since(generation.id, 0) if generation else []
            return ConversationDetail(
                **ConversationView.model_validate(row).model_dump(),
                messages=[MessageView.model_validate(m) for m in messages],
                generation=self.generation_view(session, generation) if generation else None,
                runtime_events=[asdict(event) for event in event_rows],
            )

    def feedback(self, conversation_id, message_id, rating):
        with self.factory() as session:
            with write_transaction(session):
                self.conversation(session, conversation_id)
                message = session.get(ChatMessage, message_id)
                if message is None or message.conversation_id != conversation_id:
                    raise HTTPException(404, "回复不存在。")
                if message.role != "assistant":
                    raise HTTPException(400, "只能对 AI 回复进行反馈。")
                if message.status == ACTIVE:
                    raise HTTPException(409, "请等待回复完成后再反馈。")
                message.feedback_rating = rating
                session.flush()
                result = MessageView.model_validate(message)
            return result

    def active(self, session, conversation_id):
        row = session.scalar(
            select(ChatGeneration).where(
                ChatGeneration.conversation_id == conversation_id,
                ChatGeneration.status == ACTIVE,
            )
        )
        if row and row.id in self.unsaved:
            # 上次写入失败的状态在后续数据库恢复后修正，避免永久锁住会话。
            fallback = self.unsaved[row.id]
            row.status, row.error = fallback.status, fallback.error
            message = session.get(ChatMessage, row.assistant_message_id)
            if message:
                message.status = "failed"
            session.flush()
            return None
        return row

    def select_agent(self, conversation_id, agent_id):
        with self.factory() as session, write_transaction(session):
            row = self.conversation(session, conversation_id)
            if self.active(session, conversation_id):
                raise HTTPException(409, "当前会话正在生成，请先停止或等待完成。")
            self.available_agent(session, agent_id)
            row.agent_id = agent_id
            result = ConversationView.model_validate(row)
        return result

    def start(self, conversation_id, data, prepared=None, *, limits=None, source="chat"):
        prepared = prepare_attachments(data.attachments) if prepared is None else prepared
        with self.factory() as session, write_transaction(session):
            conversation = self.conversation(session, conversation_id)
            previous = session.get(ChatGeneration, data.request_id)
            if previous:
                user = session.get(ChatMessage, previous.user_message_id)
                if (
                    previous.conversation_id != conversation_id
                    or user.content != data.content
                    or [(a.name, a.mime_type, a.digest) for a in user.attachments]
                    != [(a.name, a.mime_type, a.digest) for a in prepared]
                ):
                    raise HTTPException(409, "请求标识已使用，请重新发送。")
                return self.generation_view(session, previous)
            if self.active(session, conversation_id):
                raise HTTPException(409, "当前会话正在生成，请先停止或等待完成。")
            agent = self.available_agent(session, conversation.agent_id)
            model = session.get(LanguageModel, agent.model_id)
            if model is None:
                raise HTTPException(409, "当前 Agent 的模型不可用，请重新选择 Agent。")
            sequence = (
                session.scalar(
                    select(func.max(ChatMessage.sequence)).where(
                        ChatMessage.conversation_id == conversation_id
                    )
                )
                or 0
            )
            reserved = (
                session.scalar(
                    select(func.max(ChatGeneration.sequence)).where(
                        ChatGeneration.conversation_id == conversation_id
                    )
                )
                or 0
            )
            sequence = max(sequence, reserved) + 1
            now = datetime.now(UTC)
            user = ChatMessage(
                id=str(uuid4()),
                conversation_id=conversation_id,
                sequence=sequence,
                role="user",
                content=data.content,
                status="completed",
                created_at=now,
            )
            user.attachments = [
                ChatAttachment(
                    id=str(uuid4()),
                    position=index,
                    name=item.name,
                    mime_type=item.mime_type,
                    size=len(item.data),
                    digest=item.digest,
                    data=item.data,
                    extracted_text=item.extracted_text,
                    width=item.width,
                    height=item.height,
                )
                for index, item in enumerate(prepared)
            ]
            session.add(user)
            session.flush()
            if sequence == 1 and not conversation.title_custom:
                title = " ".join(data.content.split()) or prepared[0].name
                conversation.title = title[:30] + ("…" if len(title) > 30 else "")
            conversation.updated_at = now
            generation = ChatGeneration(
                id=data.request_id,
                source=source,
                conversation_id=conversation_id,
                user_message_id=user.id,
                assistant_message_id=str(uuid4()),
                sequence=sequence + 1,
                agent_id=agent.id,
                agent_name=agent.name,
                model_id=model.id,
                model_name=model.display_name,
                model_identifier=model.model_id,
                status=ACTIVE,
                created_at=now,
            )
            self.runs.apply_pricing_snapshot(generation, model)
            session.add(generation)
            session.flush()
            # Runtime 负责系统提示与配置；聊天仅提供本次输入之前的 completed 历史。
            messages = self.history(session, conversation_id, before=user.sequence)
            context = RuntimeContext(
                summary=conversation.context_summary,
                summarized_through_sequence=conversation.summarized_through_sequence,
                save_summary=lambda new, boundary, old, old_boundary: self.save_summary(
                    conversation_id, new, boundary, old, old_boundary
                ),
            )
            session.expunge(generation)
            result = self.generation_view(session, generation)
        if self.workspace:
            self.workspace.archive(conversation_id)
        self.dispatch(
            generation,
            data.content,
            messages,
            context,
            model_content(data.content, prepared),
            limits,
        )
        return result

    def dispatch(self, generation, user_input, messages, context, user_content, limits=None):
        # 只有用户消息提交成功，才允许发起模型调用。任务由 Store 持有，不依赖请求生命周期。
        cancel = Cancellation()
        self.signals[generation.id] = cancel
        self.runtime_events[generation.id] = RunEventBuffer()
        # 只保留最近已完成任务的短期事件缓存，不作为运行记录持久化。
        for old in list(self.runtime_events):
            if len(self.runtime_events) <= 32:
                break
            if old not in self.tasks and old != generation.id:
                self.runtime_events.pop(old)
        task = asyncio.create_task(
            self.run(
                generation,
                user_input,
                messages,
                context,
                cancel,
                user_content,
                limits,
            )
        )
        self.tasks[generation.id] = task

        def done(_):
            self.tasks.pop(generation.id, None)
            self.signals.pop(generation.id, None)

        task.add_done_callback(done)

    def history(self, session, conversation_id, before=None):
        # Context uses the latest complete reply, independent of run record deletion.
        query = (
            select(ChatMessage)
            .where(
                ChatMessage.conversation_id == conversation_id, ChatMessage.status == "completed"
            )
            .order_by(ChatMessage.sequence)
        )
        if before is not None:
            query = query.where(ChatMessage.sequence < before)
        messages = []
        for message in session.scalars(query):
            item = {
                "role": message.role,
                "content": model_content(message.content, message.attachments),
                "sequence": message.sequence,
            }
            if message.role == "assistant" and messages and messages[-1]["role"] == "assistant":
                messages[-1] = item
            else:
                messages.append(item)
        return messages

    def regenerate(self, conversation_id, generation_id, request_id):
        with self.factory() as session, write_transaction(session):
            conversation = self.conversation(session, conversation_id)
            source = session.get(ChatGeneration, generation_id)
            if source is None or source.conversation_id != conversation_id:
                raise HTTPException(404, "回复不存在。")
            previous = session.get(ChatGeneration, request_id)
            if previous:
                if (
                    previous.conversation_id != conversation_id
                    or previous.user_message_id != source.user_message_id
                ):
                    raise HTTPException(409, "请求标识已使用，请重新发送。")
                return self.generation_view(session, previous)
            if self.active(session, conversation_id):
                raise HTTPException(409, "当前会话正在生成，请先停止或等待完成。")
            user = session.get(ChatMessage, source.user_message_id)
            latest_user = session.scalar(
                select(ChatMessage.id)
                .where(ChatMessage.conversation_id == conversation_id, ChatMessage.role == "user")
                .order_by(ChatMessage.sequence.desc())
                .limit(1)
            )
            if user is None or user.id != latest_user:
                raise HTTPException(409, "只能重新生成最后一次提问的回复。")
            agent = self.available_agent(session, conversation.agent_id)
            model = session.get(LanguageModel, agent.model_id)
            if model is None:
                raise HTTPException(409, "当前 Agent 的模型不可用。")
            maximum = (
                session.scalar(
                    select(func.max(ChatMessage.sequence)).where(
                        ChatMessage.conversation_id == conversation_id
                    )
                )
                or 0
            )
            reserved = (
                session.scalar(
                    select(func.max(ChatGeneration.sequence)).where(
                        ChatGeneration.conversation_id == conversation_id
                    )
                )
                or 0
            )
            generation = ChatGeneration(
                id=request_id,
                conversation_id=conversation_id,
                user_message_id=user.id,
                assistant_message_id=str(uuid4()),
                sequence=max(maximum, reserved) + 1,
                agent_id=agent.id,
                agent_name=agent.name,
                model_id=model.id,
                model_name=model.display_name,
                model_identifier=model.model_id,
                status=ACTIVE,
                created_at=datetime.now(UTC),
            )
            self.runs.apply_pricing_snapshot(generation, model)
            session.add(generation)
            session.flush()
            messages = self.history(session, conversation_id, before=user.sequence)
            context = RuntimeContext(
                summary=conversation.context_summary,
                summarized_through_sequence=conversation.summarized_through_sequence,
            )
            user_input = user.content
            user_content = model_content(user.content, user.attachments)
            result = self.generation_view(session, generation)
            session.expunge(generation)
        limits = CapabilityLimits(tools=frozenset(), mcp_servers=frozenset())
        self.dispatch(generation, user_input, messages, context, user_content, limits)
        return result

    def save_progress(self, generation, content, status, error):
        with self.factory() as session, write_transaction(session):
            row = session.get(ChatGeneration, generation.id)
            row.status, row.error = status, error
            if status != ACTIVE and row.ended_at is None:
                now = datetime.now(UTC)
                row.ended_at = now
                row.duration_ms = max(
                    0, int((now - row.created_at.replace(tzinfo=UTC)).total_seconds() * 1000)
                )
                row.end_reason = error or (
                    "模型已完成回答。" if status == "completed" else "运行已结束。"
                )
            if content:
                message = session.get(ChatMessage, generation.assistant_message_id)
                if message is None:
                    message = ChatMessage(
                        id=generation.assistant_message_id,
                        conversation_id=generation.conversation_id,
                        sequence=generation.sequence,
                        role="assistant",
                        agent_id=generation.agent_id,
                        agent_name=generation.agent_name,
                        created_at=datetime.now(UTC),
                    )
                    session.add(message)
                message.content = content
                message.status = "failed" if status == "limit_reached" else status
                self.conversation(session, generation.conversation_id).updated_at = datetime.now(
                    UTC
                )

    def finish(self, generation, content, status, error):
        try:
            self.save_progress(generation, content, status, error)
            if self.workspace:
                self.workspace.archive(generation.conversation_id)
        except Exception:
            # 绝不打印数据库参数、模型异常或密钥。保留内存正文供页面明确展示“未保存”。
            try:
                self.runs.mark_save_failed(generation.id)
            except Exception:
                pass
            self.unsaved[generation.id] = GenerationView(
                id=generation.id,
                conversation_id=generation.conversation_id,
                status="failed",
                error="回复保存失败，内容尚未可靠保存，请复制保留。",
                saved=False,
                message=MessageView(
                    id=generation.assistant_message_id,
                    conversation_id=generation.conversation_id,
                    sequence=generation.sequence,
                    role="assistant",
                    content=content,
                    status="failed",
                    created_at=generation.created_at,
                    agent_id=generation.agent_id,
                    agent_name=generation.agent_name,
                )
                if content
                else None,
            )

    def save_summary(self, conversation_id, summary, boundary, old_summary, old_boundary):
        if not summary.strip() or type(boundary) is not int or boundary < 1:
            raise RuntimeError("invalid context summary")
        with self.factory() as session, write_transaction(session):
            conversation = self.conversation(session, conversation_id)
            if (
                conversation.context_summary != old_summary
                or conversation.summarized_through_sequence != old_boundary
            ):
                raise RuntimeError("context summary changed")
            conversation.context_summary = summary
            conversation.summarized_through_sequence = boundary

    async def run(
        self, generation, user_input, messages, context, cancel, user_content=None, limits=None
    ):
        content = ""

        async def receive(event):
            nonlocal content
            self.runs.record(generation.id, event)
            self.runtime_events[generation.id].append(event)
            if event.type == "text_delta":
                content += event.data["content"]
                if content.strip():
                    self.save_progress(generation, safe_value(content), ACTIVE, None)

        try:
            with self.factory() as session:
                folder = self.conversation(session, generation.conversation_id).folder
            result = await self.runtime.run(
                RuntimeRequest(
                    generation.agent_id,
                    user_input,
                    messages,
                    context=context,
                    run_id=generation.id,
                    user_content=user_content,
                    limits=limits or CapabilityLimits(),
                    folder=folder,
                ),
                cancel,
                receive,
                transport=self.transport,
            )
            self.finish(
                generation,
                safe_value(result.content) if result.content.strip() else "",
                result.status,
                None if result.status == "completed" else result.reason,
            )
        except Exception:
            self.finish(
                generation,
                safe_value(content),
                "failed",
                "回复处理或保存失败，请检查本地服务后重试。",
            )

    def cancel(self, generation_id):
        signal = self.signals.get(generation_id)
        if signal:
            signal.cancel()

    def events_since(self, generation_id, sequence):
        return self.runs.persisted_events_since(generation_id, sequence)

    def snapshot(self, conversation_id, generation_id):
        if generation_id in self.unsaved:
            result = self.unsaved[generation_id]
            if result.conversation_id == conversation_id:
                return result
        with self.factory() as session:
            row = session.get(ChatGeneration, generation_id)
            if row is None or row.conversation_id != conversation_id:
                raise HTTPException(404, "生成请求不存在。")
            return self.generation_view(session, row)

    async def stop(self, conversation_id, generation_id):
        self.snapshot(conversation_id, generation_id)
        task = self.tasks.get(generation_id)
        if task:
            self.cancel(generation_id)
            await asyncio.gather(task, return_exceptions=True)
        with self.factory() as session:
            row = session.get(ChatGeneration, generation_id)
            if row.status == ACTIVE and generation_id not in self.unsaved:
                message = session.get(ChatMessage, row.assistant_message_id)
                self.finish(row, message.content if message else "", "cancelled", "已停止生成。")
        return self.snapshot(conversation_id, generation_id)
