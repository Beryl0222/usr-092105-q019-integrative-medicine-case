"""事件存储：只追加、幂等、版本连续。

存储不执行业务授权（那是 SystemOfRecord 的职责），它保证：
- 同一 aggregate_id 内 version 从 1 开始连续；
- event_id 全局唯一，来源系统用同一 event_id 重试且内容一致时幂等接受，
  内容不一致时拒绝（防止伪装重试的改写）；
- 事件一经接受不可变、不可删除。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .errors import ConcurrencyError, ValidationError
from .events import validate_event


class EventStore:
    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._by_id: dict[str, dict[str, Any]] = {}
        self._aggregates: dict[str, list[dict[str, Any]]] = {}

    # ------------------------------------------------------------ 写入

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        errors = validate_event(event)
        if errors:
            raise ValidationError(errors)

        eid = event["event_id"]
        existing = self._by_id.get(eid)
        if existing is not None:
            if existing == event:
                return event  # 幂等重试
            raise ConcurrencyError(
                f"事件标识 {eid} 已存在但内容不一致：重试必须沿用原事件内容"
            )

        stream = self._aggregates.setdefault(event["aggregate_id"], [])
        expected = len(stream) + 1
        if event["version"] != expected:
            raise ConcurrencyError(
                f"聚合 {event['aggregate_id']} 版本应为 {expected}，收到 {event['version']}"
            )

        self._events.append(event)
        self._by_id[eid] = event
        stream.append(event)
        return event

    def append_many(self, events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.append(e) for e in events]

    # ------------------------------------------------------------ 读取

    def all_events(self) -> list[dict[str, Any]]:
        """按接受顺序（全局限序）返回全部事件。"""
        return list(self._events)

    def stream(self, aggregate_id: str) -> list[dict[str, Any]]:
        return list(self._aggregates.get(aggregate_id, []))

    def exists(self, event_id: str) -> bool:
        return event_id in self._by_id

    def get(self, event_id: str) -> dict[str, Any] | None:
        return self._by_id.get(event_id)

    def case_events(self, case_id: str) -> list[dict[str, Any]]:
        """按全局顺序返回某病例四层的全部事件。"""
        return [
            e
            for e in self._events
            if e["aggregate_id"] == case_id
            or (isinstance(e.get("payload"), dict) and e["payload"].get("case_id") == case_id)
        ]

    # ------------------------------------------------------------ JSONL 持久化（联调用）

    def export_jsonl(self, path: str | Path) -> int:
        path = Path(path)
        with path.open("w", encoding="utf-8") as f:
            for e in self._events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        return len(self._events)

    def import_jsonl(self, path: str | Path) -> int:
        n = 0
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                self.append(json.loads(line))
                n += 1
        return n
