"""方案修订并排视图。

查看某次方案修订时，同屏呈现四条来路：
  新增事实（含证候观察） | 冲突识别 | 治疗取舍（合并/保留/排除/搁置 + 依据） | 教师分歧
每条记录都带来源事件（event_id/version/actor/occurred_at），学习进步可按版本比较，
课程负责人可据真实决策变化判断教学是否仍停留在"两套术语并排抄写"。
"""

from __future__ import annotations

from typing import Any

from .events import parse_dt
from .projections import CaseProjection

_ACTION_CN = {"merged": "合并", "retained": "保留", "excluded": "排除", "deferred": "搁置"}
_SYSTEM_CN = {"western": "西医", "tcm": "中医", "nonpharmacologic": "非药物", "other": "其他"}
_STANCE_CN = {"support": "支持", "concern": "担忧", "disagree": "反对", "alternative": "替代建议"}


def _origin(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event["event_id"],
        "version": event["version"],
        "actor": event["payload"].get("actor", {}),
        "occurred_at": event["occurred_at"],
        "course_id": event["payload"].get("course_id"),
    }


def build_revision_view(case: CaseProjection, plan_id: str, revision: int) -> dict[str, Any]:
    submission = case.plan_revision(plan_id, revision)
    if submission is None:
        raise KeyError(f"方案 {plan_id} 不存在第 {revision} 版")
    submitted_at = parse_dt(submission["occurred_at"])
    prev = case.plan_revision(plan_id, revision - 1) if revision > 1 else None
    window_start = parse_dt(prev["occurred_at"]) if prev else None

    # 1) 新增事实（本版提交窗口内新增；首版则取截至提交时的全部在案观察）
    new_facts: list[dict[str, Any]] = []
    for rec in case.observations.values():
        created = rec.history[0]
        ts = parse_dt(created["occurred_at"])
        if ts <= submitted_at and (window_start is None or ts > window_start):
            new_facts.append({
                "observation_id": rec.current["observation_id"],
                "layer": rec.current["layer"],
                "category": rec.current["category"],
                "text": rec.current["text"],
                "pattern_name": rec.current.get("pattern_name"),
                "lab_value": rec.current.get("lab_value"),
                "linked_fact_ids": rec.current.get("linked_fact_ids", []),
                "origin": _origin(created),
            })

    # 2) 冲突 / 相互作用 / 候选机制（窗口内新增）
    def _windowed(collection: dict) -> list[dict[str, Any]]:
        out = []
        for rec in collection.values():
            ts = parse_dt(rec.history[0]["occurred_at"])
            if ts <= submitted_at and (window_start is None or ts > window_start):
                out.append(rec.current | {"origin": _origin(rec.history[0])})
        return out

    conflicts_new = _windowed(case.conflicts)
    interactions_new = _windowed(case.interaction_flags)
    mechanisms_new = _windowed(case.mechanisms)

    # 3) 问题表述（窗口内新增，附截至本版仍开放的跨体系冲突）
    problems_new = _windowed(case.problems)

    # 4) 治疗取舍：与上一版逐条比对
    prev_decisions = {d["label"]: d for d in prev["payload"]["decisions"]} if prev else {}
    active_labels_now = {
        x["label"] for x in submission["payload"]["decisions"] if x["action"] in ("merged", "retained")
    }
    excluded_labels = {
        x["label"] for x in submission["payload"]["decisions"] if x["action"] == "excluded"
    }
    merged_away_labels = {
        part.get("label")
        for x in submission["payload"]["decisions"] if x["action"] == "merged"
        for part in x.get("merged_from", [])
    }
    accounted_labels = active_labels_now | excluded_labels | merged_away_labels
    excluded_now = {
        label
        for label, old in prev_decisions.items()
        if old["action"] in ("merged", "retained") and label not in accounted_labels
    }
    decisions_view: list[dict[str, Any]] = []
    for d in submission["payload"]["decisions"]:
        prior = prev_decisions.get(d["label"])
        if prior is None:
            change = "introduced"  # 本版新增
        elif prior["action"] != d["action"]:
            change = f"{prior['action']}->{d['action']}"
        else:
            change = "unchanged"
        decisions_view.append({
            "decision_id": d["decision_id"],
            "label": d["label"],
            "system": d["system"],
            "action": d["action"],
            "change_from_previous": change,
            "rationale": d["rationale"],
            "target_problem_ids": d["target_problem_ids"],
            "evidence_refs": d["evidence_refs"],
            "substances": d.get("substances", []),
            "merged_from": d.get("merged_from", []),
            "exclusion_reason": d.get("exclusion_reason"),
            "duplication_ack": [
                a for a in submission["payload"].get("duplication_acknowledgments", [])
                if d["decision_id"] in (a.get("decision_a"), a.get("decision_b"))
            ],
        })
    # 上一版保留/合并、本版消失的治疗 = 本版被排除（要求学生在新版以 excluded 显式记录，
    # 若只是悄悄删除，这里如实标红）
    silent_drops = sorted(
        label for label in excluded_now
        if not any(x["label"] == label and x["action"] == "excluded" for x in submission["payload"]["decisions"])
    )

    # 5) 教师分歧：针对本版及其决策/问题的全部意见，按 supports/disputes 串成线程
    faculty_input = _faculty_inputs(case, submission, submitted_at)

    metrics = _integration_metrics(case, submission, prev, new_facts, conflicts_new,
                                   interactions_new, mechanisms_new, silent_drops)

    return {
        "case_id": case.case_id,
        "case_title": case.release["payload"]["title"] if case.release else case.case_id,
        "plan_id": plan_id,
        "student_id": submission["payload"]["student_id"],
        "course_id": submission["payload"]["course_id"],
        "revision": revision,
        "submitted_origin": _origin(submission),
        "previous_revision": revision - 1 if prev else None,
        "columns": {
            "new_facts": new_facts,
            "conflicts": conflicts_new,
            "interactions": interactions_new,
            "mechanisms": mechanisms_new,
            "problems": problems_new,
            "treatment_decisions": decisions_view,
            "silent_drops": silent_drops,
            "faculty_input": faculty_input,
            "simulations": [
                s["payload"] | {"origin": _origin(s)}
                for s in case.simulations
                if s["payload"]["linked_revision"] == revision
            ],
        },
        "metrics": metrics,
    }


