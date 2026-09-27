"""Run 摘要、真实 Runtime 事件持久化与只读查询。"""

import json
import math
import re
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert

from app.models import (
    ChatGeneration,
    ChatMessage,
    EvaluationTaskCase,
    LanguageModel,
    RunEvent,
    RunEventPayload,
)
from app.repositories.language_models import write_transaction
from app.schemas.runs import (
    RunAgentOption,
    RunDetail,
    RunEventPayloadView,
    RunEventView,
    RunMetrics,
    RunModelOption,
    RunPage,
    RunView,
)
from app.services.agent_runtime import RuntimeEvent

_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|authorization|cookie|password|secret|credential|access[_-]?token)", re.I
)
_AUTH = re.compile(r"(?i)(authorization\s*[:=]\s*|bearer\s+)[^\s,;]+")
_UNIX_PATH = re.compile(r"(?<![\w.])/(?:Users|home|private|var/folders)/[^\s\"'<>]+")
_WINDOWS_PATH = re.compile(r"(?i)(?<![\w])(?:[a-z]:\\Users\\)[^\s\"'<>]+")
_PAYLOAD_LIMIT = 128 * 1024

STATUS_TO_PUBLIC = {
    "generating": "running",
    "completed": "success",
    "limit_reached": "partial",
    "failed": "failed",
    "cancelled": "cancelled",
}
PUBLIC_TO_STATUS = {value: key for key, value in STATUS_TO_PUBLIC.items()}


def _safe_string(value: str) -> str:
    value = _AUTH.sub("[认证信息已隐藏]", value)
    value = _UNIX_PATH.sub("[路径已隐藏]", value)
    return _WINDOWS_PATH.sub("[路径已隐藏]", value)


