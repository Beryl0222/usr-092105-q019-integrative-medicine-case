"""方案修订的并排比较视图。

查看某次修订时，把四条线索并排呈现，且每条都带来路（事件标识与时间）：

- 新增事实：两版之间进入病例的观察与解释层记录；
- 冲突识别：窗口内新标记的药物相互作用；
- 治疗取舍：各治疗项目在旧版与新版之间的动作变化及依据；
- 教师分歧：窗口内签署的跨学科意见，按对象分组并存呈现。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.events import Event
from src.services import Projection


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _in_window(ts: str, start: datetime, end: datetime) -> bool:
    return start < _parse(ts) <= end


def _decision_index(event: Event) -> dict[str, dict[str, Any]]:
    return {d.get("item"): d for d in event.payload.get("decisions", [])}


def compare_revisions(
    proj: Projection, case_id: str, plan_id: str, from_revision: int, to_revision: int
) -> dict[str, Any]:
    """比较同一学生方案的两个版本，返回结构化并排视图。"""
    revisions = {e.payload.get("revision"): e for e in proj.plan_revisions(plan_id)}
    if from_revision not in revisions or to_revision not in revisions:
        missing = [r for r in (from_revision, to_revision) if r not in revisions]
        raise ValueError(f"方案 {plan_id} 不存在版本：{missing}")
    e_from, e_to = revisions[from_revision], revisions[to_revision]
    start, end = _parse(e_from.occurred_at), _parse(e_to.occurred_at)

    observations = proj.observations.get(case_id, [])
    new_facts = [
        {
            "obs_id": o["obs_id"],
            "kind": o["kind"],
            "text": o["text"],
            "event_id": o["event_id"],
            "occurred_at": o["occurred_at"],
        }
        for o in observations
        if _in_window(o["occurred_at"], start, end)
    ]
    conflicts = [
        {
            "obs_id": o["obs_id"],
            "involves": o.get("involves", []),
            "interaction_kind": o.get("interaction_kind"),
            "text": o["text"],
            "event_id": o["event_id"],
        }
        for o in observations
        if o["kind"] == "drug_interaction" and _in_window(o["occurred_at"], start, end)
    ]

    before, after = _decision_index(e_from), _decision_index(e_to)
    trade_offs = []
    for item in sorted(set(before) | set(after)):
        old, new = before.get(item), after.get(item)
        if old is None or new is None or old.get("action") != new.get("action"):
            trade_offs.append(
                {
                    "item": item,
                    "before": (old or {}).get("action"),
                    "after": (new or {}).get("action"),
                    "rationale": (new or old or {}).get("rationale", {}),
                }
            )

    disagreements = []
    for event in proj.feedback.get(plan_id, []):
        if not _in_window(event.occurred_at, start, end):
            continue
        p = event.payload
        disagreements.append(
            {
                "faculty_id": p.get("faculty_id"),
                "discipline": p.get("discipline"),
                "kind": p.get("kind"),
                "targets": p.get("targets", []),
                "text": p.get("text"),
                "event_id": event.event_id,
                "occurred_at": event.occurred_at,
            }
        )

    return {
        "case_id": case_id,
        "plan_id": plan_id,
        "from_revision": from_revision,
        "to_revision": to_revision,
        "window": {"start": e_from.occurred_at, "end": e_to.occurred_at},
        "new_facts": new_facts,
        "conflicts_identified": conflicts,
        "trade_offs": trade_offs,
        "faculty_disagreements": disagreements,
    }


def render_side_by_side(view: dict[str, Any]) -> str:
    """把并排视图渲染为可读的文本对照表。"""
    lines = [
        f"方案 {view['plan_id']}：第 {view['from_revision']} 版 → 第 {view['to_revision']} 版",
        f"窗口：{view['window']['start']} ～ {view['window']['end']}",
        "",
        "【新增事实】",
    ]
    for f in view["new_facts"]:
        lines.append(f"  + [{f['kind']}] {f['obs_id']}：{f['text']}（来路 {f['event_id']}）")
    if not view["new_facts"]:
        lines.append("  （无）")
    lines.append("")
    lines.append("【冲突识别】")
    for c in view["conflicts_identified"]:
        lines.append(
            f"  ! {c['obs_id']}：{' + '.join(c['involves'])}（{c['interaction_kind']}）{c['text']}（来路 {c['event_id']}）"
        )
    if not view["conflicts_identified"]:
        lines.append("  （无）")
    lines.append("")
    lines.append("【治疗取舍】")
    action_label = {"merge": "合并", "keep": "保留", "exclude": "排除", None: "—"}
    for t in view["trade_offs"]:
        rationale = t["rationale"] or {}
        refs = "、".join(str(r.get("id")) for r in rationale.get("references", [])) or "无引用"
        lines.append(
            f"  * {t['item']}：{action_label[t['before']]} → {action_label[t['after']]}"
            f"｜依据：{rationale.get('text', '')}（引用：{refs}）"
        )
    if not view["trade_offs"]:
        lines.append("  （无变化）")
    lines.append("")
    lines.append("【教师分歧】")
    for d in view["faculty_disagreements"]:
        targets = "、".join(d["targets"]) or "整体方案"
        lines.append(
            f"  · {d['faculty_id']}（{d['discipline']}，{d['kind']}）就 {targets}：{d['text']}"
            f"（来路 {d['event_id']}）"
        )
    if not view["faculty_disagreements"]:
        lines.append("  （无）")
    return "\n".join(lines)
