"""校验领域事件信封的公共字段。"""

from src.events import AGGREGATE_TYPES, EVENT_TYPES

REQUIRED = ("event_id", "event_type", "aggregate_type", "aggregate_id", "occurred_at", "version", "summary")


def validate_event(record: dict) -> list[str]:
    """返回可以直接展示给接入方的中文错误。"""
    errors = [f"缺少字段：{name}" for name in REQUIRED if name not in record]
    if "event_id" in record and (not isinstance(record["event_id"], str) or len(record["event_id"]) < 8):
        errors.append("event_id 至少 8 个字符")
    if "event_type" in record and record["event_type"] not in EVENT_TYPES:
        errors.append(f"未知事件类型：{record['event_type']}")
    if "aggregate_type" in record and record["aggregate_type"] not in AGGREGATE_TYPES:
        errors.append(f"未知聚合类型：{record['aggregate_type']}")
    if "version" in record and (not isinstance(record["version"], int) or record["version"] < 1):
        errors.append("version 必须是正整数")
    if "summary" in record and (not isinstance(record["summary"], str) or len(record["summary"]) < 2):
        errors.append("summary 至少 2 个字符")
    return errors
