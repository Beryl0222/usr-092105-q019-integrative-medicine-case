"""课程间事件同步。

课程之间通过 teaching_case、clinical_observation、student_plan、
faculty_feedback 四类聚合的事件流交换记录。导出结果为符合公共信封
约定的字典列表；导入端先做信封校验，再按 event_id 幂等落库，
来源系统重试时沿用原事件标识即可安全重放。
"""

from __future__ import annotations

from typing import Any

from src.events import Event, EventStore, VersionConflictError
from src.validator import validate_event


def export_events(store: EventStore, aggregate_type: str | None = None) -> list[dict[str, Any]]:
    """导出事件信封；可按聚合类型过滤。"""
    return [
        event.to_dict()
        for event in store
        if aggregate_type is None or event.aggregate_type == aggregate_type
    ]


def import_events(store: EventStore, records: list[dict[str, Any]]) -> dict[str, Any]:
    """导入事件信封。重复 event_id 跳过，信封错误或版本冲突逐条报告。"""
    imported: list[str] = []
    skipped_duplicates: list[str] = []
    errors: list[dict[str, Any]] = []
    for record in records:
        validation = validate_event(record)
        if validation:
            errors.append({"event_id": record.get("event_id"), "errors": validation})
            continue
        if store.get(record["event_id"]) is not None:
            skipped_duplicates.append(record["event_id"])
            continue
        try:
            store.append(Event.from_dict(record))
            imported.append(record["event_id"])
        except VersionConflictError as exc:
            errors.append({"event_id": record.get("event_id"), "errors": [str(exc)]})
    return {
        "imported": imported,
        "skipped_duplicates": skipped_duplicates,
        "errors": errors,
    }