def _faculty_inputs(case: CaseProjection, submission: dict[str, Any], submitted_at) -> dict[str, Any]:
    revision = submission["payload"]["revision"]
    decision_ids = {d["decision_id"] for d in submission["payload"]["decisions"]}
    problem_ids = {pid for d in submission["payload"]["decisions"] for pid in d["target_problem_ids"]}
    cited_events = {ref for d in submission["payload"]["decisions"] for ref in d.get("evidence_refs", [])}

    threads: dict[str, dict[str, Any]] = {}
    for rec in case.opinions.values():
        p = rec.current
        t = p.get("target", {})
        informed_this_revision = any(
            h["event_id"] in cited_events for h in rec.history
        )
        hit = (
            (t.get("kind") == "plan_revision" and t.get("id") == f"r{revision}")
            or (t.get("kind") == "decision" and t.get("id") in decision_ids)
            or (t.get("kind") == "problem" and t.get("id") in problem_ids)
            or informed_this_revision  # 上一版的意见被本版取舍直接引用：意见→决策的来路
        )
        if not hit:
            continue
        threads[p["opinion_id"]] = {
            "opinion_id": p["opinion_id"],
            "discipline": p["discipline"],
            "stance": p["stance"],
            "content": p["content"],
            "target": t,
            "relation_to": p.get("relation_to"),
            "amended": len(rec.history) > 1,
            "informed_this_revision": informed_this_revision,
            "origin": _origin(rec.history[0]),
        }

    # 标注仍未被回应的反对意见（没有另一条意见 supports 它，也没有作者本人更正）
    disputed_threads, supporting = [], []
    for oid, t in threads.items():
        rel = t["relation_to"]
        if rel and rel.get("relation") == "supports":
            supporting.append(oid)
    for oid, t in threads.items():
        if t["stance"] in ("disagree", "concern"):
            answered = any(
                u["relation_to"]
                and u["relation_to"].get("opinion_id") == oid
                and u["relation_to"].get("relation") == "supports"
                for u in threads.values()
            )
            disputed_threads.append({**t, "answered": answered})

    return {
        "all_opinions": list(threads.values()),
        "unresolved_disagreements": [t for t in disputed_threads if not t["answered"]],
        "disciplines_present": sorted({t["discipline"] for t in threads.values()}),
        "note": "分歧允许并存：没有任何意见会因票数少而被删除或折叠，更正保留完整历史",
    }


