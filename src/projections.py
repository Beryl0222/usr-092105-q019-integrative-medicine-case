"""只读投影：从事件流重建教学案各层的当前状态与来路。

投影不做写入校验；所有结论都能回溯到具体事件（event_id + version）。
授权访问判定也在这里给出单一事实来源，供服务层与修订视图共用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .events import parse_dt


def _ts(event: dict) -> str:
    return event["occurred_at"]


@dataclass
class VersionedRecord:
    """一条带完整来路的业务记录。"""

    current: dict[str, Any]
    created_event_id: str
    created_version: int
    history: list[dict[str, Any]] = field(default_factory=list)  # 每次变更的事件

    @property
    def last_event_id(self) -> str:
        return self.history[-1]["event_id"] if self.history else self.created_event_id


@dataclass
class CaseProjection:
    case_id: str
    events: list[dict[str, Any]] = field(default_factory=list)
    release: dict[str, Any] | None = None
    withdrawn: dict[str, Any] | None = None
    expired: dict[str, Any] | None = None
    observations: dict[str, VersionedRecord] = field(default_factory=dict)
    conflicts: dict[str, VersionedRecord] = field(default_factory=dict)
    interaction_flags: dict[str, VersionedRecord] = field(default_factory=dict)
    mechanisms: dict[str, VersionedRecord] = field(default_factory=dict)
    problems: dict[str, VersionedRecord] = field(default_factory=dict)
    plans: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # plan_id -> 按版本提交
    opinions: dict[str, VersionedRecord] = field(default_factory=dict)
    simulations: list[dict[str, Any]] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)
    competency: list[dict[str, Any]] = field(default_factory=list)

    # ---------------------------------------------------------- 授权状态

    @property
    def courses(self) -> list[str]:
        return list(self.release["payload"].get("courses", [])) if self.release else []

    def access_status(self, course_id: str, at: str) -> tuple[bool, str]:
        """判定某课程在 at 时刻能否访问病例。返回（可访问, 原因）。"""
        if self.release is None:
            return False, "病例尚未发布"
        if course_id not in self.release["payload"].get("courses", []):
            return False, "该病例未授权给此课程（同意范围之外）"
        auth = self.release["payload"]["authorization"]
        if parse_dt(at) < parse_dt(auth["valid_from"]):
            return False, "尚未到授权生效日"
        if self.expired is not None and parse_dt(at) >= parse_dt(self.expired["payload"]["effective_at"]):
            return False, f"授权已终止：{self.expired['payload']['reason']}"
        if self.withdrawn is not None and parse_dt(at) >= parse_dt(_ts(self.withdrawn)):
            return False, "教学同意已被撤回"
        if parse_dt(at) >= parse_dt(auth["valid_until"]):
            return False, "授权期限已届满（到期后停止新课程访问）"
        return True, "在授权期与同意范围内"

    def is_active(self, at: str) -> bool:
        """病例本身（任一课程）是否仍在授权期。"""
        if self.release is None:
            return False
        auth = self.release["payload"]["authorization"]
        if self.expired is not None and parse_dt(at) >= parse_dt(self.expired["payload"]["effective_at"]):
            return False
        return parse_dt(auth["valid_from"]) <= parse_dt(at) < parse_dt(auth["valid_until"])

    # ---------------------------------------------------------- 查询助手

    def plan_revision(self, plan_id: str, revision: int) -> dict[str, Any] | None:
        for submission in self.plans.get(plan_id, []):
            if submission["payload"]["revision"] == revision:
                return submission
        return None

    def latest_revision(self, plan_id: str) -> int:
        revs = [s["payload"]["revision"] for s in self.plans.get(plan_id, [])]
        return max(revs) if revs else 0

    def opinions_targeting(self, kind: str, target_id: str) -> list[dict[str, Any]]:
        out = []
        for rec in self.opinions.values():
            t = rec.current.get("target", {})
            if t.get("kind") == kind and t.get("id") == target_id:
                out.append(rec.current | {"event_id": rec.last_event_id})
        return out

    def grade_evidence(self) -> list[dict[str, Any]]:
        """按到期保留规则返回成绩证据视图。"""
        rule = self.expired["payload"].get("retention", {}).get("grade_evidence") if self.expired else None
        evidence = []
        for ev in self.competency:
            p = ev["payload"]
            item = {
                "evaluation_id": p["evaluation_id"],
                "course_id": p["course_id"],
                "plan_revision": p["plan_revision"],
                "dimensions": p["dimensions"],
                "event_id": ev["event_id"],
                "retention_grade": rule or "retain_full",
            }
            if rule == "retain_anonymized":
                # 保留成绩证据本身，但切断与可识别学生的直接关联，只留学号级假名；
                # 假名由病例与学号稳定派生（不使用进程随机哈希），便于跨学年核对又不可逆推姓名
                import hashlib
                digest = hashlib.sha256(f"{self.case_id}|{p['student_id']}".encode("utf-8")).hexdigest()
                item["student_pseudonym"] = f"STU-{int(digest[:8], 16) % 10_000_000:07d}"
            elif rule == "delete_evidence":
                continue  # 读模型与导出边界不再呈现（追加存储中的处置由机构保留策略执行）
            else:
                item["student_id"] = p["student_id"]
            evidence.append(item)
        return evidence


class Projection:
    """从 EventStore 的事件流构建全部病例投影。"""

    def __init__(self) -> None:
        self._cases: dict[str, CaseProjection] = {}

    def rebuild(self, events: list[dict[str, Any]]) -> dict[str, CaseProjection]:
        self._cases = {}
        for event in sorted(events, key=lambda e: (e["occurred_at"], e["event_id"])):
            self._apply(event)
        return dict(self._cases)

    def cases(self) -> dict[str, CaseProjection]:
        return dict(self._cases)

    def case(self, case_id: str) -> CaseProjection:
        if case_id not in self._cases:
            self._cases[case_id] = CaseProjection(case_id=case_id)
        return self._cases[case_id]

    def apply(self, event: dict[str, Any]) -> None:
        """增量应用一条已被存储接受的事件。"""
        self._apply(event)

    # ---------------------------------------------------------- 折叠

    def _apply(self, event: dict[str, Any]) -> None:
        etype = event["event_type"]
        atype = event["aggregate_type"]
        p = event.get("payload")

        if atype == "teaching_case":
            case_id = event["aggregate_id"]
            cp = self.case(case_id)
            cp.events.append(event)
            if etype == "CASE_RELEASED":
                cp.release = event
            elif etype == "CONSENT_WITHDRAWN":
                cp.withdrawn = event
            elif etype == "ACCESS_EXPIRED":
                cp.expired = event
            return

        if not isinstance(p, dict) or not p.get("case_id"):
            return
        cp = self.case(p["case_id"])
        cp.events.append(event)

        if etype == "OBSERVATION_ADDED":
            cp.observations[p["observation_id"]] = VersionedRecord(
                current=p, created_event_id=event["event_id"], created_version=event["version"],
                history=[event],
            )
        elif etype == "OBSERVATION_CORRECTED":
            rec = cp.observations.get(p["observation_id"])
            if rec is not None:
                rec.current = {**rec.current, **p["patch"]}
                rec.history.append(event)
        elif etype == "CONFLICT_IDENTIFIED":
            cp.conflicts[p["conflict_id"]] = VersionedRecord(
                current=p, created_event_id=event["event_id"], created_version=event["version"], history=[event])
        elif etype == "INTERACTION_FLAGGED":
            cp.interaction_flags[p["flag_id"]] = VersionedRecord(
                current=p, created_event_id=event["event_id"], created_version=event["version"], history=[event])
        elif etype == "MECHANISM_PROPOSED":
            cp.mechanisms[p["mechanism_id"]] = VersionedRecord(
                current=p, created_event_id=event["event_id"], created_version=event["version"], history=[event])
        elif etype == "PROBLEM_FORMULATED":
            cp.problems[p["problem_id"]] = VersionedRecord(
                current=p, created_event_id=event["event_id"], created_version=event["version"], history=[event])
        elif etype == "PLAN_SUBMITTED":
            cp.plans.setdefault(p["plan_id"], []).append(event)
        elif etype == "OPINION_RECORDED":
            cp.opinions[p["opinion_id"]] = VersionedRecord(
                current=p, created_event_id=event["event_id"], created_version=event["version"], history=[event])
        elif etype == "OPINION_CORRECTED":
            rec = cp.opinions.get(p["opinion_id"])
            if rec is not None:
                rec.current = {**rec.current, **p["patch"]}
                rec.history.append(event)
        elif etype == "SIMULATION_RECORDED":
            cp.simulations.append(event)
        elif etype == "CASE_REVIEWED":
            cp.reviews.append(event)
        elif etype == "COMPETENCY_EVALUATED":
            cp.competency.append(event)
