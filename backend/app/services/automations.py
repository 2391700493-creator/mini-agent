"""SQLite 认领任务，CronTrigger 计算时刻；每个任务最多一个在途执行。"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from apscheduler.triggers.cron import CronTrigger
from fastapi import HTTPException
from sqlalchemy import inspect, select

from app.models import Automation
from app.repositories.language_models import write_transaction
from app.schemas.automations import AutomationView
from app.schemas.chat import ChatInput
from app.services.agent_runtime import CapabilityLimits


def next_time(row, now):
    hour, minute = map(int, row.time.split(":"))
    weekday = (
        "*"
        if row.frequency == "daily"
        else "mon-fri"
        if row.frequency == "weekdays"
        else str(row.weekday)
    )
    return (
        CronTrigger(hour=hour, minute=minute, day_of_week=weekday, timezone=row.timezone)
        .get_next_fire_time(None, now + timedelta(seconds=1))
        .astimezone(UTC)
    )


class AutomationStore:
    def __init__(self, factory, chat):
        self.factory, self.chat = factory, chat
        self.worker = None
        self.tasks = {}
        self.runs = {}
        self.closing = False
        self.stopping = set()

    def listing(self):
        with self.factory() as session:
            return [
                AutomationView.model_validate(row)
                for row in session.scalars(
                    select(Automation).order_by(Automation.created_at.desc())
                )
            ]

    @staticmethod
    def get(session, task_id):
        row = session.get(Automation, task_id)
        if row is None:
            raise HTTPException(404, "定时任务不存在。")
        return row

    def save(self, data, task_id=None):
        with self.factory() as session, write_transaction(session):
            self.chat.available_agent(session, data.agent_id)
            row = (
                self.get(session, task_id)
                if task_id
                else Automation(id=str(uuid4()), created_at=datetime.now(UTC), status="idle")
            )
            if row.status == "running":
                raise HTTPException(409, "请先停止正在执行的任务。")
            for key, value in data.model_dump().items():
                setattr(row, key, value)
            row.next_run_at = next_time(row, datetime.now(UTC))
            row.last_error = None
            session.add(row)
            session.flush()
            return AutomationView.model_validate(row)

    def toggle(self, task_id, enabled):
        with self.factory() as session, write_transaction(session):
            row = self.get(session, task_id)
            row.enabled = enabled
            row.next_run_at = next_time(row, datetime.now(UTC))
            session.flush()
            return AutomationView.model_validate(row)

    def delete(self, task_id):
        with self.factory() as session, write_transaction(session):
            row = self.get(session, task_id)
            if row.status == "running":
                raise HTTPException(409, "请先停止正在执行的任务。")
            session.delete(row)

    def start(self, task_id, *, scheduled=False, now=None):
        if self.closing:
            raise HTTPException(409, "服务正在关闭。")
        self.stopping.discard(task_id)
        now = now or datetime.now(UTC)
        with self.factory() as session, write_transaction(session):
            row = self.get(session, task_id)
            if row.status == "running":
                if scheduled:
                    return
                raise HTTPException(409, "任务正在执行，请等待完成。")
            if scheduled and (not row.enabled or row.next_run_at.replace(tzinfo=UTC) > now):
                return
            row.status = "running"
            row.last_error = None
            row.last_run_at = now
            row.next_run_at = next_time(row, now)
            session.flush()
            snapshot = AutomationView.model_validate(row)
        task = asyncio.create_task(self.execute(snapshot))
        self.tasks[task_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(task_id, None))
        return snapshot

    async def execute(self, row):
        status, error = "failed", None
        try:
            if self.closing or row.id in self.stopping:
                raise asyncio.CancelledError
            conversation = self.chat.create(fresh=True)
            self.chat.select_agent(conversation.id, row.agent_id)
            with self.factory() as session, write_transaction(session):
                task = self.get(session, row.id)
                task.last_conversation_id = conversation.id
            limits = (
                CapabilityLimits()
                if row.allow_tools
                else CapabilityLimits(tools=frozenset(), mcp_servers=frozenset())
            )
            generation = self.chat.start(
                conversation.id,
                ChatInput(request_id=str(uuid4()), content=row.prompt),
                limits=limits,
                source="automation",
            )
            self.runs[row.id] = (conversation.id, generation.id)
            await self.chat.tasks[generation.id]
            result = self.chat.snapshot(conversation.id, generation.id)
            status, error = result.status, result.error
        except asyncio.CancelledError:
            status, error = "cancelled", "任务已停止。"
        except Exception:
            error = "任务未完成，请检查 Agent、模型连接和运行结果。"
        finally:
            self.runs.pop(row.id, None)
            self.stopping.discard(row.id)
            with self.factory() as session, write_transaction(session):
                task = self.get(session, row.id)
                task.status, task.last_error = status, error

    async def stop(self, task_id):
        with self.factory() as session:
            self.get(session, task_id)
        self.stopping.add(task_id)
        if task_id in self.runs:
            await self.chat.stop(*self.runs[task_id])
        if task_id in self.tasks:
            await self.tasks[task_id]
        return next((r for r in self.listing() if r.id == task_id), None)

    def tick(self, now=None):
        now = now or datetime.now(UTC)
        with self.factory() as session:
            ids = list(
                session.scalars(
                    select(Automation.id).where(
                        Automation.enabled.is_(True),
                        Automation.status != "running",
                        Automation.next_run_at <= now,
                    )
                )
            )
        for task_id in ids:
            self.start(task_id, scheduled=True, now=now)

    async def loop(self):
        while not self.closing:
            try:
                self.tick()
            except Exception:
                # 数据库临时不可用时下次重试，不将查询或参数写入日志。
                pass
            await asyncio.sleep(1)

    def launch(self):
        with self.factory() as session:
            if not inspect(session.bind).has_table("automations"):
                return
            session.rollback()
            with write_transaction(session):
                now = datetime.now(UTC)
                for row in session.scalars(select(Automation)):
                    if row.status == "running":
                        row.status, row.last_error = "failed", "服务退出，任务未完成。"
                    if row.next_run_at.replace(tzinfo=UTC) <= now:
                        row.next_run_at = next_time(row, now)
        self.worker = asyncio.create_task(self.loop())

    async def close(self):
        self.closing = True
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        for _conversation_id, generation_id in list(self.runs.values()):
            self.chat.cancel(generation_id)
        await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)