def _integration_metrics(case, submission, prev, new_facts, conflicts_new,
                         interactions_new, mechanisms_new, silent_drops) -> dict[str, Any]:
    """整合度的结构性指标——只描述决策结构，不替教师打分裁定。"""
    decisions = submission["payload"]["decisions"]
    counts = {a: sum(1 for d in decisions if d["action"] == a) for a in
              ("merged", "retained", "excluded", "deferred")}

    # 跨体系合并：真正把两套体系对同一问题的治疗并成一项决策
    cross_system_merges = [
        d["label"] for d in decisions
        if d["action"] == "merged"
        and len({p.get("system") for p in d.get("merged_from", [])}) >= 2
    ]

    # 共同解释：同一候选机制同时引用了西医视角与中医视角的问题
    perspective_of_problem = {
        rec.current["problem_id"]: rec.current["perspective"]
        for rec in case.problems.values()
    }
    shared_explanations = []
    for rec in case.mechanisms.values():
        persps = {perspective_of_problem.get(r) for r in rec.current["linked_refs"]
                  if r in perspective_of_problem}
        if {"western", "tcm"} <= persps:
            shared_explanations.append(rec.current["mechanism_id"])

    # 依据到事实的距离：本版决策引用的问题/证据是否最终落在事实上
    fact_backed = 0
    target_total = 0
    obs_ids = set(case.observations)
    for d in decisions:
        for pid in d["target_problem_ids"]:
            target_total += 1
            prob = case.problems.get(pid)
            if prob and any(r in obs_ids for r in prob.current.get("linked_observation_ids", [])):
                fact_backed += 1

    # 疗效措辞风险：把相关性/假说当 validated_outcome 使用（提交时已拦截，指标保持 0 以示守卫存在）
    overclaim = [
        rec.current["mechanism_id"] for rec in case.mechanisms.values()
        if rec.current["claim_scope"] == "validated_outcome"
        and not rec.current.get("citations")
    ]

    open_cross_conflicts = [
        cid for cid, rec in case.conflicts.items()
        if rec.current["conflict_type"] == "cross_system"
        and rec.current.get("status", "open") == "open"
    ]

    prev_counts = None
    if prev:
        pd = prev["payload"]["decisions"]
        prev_counts = {a: sum(1 for d in pd if d["action"] == a) for a in
                       ("merged", "retained", "excluded", "deferred")}

    # 拼贴风险信号：并列但无共同解释、悄悄删药、未解释的跨体系冲突
    juxtaposition_signals = []
    retained_count = counts["retained"]
    if counts["merged"] == 0 and retained_count >= 2:
        juxtaposition_signals.append(
            f"本版 {retained_count} 项治疗全部并列保留，没有任何一项跨体系合并"
        )
    if silent_drops:
        juxtaposition_signals.append(f"存在未说明依据的悄悄删药：{silent_drops}")
    if open_cross_conflicts:
        juxtaposition_signals.append(f"仍有 {len(open_cross_conflicts)} 个跨体系冲突未被解释或确认")
    corr = sum(1 for r in case.mechanisms.values() if r.current["claim_scope"] == "correlation")
    if corr and not shared_explanations:
        juxtaposition_signals.append("已登记相关性观察，但没有任何机制把两套体系的问题共同解释")

    return {
        "decision_counts": counts,
        "previous_decision_counts": prev_counts,
        "cross_system_merges": cross_system_merges,
        "shared_cross_system_explanations": shared_explanations,
        "fact_backed_target_ratio": f"{fact_backed}/{target_total}",
        "rationale_coverage": f"{sum(1 for d in decisions if d['rationale'])}/{len(decisions)}",
        "exclusion_reason_coverage": f"{counts['excluded']}/{counts['excluded']}",
        "duplication_acknowledged": len(submission["payload"].get("duplication_acknowledgments", [])),
        "interaction_acknowledged": len(submission["payload"].get("interaction_acknowledgments", [])),
        "open_cross_system_conflicts": open_cross_conflicts,
        "overclaim_risk": overclaim,
        "juxtaposition_signals": juxtaposition_signals,
        "interpretation_hint": (
            "指标只反映决策结构的变化：跨体系合并、共同解释、有依据的排除是否随版本增加；"
            "是否为好的临床方案仍由教师判断，系统不输出疗效结论"
        ),
    }


# ---------------------------------------------------------------- Markdown

