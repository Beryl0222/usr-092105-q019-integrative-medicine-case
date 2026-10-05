"""事件信封与仅追加事件存储。

事件由 ``event_id`` 唯一标识；来源系统重试时必须沿用原 ``event_id``，
存储层据此去重，保证同步幂等。``version`` 在同一聚合流内从 1 开始递增。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

EVENT_TYPES = (
    "CASE_RELEASED",
    "CONSENT_UPDATED",
    "ACCESS_EXPIRED",
    "OBSERVATION_ADDED",
    "PLAN_SUBMITTED",
    "SIMULATION_RECORDED",
    "FEEDBACK_SIGNED",
)

AGGREGATE_TYPES = (
    "teaching_case",
    "clinical_observation",
    "student_plan",
    "faculty_feedback",
)


@dataclass(frozen=True)
class Event:
    """一条领域事件。payload 承载分层内容，信封字段保持公共语义。"""

    event_id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    occurred_at: str
    version: int
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        record = {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "occurred_at": self.occurred_at,
            "version": self.version,
            "summary": self.summary,
        }
        record.update(self.payload)
        return record

    @staticmethod
    def from_dict(record: dict[str, Any]) -> "Event":
        envelope_keys = {
            "event_id",
            "event_type",
            "aggregate_type",
            "aggregate_id",
            "occurred_at",
            "version",
            "summary",
        }
        payload = {k: v for k, v in record.items() if k not in envelope_keys}
        return Event(
            event_id=record["event_id"],
            event_type=record["event_type"],
            aggregate_type=record["aggregate_type"],
            aggregate_id=record["aggregate_id"],
            occurred_at=record["occurred_at"],
            version=record["version"],
            summary=record["summary"],
            payload=payload,
        )


class VersionConflictError(ValueError):
    """同一聚合流上出现版本跳跃或冲突。"""


class EventStore:
    """仅追加事件存储，可选 JSONL 持久化。

    - 按 ``event_id`` 去重：重复提交返回已存事件，不产生第二条记录。
    - 每个 ``(aggregate_type, aggregate_id)`` 流的 ``version`` 必须连续递增。
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else None
        self._events: list[Event] = []
        self._by_id: dict[str, Event] = {}
        self._stream_versions: dict[tuple[str, str], int] = {}
        if self._path and self._path.exists():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    self._index(Event.from_dict(json.loads(line)))

    def _index(self, event: Event) -> None:
        key = (event.aggregate_type, event.aggregate_id)
        self._events.append(event)
        self._by_id[event.event_id] = event
        self._stream_versions[key] = max(self._stream_versions.get(key, 0), event.version)

    def append(self, event: Event) -> Event:
        """追加事件；同一 event_id 重试时返回原事件（幂等）。"""
        existing = self._by_id.get(event.event_id)
        if existing is not None:
            return existing
        key = (event.aggregate_type, event.aggregate_id)
        expected = self._stream_versions.get(key, 0) + 1
        if event.version != expected:
            raise VersionConflictError(
                f"版本冲突：聚合 {key[0]}/{key[1]} 期望 version={expected}，收到 version={event.version}"
            )
        if self._path:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        self._index(event)
        return event

    def next_version(self, aggregate_type: str, aggregate_id: str) -> int:
        return self._stream_versions.get((aggregate_type, aggregate_id), 0) + 1

    def stream(self, aggregate_type: str, aggregate_id: str) -> list[Event]:
        return [
            e
            for e in self._events
            if e.aggregate_type == aggregate_type and e.aggregate_id == aggregate_id
        ]

    def all(self) -> list[Event]:
        return list(self._events)

    def get(self, event_id: str) -> Event | None:
        return self._by_id.get(event_id)

    def __iter__(self) -> Iterator[Event]:
        return iter(self._events)
