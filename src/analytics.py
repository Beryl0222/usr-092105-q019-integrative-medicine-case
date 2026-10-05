"""课程负责人视角的教学分析。

核心问题：教学是否仍只是把两套术语拼在一起？这里用真实决策变化
回答，而不是用主观印象：

- 共同解释率：问题表述同时连接西医与中医观察记录的比例；
- 取舍有据率：治疗取舍引用事实层记录（而非空泛术语）的比例；
- 拼贴指数：1 减去上述两者的均值，越高越像“术语拼贴”。

指标按方案版本展开成趋势，进步与否由版本间变化判断。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.events import Event
from src.services import Projection

_JOINT_TRADITIONS = {"biomedicine", "tcm"}


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def version_metrics(proj: Projection, case_id: str, plan_event: Event) -> dict[str, Any]:
    """计算某一版方案提交时刻的整合指标。"""
    at = _parse(plan_event.occurred_at)
    observations = [o for o in proj.observations.get(case_id, []) if _parse(o["occurred_at"]) <= at]
    obs_by_id = {o["obs_id"]: o for o in observations}

    problems = [o for o in observations if o["kind"] == "problem_statement"]
    joint = 0
    for problem in problems:
        traditions = {
            (obs_by_id.get(ref) or {}).get("tradition")
            for ref in problem.get("linked_observations") or []
        }
        if _JOINT_TRADITIONS <= traditions:
            joint += 1
    joint_ratio = joint / len(problems) if problems else 0.0

    decisions = plan_event.payload.get("decisions", [])
    grounded = 0
    for decision in decisions:
        refs = (decision.get("rationale") or {}).get("references") or []
        if any(r.get("id") in obs_by_id for r in refs):
            grounded += 1
    grounding_ratio = grounded / len(decisions) if decisions else 0.0

    integration = (joint_ratio + grounding_ratio) / 2
    return {
        "revision": plan_event.payload.get("revision"),
        "occurred_at": plan_event.occurred_at,
        "problem_count": len(problems),
        "joint_explanation_ratio": round(joint_ratio, 3),
        "decision_grounding_ratio": round(grounding_ratio, 3),
        "integration_score": round(integration, 3),
        "juxtaposition_index": round(1 - integration, 3),
    }


def plan_progress(proj: Projection, case_id: str, plan_id: str) -> list[dict[str, Any]]:
    """同一学生各版方案的指标序列，用于观察学习进步。"""
    return [version_metrics(proj, case_id, e) for e in proj.plan_revisions(plan_id)]


def course_report(proj: Projection, course_id: str) -> dict[str, Any]:
    """课程负责人报告：按学生汇总趋势，并标出仍停留在术语拼贴的方案。"""
    students = []
    for plan_id, events in sorted(proj.plans.items()):
        revisions = [e for e in events if e.event_type == "PLAN_SUBMITTED"]
        if not revisions or revisions[0].payload.get("course_id") != course_id:
            continue
        case_id = revisions[0].payload["case_id"]
        progress = plan_progress(proj, case_id, plan_id)
        first, last = progress[0], progress[-1]
        improving = last["juxtaposition_index"] < first["juxtaposition_index"]
        students.append(
            {
                "plan_id": plan_id,
                "student_id": revisions[0].payload.get("student_id"),
                "case_id": case_id,
                "revisions": progress,
                "first_juxtaposition": first["juxtaposition_index"],
                "latest_juxtaposition": last["juxtaposition_index"],
                "improving": improving,
                "still_juxtaposing": last["juxtaposition_index"] > 0.5 and not improving,
            }
        )
    return {
        "course_id": course_id,
        "student_count": len(students),
        "students": students,
        "flagged_plans": [s["plan_id"] for s in students if s["still_juxtaposing"]],
    }