def render_revision_markdown(view: dict[str, Any]) -> str:
    c = view["columns"]
    lines = [
        f"# 方案修订并排视图 · 第 {view['revision']} 版",
        "",
        f"病例：{view['case_title']}（{view['case_id']}）｜学生：{view['student_id']}｜课程：{view['course_id']}",
        f"提交：{view['submitted_origin']['occurred_at']}｜事件 {view['submitted_origin']['event_id']} v{view['submitted_origin']['version']}",
        f"上一版：{view['previous_revision'] or '无（首版）'}",
        "",
        "## 一、并排总览（新增事实 / 冲突识别 / 治疗取舍 / 教师分歧）",
        "",
        "| 新增事实 | 冲突识别 | 治疗取舍 | 教师分歧（来路） |",
        "| --- | --- | --- | --- |",
    ]

    def fact_cell(items):
        if not items:
            return "—"
        return "<br>".join(
            f"[{ '证候' if x['layer'] == 'tcm_observation' else '事实'}] {x['text']}"
            f"（{x['origin']['event_id']}）" for x in items
        )

    def conflict_cell(items):
        if not items:
            return "—"
        return "<br>".join(f"[{x['conflict_type']}] {x['description']}（{x['origin']['event_id']}）"
                           for x in items)

    def decision_cell(items):
        if not items:
            return "—"
        return "<br>".join(
            f"{_ACTION_CN[x['action']]}·{_SYSTEM_CN.get(x['system'], x['system'])} {x['label']}"
            f"（{x['decision_id']}）" for x in items
        )

    def opinion_cell(items):
        if not items:
            return "—"
        return "<br>".join(
            f"{_STANCE_CN[x['stance']]}·{x['discipline']}：{x['content'][:24]}…"
            f"（{x['origin']['event_id']}）" for x in items
        )

    rows = max(len(c["new_facts"]), len(c["conflicts"]),
               len(c["treatment_decisions"]), len(c["faculty_input"]["all_opinions"]), 1)
    for i in range(rows):
        lines.append(
            "| " + " | ".join([
                fact_cell([c["new_facts"][i]]) if i < len(c["new_facts"]) else "",
                conflict_cell([c["conflicts"][i]]) if i < len(c["conflicts"]) else "",
                decision_cell([c["treatment_decisions"][i]]) if i < len(c["treatment_decisions"]) else "",
                opinion_cell([c["faculty_input"]["all_opinions"][i]])
                if i < len(c["faculty_input"]["all_opinions"]) else "",
            ]) + " |"
        )

    lines += ["", "## 二、治疗取舍与依据（含与上一版的差异）", ""]
    for d in c["treatment_decisions"]:
        lines.append(
            f"- **{_ACTION_CN[d['action']]} {d['label']}**（{_SYSTEM_CN.get(d['system'], d['system'])}，"
            f"变化：{d['change_from_previous']}，决策号 {d['decision_id']}）"
        )
        lines.append(f"  - 依据：{d['rationale']}")
        lines.append(f"  - 针对问题：{', '.join(d['target_problem_ids'])}")
        lines.append(f"  - 证据来路：{', '.join(d['evidence_refs'])}")
        if d["action"] == "merged":
            parts = [f"{p.get('label')}（{_SYSTEM_CN.get(p.get('system'), p.get('system'))}）"
                     for p in d["merged_from"]]
            lines.append(f"  - 合并来源：{' + '.join(parts)}")
        if d["action"] == "excluded":
            lines.append(f"  - 排除理由分类：{d['exclusion_reason']}")
        for a in d["duplication_ack"]:
            lines.append(f"  - 重复确认：{a}")

    if c["silent_drops"]:
        lines += ["", f"> ⚠ 未给出依据就从方案中消失的治疗：{', '.join(c['silent_drops'])}"]

    lines += ["", "## 三、教师分歧（并存，不做少数服从多数）", ""]
    for o in c["faculty_input"]["all_opinions"]:
        rel = o.get("relation_to")
        rel_txt = ""
        if rel:
            rel_txt = f"，对意见 {rel['opinion_id']} 表示 {rel['relation']}"
        mark = "（未回应的反对/担忧）" if o in c["faculty_input"]["unresolved_disagreements"] else ""
        informed = "（被本版取舍引用）" if o.get("informed_this_revision") else ""
        lines.append(
            f"- [{_STANCE_CN[o['stance']]}] {o['discipline']}：{o['content']}{rel_txt}"
            f"{'（已更正，保留历史）' if o['amended'] else ''}{mark}{informed}"
            f" — {o['origin']['actor'].get('id')} @ {o['origin']['occurred_at']}（{o['origin']['event_id']}）"
        )

    lines += ["", "## 四、候选机制与共同解释", ""]
    for m in c["mechanisms"]:
        lines.append(f"- {m['title']}（{m['claim_scope']}，关联 {', '.join(m['linked_refs'])}）")
    if not c["mechanisms"]:
        lines.append("- （本窗口无新增候选机制）")

    m = view["metrics"]
    lines += ["", "## 五、整合度结构指标（供课程负责人判断是否仍在拼术语）", ""]
    lines.append(f"- 取舍计数：{m['decision_counts']}（上一版：{m['previous_decision_counts']}）")
    lines.append(f"- 跨体系合并：{len(m['cross_system_merges'])} 项 {m['cross_system_merges']}")
    lines.append(f"- 共同解释两套体系问题的机制：{m['shared_cross_system_explanations']}")
    lines.append(f"- 决策目标有事实支撑：{m['fact_backed_target_ratio']}；依据覆盖率：{m['rationale_coverage']}")
    lines.append(f"- 已确认的重复：{m['duplication_acknowledged']}；已确认的高危相互作用：{m['interaction_acknowledged']}")
    lines.append(f"- 未关闭的跨体系冲突：{m['open_cross_system_conflicts']}")
    if m["juxtaposition_signals"]:
        lines += ["- 拼贴风险信号："] + [f"  - {s}" for s in m["juxtaposition_signals"]]
    lines += ["", f"> {m['interpretation_hint']}"]
    return "\n".join(lines)
