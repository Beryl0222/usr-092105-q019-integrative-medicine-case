"""融合医学临床教学案的应用服务。

分层保存结构（四类聚合流）：

- ``teaching_case``：脱敏病例与教学同意、授权到期。
- ``clinical_observation``：症状与检查事实、证候观察、问题表述、
  药物相互作用、候选机制（payload.kind 区分层次）。
- ``student_plan``：学生各版决策（payload.revision 递增）与模拟结果。
- ``faculty_feedback``：跨学科意见、临床回顾与能力反馈；不同教师的
  分歧以追加方式并存，互不覆盖。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src import rules
from src.events import Event, EventStore


class DomainError(Exception):
    """携带可直接展示给师生的中文错误列表。"""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("；".join(errors))


class AccessDenied(Exception):
    """访问被授权规则拒绝。"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


class Projection:
    """事件流的重放视图，供规则校验、修订比较与课程分析使用。"""

    def __init__(self, store: EventStore) -> None:
        self.cases: dict[str, dict[str, Any]] = {}
        self.observations: dict[str, list[dict[str, Any]]] = {}
        self.plans: dict[str, list[Event]] = {}
        self.feedback: dict[str, list[Event]] = {}
        for event in store:
            self._apply(event)

    def _apply(self, event: Event) -> None:
        if event.aggregate_type == "teaching_case":
            case = self.cases.setdefault(event.aggregate_id, {"consent": None, "released": False, "expired": False})
            if event.event_type == "CASE_RELEASED":
                case["released"] = True
                case["consent"] = event.payload.get("consent")
            elif event.event_type == "CONSENT_UPDATED":
                case["consent"] = event.payload.get("consent")
            elif event.event_type == "ACCESS_EXPIRED":
                case["expired"] = True
        elif event.aggregate_type == "clinical_observation":
            item = dict(event.payload)
            item.update(
                obs_id=event.payload.get("obs_id"),
                occurred_at=event.occurred_at,
                event_id=event.event_id,
                stream_version=event.version,
            )
            self.observations.setdefault(event.aggregate_id, []).append(item)
        elif event.aggregate_type == "student_plan":
            self.plans.setdefault(event.aggregate_id, []).append(event)
        elif event.aggregate_type == "faculty_feedback":
            self.feedback.setdefault(event.aggregate_id, []).append(event)

    def observation_index(self, case_id: str) -> dict[str, dict[str, Any]]:
        return {o["obs_id"]: o for o in self.observations.get(case_id, [])}

    def plan_revisions(self, plan_id: str) -> list[Event]:
        return [e for e in self.plans.get(plan_id, []) if e.event_type == "PLAN_SUBMITTED"]

    def known_reference_ids(self, case_id: str, plan_id: str) -> set[str]:
        """取舍依据可引用的标识集合：事实层各条记录与已签署的教师意见。"""
        ids = {o["obs_id"] for o in self.observations.get(case_id, [])}
        ids.update(e.event_id for e in self.feedback.get(plan_id, []))
        return ids