def safe_value(value, field=""):
    """写入前的最后一道统一脱敏；Runtime 的已知密钥脱敏仍先执行。"""
    if _SENSITIVE_KEY.search(field):
        return "[已隐藏]"
    if isinstance(value, dict):
        return {str(key): safe_value(item, str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_value(item) for item in value]
    if isinstance(value, str):
        return _safe_string(value)
    return value


def _preview(value) -> str:
    if isinstance(value, dict) and "value" in value:
        value = value["value"]
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = " ".join(text.split())
    return text[:240] + ("…" if len(text) > 240 else "")


def split_event_data(event: RuntimeEvent):
    data = safe_value(event.data)
    payload = {}
    if event.type == "tool_start" and "input" in data:
        payload["input"] = data.pop("input")
        data["input_summary"] = _preview(payload["input"])
    if event.type == "tool_result" and "result" in data:
        payload["result"] = data.pop("result")
    if event.type == "text_delta":
        content = data.pop("content", "")
        data = {
            "content_length": len(content),
            "has_visible_content": bool(content.strip()),
        }
    if payload:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > _PAYLOAD_LIMIT:
            payload = {"notice": "详细载荷超过 128 KiB，未保存。"}
    return data, payload or None


def _event_time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
        return result if result.tzinfo else result.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return datetime.now(UTC)


class RunStore:
    def __init__(self, factory):
        self.factory = factory

    @staticmethod
    def apply_pricing_snapshot(run: ChatGeneration, model: LanguageModel) -> None:
        """Run 创建时固定计价配置，后续修改模型价格不影响历史记录。"""
        run.pricing_snapshot = {
            "currency": model.pricing_currency,
            "unit_tokens": model.price_unit_tokens,
            "input_price": model.input_price,
            "output_price": model.output_price,
            "cached_input_price": model.cached_input_price,
        }
        run.cost_status = "unknown"

    @staticmethod
    def refresh_cost(run: ChatGeneration) -> None:
        snapshot = run.pricing_snapshot
        if run.usage_report_count == 0 or not isinstance(snapshot, dict):
            run.cost, run.cost_status = None, "unknown"
            return
        if not run.usage_complete or run.usage_report_count != run.model_call_count:
            run.cost, run.cost_status = None, "incomplete"
            return
        unit = snapshot.get("unit_tokens")
        prompt, output, cached = run.input_tokens, run.output_tokens, run.cached_input_tokens or 0
        if (
            type(unit) is not int
            or unit < 1
            or cached < 0
            or prompt < cached
            or prompt < 0
            or output < 0
        ):
            run.cost, run.cost_status = None, "incomplete"
            return
        components = (
            (prompt - cached, snapshot.get("input_price")),
            (cached, snapshot.get("cached_input_price")),
            (output, snapshot.get("output_price")),
        )
        if any(tokens and not isinstance(price, (int, float)) for tokens, price in components):
            run.cost, run.cost_status = None, "unknown"
            return
        run.cost = round(sum(tokens * float(price or 0) / unit for tokens, price in components), 12)
        run.cost_status = "complete"

    def record(self, run_id: str, event: RuntimeEvent):
        if event.run_id != run_id:
            raise RuntimeError("runtime run id mismatch")
        data, payload = split_event_data(event)
        occurred_at = _event_time(event.occurred_at)
        with self.factory() as session, write_transaction(session):
            statement = (
                insert(RunEvent)
                .values(
                    run_id=run_id,
                    sequence=event.sequence,
                    type=event.type,
                    round=event.round,
                    call_id=event.call_id,
                    occurred_at=occurred_at,
                    data=data,
                    has_payload=payload is not None,
                )
                .on_conflict_do_nothing(index_elements=["run_id", "sequence"])
            )
            if session.execute(statement).rowcount == 0:
                return
            if payload is not None:
                session.add(
                    RunEventPayload(run_id=run_id, sequence=event.sequence, payload=payload)
                )
            run = session.get(ChatGeneration, run_id)
            if run is None:
                raise RuntimeError("run record missing")
            if event.type == "model_start":
                run.model_call_count += 1
            elif event.type == "model_end":
                usage = data.get("usage")
                if isinstance(usage, dict) and any(
                    type(usage.get(key)) is int
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                ):
                    run.usage_report_count += 1
                    prompt = usage.get("prompt_tokens")
                    completion = usage.get("completion_tokens")
                    total = usage.get("total_tokens")
                    cached = usage.get("cached_input_tokens")
                    if type(prompt) is int:
                        run.input_tokens += prompt
                    if type(completion) is int:
                        run.output_tokens += completion
                    if type(total) is int:
                        run.total_tokens += total
                    elif type(prompt) is int and type(completion) is int:
                        run.total_tokens += prompt + completion
                    if type(cached) is int:
                        run.cached_input_tokens = (run.cached_input_tokens or 0) + cached
                    if type(prompt) is not int or type(completion) is not int:
                        run.usage_complete = False
                else:
                    run.usage_complete = False
            elif event.type == "tool_result" and data.get("executed") is True:
                run.tool_call_count += 1
            elif (
                event.type == "text_delta"
                and data.get("has_visible_content")
                and run.first_output_ms is None
            ):
                run.first_output_ms = max(
                    0,
                    int((occurred_at - run.created_at.replace(tzinfo=UTC)).total_seconds() * 1000),
                )
            elif event.type == "run_end":
                run.status = data.get("status", "failed")
                run.end_reason = str(data.get("reason") or "运行已结束。")[:500]
                run.ended_at = occurred_at
                run.duration_ms = max(
                    0,
                    int((occurred_at - run.created_at.replace(tzinfo=UTC)).total_seconds() * 1000),
                )
                if run.status != "completed":
                    run.error = run.end_reason
                self.refresh_cost(run)

    def mark_save_failed(self, run_id: str):
        """Runtime 已结束但最终正文未可靠保存时，Run 仍以应用最终结果为准。"""
        reason = "回复保存失败，内容尚未可靠保存。"
        with self.factory() as session, write_transaction(session):
            run = session.get(ChatGeneration, run_id)
            if run is None:
                return
            now = datetime.now(UTC)
            run.status = "failed"
            run.error = reason
            run.end_reason = reason
            run.ended_at = now
            run.duration_ms = max(
                0,
                int((now - run.created_at.replace(tzinfo=UTC)).total_seconds() * 1000),
            )
            ended = session.scalar(
                select(RunEvent).where(
                    RunEvent.run_id == run_id,
                    RunEvent.type == "run_end",
                )
            )
            if ended is not None:
                ended.data = {**ended.data, "status": "failed", "reason": reason}

    @staticmethod
    def view(row: ChatGeneration) -> RunView:
        usage_status = (
            "unknown"
            if row.usage_report_count == 0
            else "complete"
            if row.usage_complete and row.usage_report_count == row.model_call_count
            else "incomplete"
        )
        has_usage = row.usage_report_count > 0
        return RunView(
            id=row.id,
            conversation_id=row.conversation_id,
            status=STATUS_TO_PUBLIC.get(row.status, "failed"),
            agent_id=row.agent_id,
            agent_name=row.agent_name,
            model_id=row.model_id,
            model_name=row.model_name,
            model_identifier=row.model_identifier,
            started_at=row.created_at,
            ended_at=row.ended_at,
            duration_ms=row.duration_ms,
            model_call_count=row.model_call_count,
            tool_call_count=row.tool_call_count,
            input_tokens=row.input_tokens if has_usage else None,
            output_tokens=row.output_tokens if has_usage else None,
            total_tokens=row.total_tokens if has_usage else None,
            cached_input_tokens=row.cached_input_tokens,
            cost=row.cost,
            cost_currency=(row.pricing_snapshot or {}).get("currency")
            if isinstance(row.pricing_snapshot, dict)
            else None,
            cost_status=row.cost_status
            if row.cost_status in {"complete", "incomplete", "unknown"}
            else "unknown",
            usage_status=usage_status,
            first_output_ms=row.first_output_ms,
            end_reason=row.end_reason,
            error_summary=(row.error[:240] if row.status == "failed" and row.error else None),
        )

    @staticmethod
    def metrics(rows: list[ChatGeneration], tool_errors: int) -> RunMetrics:
        completed = [row for row in rows if row.status != "generating"]
        successful = [row for row in completed if row.status == "completed"]
        durations = sorted(row.duration_ms for row in completed if row.duration_ms is not None)
        first_output = [row.first_output_ms for row in rows if row.first_output_ms is not None]
        known_tokens = [row.total_tokens for row in rows if row.usage_report_count > 0]
        complete_costs = [
            row.cost for row in rows if row.cost_status == "complete" and row.cost is not None
        ]
        currencies = {
            (row.pricing_snapshot or {}).get("currency")
            for row in rows
            if row.cost_status == "complete" and isinstance(row.pricing_snapshot, dict)
        }
        tool_calls = sum(row.tool_call_count for row in rows)
        # P95 使用最近样本的 nearest-rank，样本不足时不伪造精度。
        p95 = durations[max(0, math.ceil(len(durations) * 0.95) - 1)] if durations else None
        return RunMetrics(
            total=len(rows),
            success_rate=round(len(successful) / len(completed) * 100, 2) if completed else None,
            p95_duration_ms=p95,
            first_output_ms=round(sum(first_output) / len(first_output)) if first_output else None,
            total_tokens=sum(known_tokens) if known_tokens else None,
            tool_error_rate=round(tool_errors / tool_calls * 100, 2) if tool_calls else None,
            total_cost=(
                round(sum(complete_costs), 12) if complete_costs and len(currencies) == 1 else None
            ),
            cost_currency=next(iter(currencies)) if len(currencies) == 1 else None,
            incomplete_cost_runs=sum(1 for row in rows if row.cost_status != "complete"),
        )

    def listing(
        self,
        page: int,
        page_size: int,
        status: str | None,
        agent_id: str | None,
        model_id: str | None = None,
        source: str | None = None,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
    ):
        with self.factory() as session:
            filters = []
            if status:
                filters.append(ChatGeneration.status == PUBLIC_TO_STATUS[status])
            if agent_id:
                filters.append(ChatGeneration.agent_id == agent_id)
            if model_id:
                filters.append(ChatGeneration.model_id == model_id)
            if started_after:
                filters.append(ChatGeneration.created_at >= started_after)
            if started_before:
                filters.append(ChatGeneration.created_at < started_before)
            evaluation_runs = select(EvaluationTaskCase.run_id).where(
                EvaluationTaskCase.run_id.is_not(None)
            )
            if source == "evaluation":
                filters.append(ChatGeneration.id.in_(evaluation_runs))
            elif source == "chat":
                filters.append(ChatGeneration.id.not_in(evaluation_runs))
            total = session.scalar(select(func.count()).select_from(ChatGeneration).where(*filters))
            rows = list(
                session.scalars(
                    select(ChatGeneration)
                    .where(*filters)
                    .order_by(ChatGeneration.created_at.desc(), ChatGeneration.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            # 选项只读一条分组查询，避免列表页随着筛选器数量增加查询次数。
            options = list(
                session.execute(
                    select(
                        ChatGeneration.agent_id,
                        func.max(ChatGeneration.agent_name),
                        ChatGeneration.model_id,
                        func.max(ChatGeneration.model_name),
                    )
                    .group_by(ChatGeneration.agent_id, ChatGeneration.model_id)
                    .order_by(func.max(ChatGeneration.agent_name), ChatGeneration.agent_id)
                )
            )
            agents = [
                RunAgentOption(id=id, name=name)
                for id, name in {(row[0], row[1]) for row in options}
            ]
            agents.sort(key=lambda item: (item.name, item.id))
            models = [
                RunModelOption(id=id, name=name or "模型快照缺失")
                for id, name in {(row[2], row[3]) for row in options}
            ]
            models.sort(key=lambda item: (item.name, item.id or ""))
            return RunPage(
                items=[self.view(row) for row in rows],
                total=total or 0,
                page=page,
                page_size=page_size,
                agents=agents,
                models=models,
                # 聚合口径与当前明细一致，分页时只表示当前页样本，避免为面板额外
                # 扫描全部运行记录影响列表读取性能。
                metrics=self.metrics(rows, 0),
            )

    def delete(self, run_id: str):
        with self.factory() as session, write_transaction(session):
            row = session.get(ChatGeneration, run_id)
            if row is None:
                raise HTTPException(404, "运行记录不存在。")
            if row.status == "generating":
                raise HTTPException(409, "运行仍在进行，停止后才能删除记录。")
            session.execute(delete(RunEventPayload).where(RunEventPayload.run_id == run_id))
            session.execute(delete(RunEvent).where(RunEvent.run_id == run_id))
            session.delete(row)

    def detail(self, run_id: str):
        with self.factory() as session:
            row = session.get(ChatGeneration, run_id)
            if row is None:
                raise HTTPException(404, "运行记录不存在。")
            events = list(
                session.scalars(
                    select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.sequence)
                )
            )
            message = session.get(ChatMessage, row.assistant_message_id)
            return RunDetail(
                **self.view(row).model_dump(),
                events=[RunEventView.model_validate(event) for event in events],
                final_answer=safe_value(message.content) if message else None,
            )

    def payload(self, run_id: str, sequence: int):
        with self.factory() as session:
            event = session.get(RunEvent, (run_id, sequence))
            if event is None:
                raise HTTPException(404, "运行事件不存在。")
            payload = session.get(RunEventPayload, (run_id, sequence))
            if payload is None:
                raise HTTPException(404, "此事件没有详细载荷。")
            return RunEventPayloadView(run_id=run_id, sequence=sequence, payload=payload.payload)

    def persisted_events_since(self, run_id: str, sequence: int):
        with self.factory() as session:
            rows = list(
                session.scalars(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.sequence > sequence)
                    .order_by(RunEvent.sequence)
                )
            )
            return [
                RuntimeEvent(
                    row.run_id,
                    row.sequence,
                    row.type,
                    row.round,
                    row.call_id,
                    row.data,
                    row.occurred_at.replace(tzinfo=UTC).isoformat(),
                )
                for row in rows
            ]