class TeachingCaseSystem:
    """教学案系统门面。clock 可注入以便测试。"""

    def __init__(
        self,
        store: EventStore,
        clock: Callable[[], datetime] = _utcnow,
        grants_path: str | Path | None = None,
    ) -> None:
        self.store = store
        self.clock = clock
        self._grants_path = Path(grants_path) if grants_path else None
        self._grants: dict[tuple[str, str], str] = {}
        if self._grants_path and self._grants_path.exists():
            raw = json.loads(self._grants_path.read_text(encoding="utf-8"))
            self._grants = {(g["case_id"], g["course_id"]): g["granted_at"] for g in raw}

    # ------------------------------------------------------------------ 工具

    def _now_iso(self) -> str:
        return self.clock().isoformat()

    def _event(
        self,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        summary: str,
        payload: dict[str, Any],
        occurred_at: str | None,
        event_id: str | None,
    ) -> Event:
        return Event(
            event_id=event_id or f"evt-{uuid.uuid4().hex[:12]}",
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            occurred_at=occurred_at or self._now_iso(),
            version=self.store.next_version(aggregate_type, aggregate_id),
            summary=summary,
            payload=payload,
        )

    def _projection(self) -> Projection:
        return Projection(self.store)

    def _require_case(self, proj: Projection, case_id: str) -> dict[str, Any]:
        case = proj.cases.get(case_id)
        if not case or not case["released"]:
            raise DomainError([f"教学案不存在：{case_id}"])
        return case

    def _assert_case_open(self, proj: Projection, case_id: str, at: str) -> None:
        """授权到期后，病例内容冻结：不再接受新的事实、方案或意见事件。"""
        case = self._require_case(proj, case_id)
        consent = case.get("consent") or {}
        valid_until = consent.get("valid_until")
        if valid_until and _parse(at) > _parse(valid_until):
            raise DomainError([f"病例 {case_id} 的教学授权已于 {valid_until} 到期，不再接受新的课程记录"])

    # ---------------------------------------------------------------- 病例与同意

    def release_case(
        self,
        case_id: str,
        summary: str,
        consent: dict[str, Any],
        occurred_at: str | None = None,
        event_id: str | None = None,
    ) -> Event:
        errors = rules.validate_consent(consent)
        if errors:
            raise DomainError(errors)
        event = self._event(
            "CASE_RELEASED", "teaching_case", case_id, summary, {"consent": consent}, occurred_at, event_id
        )
        return self.store.append(event)

    def update_consent(
        self,
        case_id: str,
        summary: str,
        consent: dict[str, Any],
        occurred_at: str | None = None,
        event_id: str | None = None,
    ) -> Event:
        proj = self._projection()
        self._require_case(proj, case_id)
        errors = rules.validate_consent(consent)
        if errors:
            raise DomainError(errors)
        event = self._event(
            "CONSENT_UPDATED", "teaching_case", case_id, summary, {"consent": consent}, occurred_at, event_id
        )
        return self.store.append(event)

    def record_expiry(
        self, case_id: str, summary: str = "教学授权到期", occurred_at: str | None = None, event_id: str | None = None
    ) -> Event:
        proj = self._projection()
        self._require_case(proj, case_id)
        event = self._event("ACCESS_EXPIRED", "teaching_case", case_id, summary, {}, occurred_at, event_id)
        return self.store.append(event)

    # ---------------------------------------------------------------- 观察与解释层

    def add_observation(
        self,
        case_id: str,
        obs_id: str,
        kind: str,
        text: str,
        summary: str | None = None,
        occurred_at: str | None = None,
        event_id: str | None = None,
        **extra: Any,
    ) -> Event:
        """登记一条事实层记录。

        kind 区分层次：symptom / exam_result / pattern_observation /
        problem_statement / drug_interaction / candidate_mechanism。
        """
        proj = self._projection()
        at = occurred_at or self._now_iso()
        self._assert_case_open(proj, case_id, at)
        if kind not in rules.OBSERVATION_KINDS:
            raise DomainError([f"未知观察类型：{kind}"])
        if proj.observation_index(case_id).get(obs_id):
            raise DomainError([f"观察标识已存在：{obs_id}"])

        payload: dict[str, Any] = {"obs_id": obs_id, "kind": kind, "text": text, **extra}
        errors: list[str] = []
        if kind == "candidate_mechanism":
            errors.extend(rules.validate_mechanism(payload))
        elif kind == "drug_interaction":
            errors.extend(rules.validate_interaction(payload))
        elif kind == "problem_statement":
            errors.extend(rules.validate_problem(payload))
        for ref in payload.get("linked_observations") or []:
            if ref not in proj.observation_index(case_id):
                errors.append(f"问题表述引用了不存在的观察记录：{ref}")
        if errors:
            raise DomainError(errors)

        event = self._event(
            "OBSERVATION_ADDED",
            "clinical_observation",
            case_id,
            summary or f"登记{kind}：{text[:20]}",
            payload,
            at,
            event_id,
        )
        return self.store.append(event)

    # ---------------------------------------------------------------- 学生方案

    @staticmethod
    def plan_id(case_id: str, student_id: str) -> str:
        return f"{case_id}::{student_id}"

    def submit_plan(
        self,
        case_id: str,
        student_id: str,
        course_id: str,
        decisions: list[dict[str, Any]],
        note: str = "",
        summary: str | None = None,
        occurred_at: str | None = None,
        event_id: str | None = None,
    ) -> Event:
        """提交一版方案。每次取舍必须说明合并、保留或排除的依据。"""
        proj = self._projection()
        at = occurred_at or self._now_iso()
        self._assert_case_open(proj, case_id, at)
        allowed, reason = self.can_access(case_id, course_id, at=at, purpose="learning")
        if not allowed:
            raise AccessDenied(reason)

        plan_id = self.plan_id(case_id, student_id)
        revision = len(proj.plan_revisions(plan_id)) + 1
        payload = {
            "case_id": case_id,
            "student_id": student_id,
            "course_id": course_id,
            "revision": revision,
            "note": note,
            "decisions": decisions,
        }
        errors = rules.validate_plan_payload(payload)
        known = proj.known_reference_ids(case_id, plan_id)
        for decision in decisions:
            for ref in (decision.get("rationale") or {}).get("references") or []:
                if ref.get("id") not in known:
                    errors.append(f"治疗项目「{decision.get('item')}」的依据引用了不存在的记录：{ref.get('id')}")
        if errors:
            raise DomainError(errors)

        event = self._event(
            "PLAN_SUBMITTED",
            "student_plan",
            plan_id,
            summary or f"{student_id} 提交第 {revision} 版方案",
            payload,
            at,
            event_id,
        )
        return self.store.append(event)

    def record_simulation(
        self,
        case_id: str,
        student_id: str,
        course_id: str,
        scenario: str,
        outcomes: dict[str, Any],
        summary: str | None = None,
        occurred_at: str | None = None,
        event_id: str | None = None,
    ) -> Event:
        proj = self._projection()
        at = occurred_at or self._now_iso()
        self._assert_case_open(proj, case_id, at)
        allowed, reason = self.can_access(case_id, course_id, at=at, purpose="learning")
        if not allowed:
            raise AccessDenied(reason)
        plan_id = self.plan_id(case_id, student_id)
        payload = {"case_id": case_id, "student_id": student_id, "course_id": course_id, "scenario": scenario, "outcomes": outcomes}
        event = self._event(
            "SIMULATION_RECORDED", "student_plan", plan_id, summary or f"记录模拟：{scenario[:20]}", payload, at, event_id
        )
        return self.store.append(event)

    # ---------------------------------------------------------------- 教师意见

    def sign_feedback(
        self,
        case_id: str,
        student_id: str,
        faculty_id: str,
        discipline: str,
        kind: str,
        text: str,
        targets: list[str] | None = None,
        dimensions: list[dict[str, Any]] | None = None,
        summary: str | None = None,
        occurred_at: str | None = None,
        event_id: str | None = None,
    ) -> Event:
        """签署一条教师意见。分歧以追加方式并存，系统不做合并或裁决。"""
        proj = self._projection()
        at = occurred_at or self._now_iso()
        self._assert_case_open(proj, case_id, at)
        if kind not in rules.FEEDBACK_KINDS:
            raise DomainError([f"未知教师意见类型：{kind}"])
        plan_id = self.plan_id(case_id, student_id)
        payload = {
            "case_id": case_id,
            "student_id": student_id,
            "faculty_id": faculty_id,
            "discipline": discipline,
            "kind": kind,
            "text": text,
            "targets": targets or [],
            "dimensions": dimensions or [],
        }
        event = self._event(
            "FEEDBACK_SIGNED",
            "faculty_feedback",
            plan_id,
            summary or f"{faculty_id}（{discipline}）签署{kind}",
            payload,
            at,
            event_id,
        )
        return self.store.append(event)

    # ---------------------------------------------------------------- 授权与保留

    def grant_access(self, case_id: str, course_id: str, at: str | None = None) -> None:
        """向课程开放病例访问。授权到期后不再开放新课程。"""
        proj = self._projection()
        case = self._require_case(proj, case_id)
        at = at or self._now_iso()
        consent = case.get("consent") or {}
        valid_until = consent.get("valid_until")
        if valid_until and _parse(at) > _parse(valid_until):
            raise AccessDenied(f"病例 {case_id} 的教学授权已于 {valid_until} 到期，不能开放新课程访问")
        self._grants[(case_id, course_id)] = at
        self._persist_grants()

    def can_access(
        self, case_id: str, course_id: str, at: str | None = None, purpose: str = "learning"
    ) -> tuple[bool, str]:
        """访问判定。

        - 授权有效期内：已获授权的课程可以学习访问。
        - 授权到期后：停止新课程访问；此前已获授权的课程仅可查阅
          已形成的成绩证据（purpose="grade_evidence"），记录按规则保留。
        """
        proj = self._projection()
        case = proj.cases.get(case_id)
        if not case or not case["released"]:
            return False, f"教学案不存在：{case_id}"
        granted_at = self._grants.get((case_id, course_id))
        if granted_at is None:
            return False, f"课程 {course_id} 未获得病例 {case_id} 的访问授权"
        at = at or self._now_iso()
        consent = case.get("consent") or {}
        valid_until = consent.get("valid_until")
        if not valid_until or _parse(at) <= _parse(valid_until):
            return True, "授权有效期内"
        if _parse(granted_at) <= _parse(valid_until) and purpose == "grade_evidence":
            return True, "授权已到期：仅保留查阅已形成成绩证据"
        return False, f"病例 {case_id} 的教学授权已于 {valid_until} 到期"

    def _persist_grants(self) -> None:
        if not self._grants_path:
            return
        raw = [
            {"case_id": case_id, "course_id": course_id, "granted_at": granted_at}
            for (case_id, course_id), granted_at in sorted(self._grants.items())
        ]
        self._grants_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
