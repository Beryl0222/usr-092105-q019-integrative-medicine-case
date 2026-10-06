"""融合医学临床教学案：领域事件定义与结构化校验。

设计原则
--------
1. 事件只记录"发生了什么"，不可变；更正以新事件（CORRECTED）表达，保留来路。
2. 四层业务对象各自成流：teaching_case / clinical_observation / student_plan /
   faculty_feedback，同一病例的四层用同一个 case_id 关联。
3. 系统不替师生裁定医学体系优先级：候选机制只能以"相关性/假说/验证结局"三档
   记录，相关性与个案随访不得包装为疗效。
4. 学生治疗取舍必须给结构化依据（合并/保留/排除/搁置 + 理由 + 证据引用）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# ---------------------------------------------------------------- 公共常量

ENVELOPE_REQUIRED = (
    "event_id",
    "event_type",
    "aggregate_type",
    "aggregate_id",
    "occurred_at",
    "version",
    "summary",
)

TEACHING_CASE = "teaching_case"
CLINICAL_OBSERVATION = "clinical_observation"
STUDENT_PLAN = "student_plan"
FACULTY_FEEDBACK = "faculty_feedback"

AGGREGATE_TYPES = (TEACHING_CASE, CLINICAL_OBSERVATION, STUDENT_PLAN, FACULTY_FEEDBACK)

# 事件类型 -> 所属聚合（1:1，便于跨课程按层同步）
EVENT_AGGREGATE: dict[str, str] = {
    # 授权与脱敏层
    "CASE_RELEASED": TEACHING_CASE,
    "CONSENT_WITHDRAWN": TEACHING_CASE,
    "ACCESS_EXPIRED": TEACHING_CASE,
    # 事实 / 证候 / 分析层
    "OBSERVATION_ADDED": CLINICAL_OBSERVATION,
    "OBSERVATION_CORRECTED": CLINICAL_OBSERVATION,
    "CONFLICT_IDENTIFIED": CLINICAL_OBSERVATION,
    "INTERACTION_FLAGGED": CLINICAL_OBSERVATION,
    "MECHANISM_PROPOSED": CLINICAL_OBSERVATION,
    # 学生问题表述与各版决策层
    "PROBLEM_FORMULATED": STUDENT_PLAN,
    "PLAN_SUBMITTED": STUDENT_PLAN,
    # 跨学科意见 / 模拟 / 回顾 / 能力证据层
    "OPINION_RECORDED": FACULTY_FEEDBACK,
    "OPINION_CORRECTED": FACULTY_FEEDBACK,
    "SIMULATION_RECORDED": FACULTY_FEEDBACK,
    "CASE_REVIEWED": FACULTY_FEEDBACK,
    "COMPETENCY_EVALUATED": FACULTY_FEEDBACK,
}

EVENT_TYPES = tuple(EVENT_AGGREGATE)

ROLES = ("student", "faculty", "admin", "system", "data_subject")

OBSERVATION_LAYERS = ("fact", "tcm_observation")
FACT_CATEGORIES = ("symptom", "sign", "lab", "imaging", "history", "diagnosis")
TCM_CATEGORIES = ("tongue", "pulse", "spirit", "palpation", "pattern", "other")

CLAIM_SCOPES = ("correlation", "hypothesis", "validated_outcome")
INTERVENTIONAL_DESIGNS = ("rct", "systematic_review", "meta_analysis", "cohort_interventional")

DECISION_ACTIONS = ("merged", "retained", "excluded", "deferred")
EXCLUSION_REASONS = (
    "contraindication",
    "duplication",
    "insufficient_evidence",
    "interaction_risk",
    "patient_preference",
    "not_applicable",
    "other",
)

EXPIRY_REASONS = ("consent_expired", "consent_withdrawn", "admin_revoked", "case_superseded")
RETENTION_GRADES = ("retain_anonymized", "retain_full", "delete_evidence")


# ---------------------------------------------------------------- 工具

def parse_dt(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _err(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def validate_event(record: dict[str, Any]) -> list[str]:
    """校验事件信封及其载荷，返回可直接展示给接入方的中文错误列表。

    载荷（payload）对最早的信封-only 接入方保持可选；一旦携带则必须符合
    对应事件类型的结构化约束。
    """
    errors: list[str] = [f"缺少字段：{name}" for name in ENVELOPE_REQUIRED if name not in record]
    if errors:
        return errors

    etype = record["event_type"]
    atype = record["aggregate_type"]

    _err(errors, etype in EVENT_AGGREGATE, f"未知事件类型：{etype}")
    _err(errors, atype in AGGREGATE_TYPES, f"未知聚合类型：{atype}")
    if etype in EVENT_AGGREGATE:
        _err(
            errors,
            EVENT_AGGREGATE[etype] == atype,
            f"事件 {etype} 必须属于聚合 {EVENT_AGGREGATE[etype]}，实际为 {atype}",
        )

    _err(errors, isinstance(record["event_id"], str) and len(record["event_id"]) >= 8, "event_id 至少 8 个字符")
    _err(errors, isinstance(record["aggregate_id"], str) and bool(record["aggregate_id"]), "aggregate_id 不能为空")
    _err(errors, isinstance(record["version"], int) and record["version"] >= 1, "version 必须是正整数")
    _err(errors, isinstance(record["summary"], str) and len(record["summary"]) >= 2, "summary 至少 2 个字符")
    if parse_dt(record["occurred_at"]) is None:
        errors.append("occurred_at 必须是 ISO 8601 日期时间")

    payload = record.get("payload")
    if payload is not None:
        _err(errors, isinstance(payload, dict), "payload 必须是对象")
        if isinstance(payload, dict) and etype in _PAYLOAD_VALIDATORS:
            errors.extend(_PAYLOAD_VALIDATORS[etype](payload))
    return errors


# ---------------------------------------------------------------- 载荷校验

def _common(errors: list[str], p: dict, *, need_course: bool = True) -> None:
    _err(errors, isinstance(p.get("case_id"), str) and p.get("case_id"), "payload.case_id 不能为空")
    if need_course:
        _err(errors, isinstance(p.get("course_id"), str) and p.get("course_id"), "payload.course_id 不能为空")
    actor = p.get("actor")
    _err(errors, isinstance(actor, dict), "payload.actor 必须是对象")
    if isinstance(actor, dict):
        _err(errors, bool(actor.get("id")), "actor.id 不能为空")
        _err(errors, actor.get("role") in ROLES, f"actor.role 必须是 {ROLES} 之一")
    if "occurred_at" in p and parse_dt(str(p["occurred_at"])) is None:
        errors.append("payload.occurred_at 必须是 ISO 8601 日期时间")


def _validate_case_released(p: dict) -> list[str]:
    e: list[str] = []
    _common(e, p, need_course=False)
    _err(e, isinstance(p.get("title"), str) and len(p["title"]) >= 2, "病例标题不能为空")
    courses = p.get("courses")
    _err(e, isinstance(courses, list) and len(courses) >= 1 and all(isinstance(c, str) for c in courses),
         "courses 必须至少包含一个课程标识")

    consent = p.get("consent")
    _err(e, isinstance(consent, dict), "consent（教学同意）必须是对象")
    if isinstance(consent, dict):
        for f in ("consent_id", "basis", "consented_at", "scope_text"):
            _err(e, bool(consent.get(f)), f"consent.{f} 不能为空")
        if consent.get("consented_at") and parse_dt(str(consent["consented_at"])) is None:
            e.append("consent.consented_at 必须是 ISO 8601 日期时间")

    deid = p.get("de_identification")
    _err(e, isinstance(deid, dict), "de_identification（脱敏说明）必须是对象")
    if isinstance(deid, dict):
        _err(e, deid.get("direct_identifiers_removed") is True,
             "de_identification.direct_identifiers_removed 必须为 true（直接标识须全部移除）")
        _err(e, bool(deid.get("pseudonym")), "de_identification.pseudonym（研究代号）不能为空")
        cats = deid.get("data_categories")
        _err(e, isinstance(cats, list) and len(cats) >= 1, "de_identification.data_categories 至少一项")
        if deid.get("checked_by"):
            _err(e, bool(deid["checked_by"]), "de_identification.checked_by 不能为空字符串")

    auth = p.get("authorization")
    _err(e, isinstance(auth, dict), "authorization（授权期限）必须是对象")
    if isinstance(auth, dict):
        for f in ("valid_from", "valid_until"):
            _err(e, parse_dt(str(auth.get(f))) is not None, f"authorization.{f} 必须是 ISO 8601 日期时间")
        vf, vu = parse_dt(str(auth.get("valid_from", ""))), parse_dt(str(auth.get("valid_until", "")))
        if vf and vu:
            _err(e, vu > vf, "authorization.valid_until 必须晚于 valid_from（授权到期日须在生效日之后）")
    return e


def _validate_consent_withdrawn(p: dict) -> list[str]:
    e: list[str] = []
    _common(e, p, need_course=False)
    _err(e, bool(p.get("consent_id")), "consent_id 不能为空")
    _err(e, bool(p.get("reason")), "撤回原因不能为空")
    return e


def _validate_access_expired(p: dict) -> list[str]:
    e: list[str] = []
    _common(e, p, need_course=False)
    _err(e, p.get("reason") in EXPIRY_REASONS, f"reason 必须是 {EXPIRY_REASONS} 之一")
    _err(e, parse_dt(str(p.get("effective_at"))) is not None, "effective_at 必须是 ISO 8601 日期时间")
    retention = p.get("retention")
    _err(e, isinstance(retention, dict), "retention（成绩证据保留规则）必须是对象")
    if isinstance(retention, dict):
        _err(e, retention.get("grade_evidence") in RETENTION_GRADES,
             f"retention.grade_evidence 必须是 {RETENTION_GRADES} 之一")
        _err(e, bool(retention.get("rule_reference")), "retention.rule_reference（保留依据）不能为空")
    return e


def _validate_observation_added(p: dict) -> list[str]:
    e: list[str] = []
    _common(e, p)
    _err(e, bool(p.get("observation_id")), "observation_id 不能为空")
    layer = p.get("layer")
    _err(e, layer in OBSERVATION_LAYERS, f"layer 必须是 {OBSERVATION_LAYERS} 之一")
    if layer == "fact":
        _err(e, p.get("category") in FACT_CATEGORIES, f"事实 category 必须是 {FACT_CATEGORIES} 之一")
    elif layer == "tcm_observation":
        _err(e, p.get("category") in TCM_CATEGORIES,
             f"证候观察 category 必须是 {TCM_CATEGORIES} 之一")
        if p.get("category") == "pattern":
            _err(e, bool(p.get("pattern_name")), "category=pattern 时 pattern_name 不能为空")
            linked = p.get("linked_fact_ids")
            _err(e, isinstance(linked, list) and len(linked) >= 1,
                 "证候判断须用 linked_fact_ids 引用至少一条支持事实，禁止无证候依据的结论")
    _err(e, bool(p.get("text")), "观察内容 text 不能为空")
    _err(e, parse_dt(str(p.get("observed_at"))) is not None, "observed_at 必须是 ISO 8601 日期时间")
    lab = p.get("lab_value")
    if isinstance(lab, dict):
        for f in ("value", "unit"):
            _err(e, lab.get(f) is not None, f"lab_value.{f} 不能为空")
    return e


def _validate_observation_corrected(p: dict) -> list[str]:
    e: list[str] = []
    _common(e, p)
    _err(e, bool(p.get("observation_id")), "observation_id 不能为空")
    _err(e, bool(p.get("supersedes_event_id")), "supersedes_event_id（被更正事件）不能为空")
    _err(e, bool(p.get("correction_reason")), "correction_reason（更正理由）不能为空")
    patch = p.get("patch")
    _err(e, isinstance(patch, dict) and len(patch) >= 1, "patch 必须是非空对象，且不得整条覆盖原记录")
    return e


def _validate_conflict(p: dict) -> list[str]:
    e: list[str] = []
    _common(e, p)
    _err(e, bool(p.get("conflict_id")), "conflict_id 不能为空")
    _err(e, p.get("conflict_type") in ("factual", "interpretive", "cross_system", "temporal"),
         "conflict_type 必须是 factual/interpretive/cross_system/temporal 之一")
    refs = p.get("between_refs")
    _err(e, isinstance(refs, list) and len(refs) >= 2, "between_refs 须引用至少两个互相冲突的记录")
    _err(e, bool(p.get("description")), "冲突说明 description 不能为空")
    _err(e, p.get("status", "open") in ("open", "acknowledged", "explained"),
         "冲突状态只能是 open/acknowledged/explained（冲突只能被解释或确认，不能被删除）")
    return e


def _validate_interaction(p: dict) -> list[str]:
    e: list[str] = []
    _common(e, p)
    _err(e, bool(p.get("flag_id")), "flag_id 不能为空")
    subs = p.get("substances")
    _err(e, isinstance(subs, list) and len(subs) >= 2, "substances 须列出至少两种相互作用的药物/成分")
    _err(e, bool(p.get("risk_text")), "risk_text（风险说明）不能为空")
    _err(e, p.get("severity") in ("low", "moderate", "high", "contraindicated"),
         "severity 必须是 low/moderate/high/contraindicated")
    _err(e, isinstance(p.get("references"), list) and len(p["references"]) >= 1,
         "相互作用旗标必须给出处 references，不得凭印象标注")
    _err(e, p.get("is_efficacy_claim") is not True, "相互作用旗标是安全提示，禁止携带疗效断言")
    return e


def _validate_mechanism(p: dict) -> list[str]:
    e: list[str] = []
    _common(e, p)
    _err(e, bool(p.get("mechanism_id")), "mechanism_id 不能为空")
    _err(e, bool(p.get("title")), "机制假说标题不能为空")
    scope = p.get("claim_scope")
    _err(e, scope in CLAIM_SCOPES, f"claim_scope 必须是 {CLAIM_SCOPES} 之一（相关性/机制假说/已验证结局）")
    _err(e, isinstance(p.get("linked_refs"), list) and len(p["linked_refs"]) >= 1,
         "linked_refs 须引用该机制试图解释的事实或问题，禁止悬空假说")
    if scope == "validated_outcome":
        cites = p.get("citations")
        ok = isinstance(cites, list) and any(
            isinstance(c, dict) and c.get("design") in INTERVENTIONAL_DESIGNS for c in cites
        )
        _err(e, ok,
             "claim_scope=validated_outcome 必须引用干预性研究（rct/systematic_review/meta_analysis 等）；"
             "相关性观察与机制假说不得记为疗效")
    return e


def _validate_problem(p: dict) -> list[str]:
    e: list[str] = []
    _common(e, p)
    _err(e, bool(p.get("problem_id")), "problem_id 不能为空")
    _err(e, bool(p.get("formulation")), "问题表述 formulation 不能为空")
    _err(e, p.get("perspective") in ("western", "tcm", "integrated"),
         "perspective 必须是 western/tcm/integrated 之一")
    _err(e, isinstance(p.get("linked_observation_ids"), list) and len(p["linked_observation_ids"]) >= 1,
         "问题表述须引用至少一条观察事实，问题不能只来自术语对照")
    return e


def _validate_plan(p: dict) -> list[str]:
    e: list[str] = []
    _common(e, p)
    _err(e, bool(p.get("plan_id")), "plan_id 不能为空")
    _err(e, isinstance(p.get("revision"), int) and p["revision"] >= 1, "revision 必须是从 1 开始的正整数")
    _err(e, bool(p.get("student_id")), "student_id 不能为空")
    decisions = p.get("decisions")
    _err(e, isinstance(decisions, list) and len(decisions) >= 1, "decisions 至少包含一项治疗取舍")
    if isinstance(decisions, list):
        ids: set[str] = set()
        for i, d in enumerate(decisions):
            where = f"decisions[{i}]"
            if not isinstance(d, dict):
                e.append(f"{where} 必须是对象")
                continue
            _err(e, bool(d.get("decision_id")), f"{where}.decision_id 不能为空")
            if d.get("decision_id"):
                _err(e, d["decision_id"] not in ids, f"{where}.decision_id 重复：{d['decision_id']}")
                ids.add(d["decision_id"])
            _err(e, bool(d.get("label")), f"{where}.label（治疗名称）不能为空")
            _err(e, d.get("system") in ("western", "tcm", "nonpharmacologic", "other"),
                 f"{where}.system 必须是 western/tcm/nonpharmacologic/other 之一")
            action = d.get("action")
            _err(e, action in DECISION_ACTIONS, f"{where}.action 必须是 {DECISION_ACTIONS} 之一")
            _err(e, bool(d.get("rationale")), f"{where} 必须填写取舍依据 rationale，禁止无理由的并列用药")
            _err(e, isinstance(d.get("target_problem_ids"), list) and len(d["target_problem_ids"]) >= 1,
                 f"{where}.target_problem_ids 至少引用一个问题")
            _err(e, isinstance(d.get("evidence_refs"), list) and len(d["evidence_refs"]) >= 1,
                 f"{where}.evidence_refs 至少一条证据来路")
            if action == "merged":
                parts = d.get("merged_from")
                _err(e, isinstance(parts, list) and len(parts) >= 2,
                     f"{where}.action=merged 时 merged_from 须列出被合并的至少两项治疗")
                systems = {p_.get("system") for p_ in parts} if isinstance(parts, list) else set()
                _err(e, len(systems) >= 2 and None not in systems,
                     f"{where}：合并必须跨越至少两个体系，同体系删减请用 retained/excluded")
            if action == "excluded":
                _err(e, d.get("exclusion_reason") in EXCLUSION_REASONS,
                     f"{where}.exclusion_reason 必须是 {EXCLUSION_REASONS} 之一")
        acks = p.get("duplication_acknowledgments", [])
        _err(e, isinstance(acks, list), "duplication_acknowledgments 必须是列表")
    return e


def _validate_opinion(p: dict) -> list[str]:
    e: list[str] = []
    _common(e, p)
    _err(e, bool(p.get("opinion_id")), "opinion_id 不能为空")
    _err(e, bool(p.get("faculty_id")), "faculty_id 不能为空")
    _err(e, bool(p.get("discipline")), "discipline（学科）不能为空")
    _err(e, p.get("stance") in ("support", "concern", "disagree", "alternative"),
         "stance 必须是 support/concern/disagree/alternative 之一——分歧意见允许并存")
    _err(e, bool(p.get("content")), "意见内容 content 不能为空")
    target = p.get("target")
    _err(e, isinstance(target, dict) and target.get("kind") in ("problem", "decision", "plan_revision", "case"),
         "target.kind 必须是 problem/decision/plan_revision/case 之一")
    relation = p.get("relation_to")
    if isinstance(relation, dict) and relation:
        _err(e, bool(relation.get("opinion_id")), "relation_to.opinion_id 不能为空")
        _err(e, relation.get("relation") in ("supports", "disputes", "extends"),
             "relation_to.relation 必须是 supports/disputes/extends 之一")
    return e


def _validate_opinion_corrected(p: dict) -> list[str]:
    e: list[str] = []
    _common(e, p)
    _err(e, bool(p.get("opinion_id")), "opinion_id 不能为空")
    _err(e, bool(p.get("supersedes_event_id")), "supersedes_event_id 不能为空")
    _err(e, bool(p.get("correction_reason")), "correction_reason 不能为空")
    _err(e, isinstance(p.get("patch"), dict) and len(p["patch"]) >= 1, "patch 必须是非空对象")
    return e


def _validate_simulation(p: dict) -> list[str]:
    e: list[str] = []
    _common(e, p)
    _err(e, bool(p.get("simulation_id")), "simulation_id 不能为空")
    _err(e, isinstance(p.get("linked_revision"), int) and p["linked_revision"] >= 1,
         "linked_revision 须指向具体方案版本")
    _err(e, bool(p.get("tool")), "tool（模拟工具/模型）不能为空")
    _err(e, bool(p.get("scenario")), "scenario（模拟情境）不能为空")
    _err(e, p.get("outputs") is not None, "outputs（模拟结果）不能为空")
    _err(e, bool(p.get("limitations")), "limitations 必填：模拟结果不是患者真实结局")
    return e


def _validate_review(p: dict) -> list[str]:
    e: list[str] = []
    _common(e, p)
    _err(e, bool(p.get("review_id")), "review_id 不能为空")
    _err(e, parse_dt(str(p.get("follow_up_at"))) is not None, "follow_up_at 必须是 ISO 8601 日期时间")
    _err(e, bool(p.get("actual_findings")), "actual_findings（实际随访所见）不能为空")
    scope = p.get("claim_scope", "individual_followup")
    _err(e, scope in ("individual_followup", "correlation", "validated_outcome"),
         "临床回顾 claim_scope 必须是 individual_followup/correlation/validated_outcome")
    _err(e, scope != "validated_outcome",
         "单病例随访不能声明 validated_outcome：个案相关性不得包装为疗效或因果结论")
    return e


def _validate_competency(p: dict) -> list[str]:
    e: list[str] = []
    _common(e, p)
    _err(e, bool(p.get("evaluation_id")), "evaluation_id 不能为空")
    _err(e, bool(p.get("student_id")), "student_id 不能为空")
    _err(e, isinstance(p.get("plan_revision"), int) and p["plan_revision"] >= 1,
         "plan_revision 须指向被评价的具体方案版本")
    dims = p.get("dimensions")
    _err(e, isinstance(dims, dict) and len(dims) >= 1, "dimensions（能力维度）至少一项")
    if isinstance(dims, dict):
        for name, d in dims.items():
            _err(e, isinstance(d, dict), f"dimensions.{name} 必须是对象")
            if isinstance(d, dict):
                if d.get("score") is not None:
                    _err(e, isinstance(d["score"], (int, float)) and 0 <= d["score"] <= 100,
                         f"dimensions.{name}.score 须在 0-100")
                refs = d.get("evidence_refs")
                _err(e, isinstance(refs, list) and len(refs) >= 1,
                     f"dimensions.{name}.evidence_refs：能力评分必须引用方案/观察/意见事件作为证据")
    return e


_PAYLOAD_VALIDATORS = {
    "CASE_RELEASED": _validate_case_released,
    "CONSENT_WITHDRAWN": _validate_consent_withdrawn,
    "ACCESS_EXPIRED": _validate_access_expired,
    "OBSERVATION_ADDED": _validate_observation_added,
    "OBSERVATION_CORRECTED": _validate_observation_corrected,
    "CONFLICT_IDENTIFIED": _validate_conflict,
    "INTERACTION_FLAGGED": _validate_interaction,
    "MECHANISM_PROPOSED": _validate_mechanism,
    "PROBLEM_FORMULATED": _validate_problem,
    "PLAN_SUBMITTED": _validate_plan,
    "OPINION_RECORDED": _validate_opinion,
    "OPINION_CORRECTED": _validate_opinion_corrected,
    "SIMULATION_RECORDED": _validate_simulation,
    "CASE_REVIEWED": _validate_review,
    "COMPETENCY_EVALUATED": _validate_competency,
}


# ---------------------------------------------------------------- 事件构造

_seq = 0


def make_event(
    event_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
    *,
    version: int,
    occurred_at: str,
    event_id: str | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    """构造一条完整事件（调用方通常经过存储层，而不是直接使用）。"""
    global _seq
    if event_type not in EVENT_AGGREGATE:
        raise ValueError(f"未知事件类型：{event_type}")
    if event_id is None:
        _seq += 1
        event_id = f"evt-{aggregate_id}-{version:04d}-{_seq:04d}"
    record = {
        "event_id": event_id,
        "event_type": event_type,
        "aggregate_type": EVENT_AGGREGATE[event_type],
        "aggregate_id": aggregate_id,
        "occurred_at": occurred_at,
        "version": version,
        "summary": summary or payload.get("summary", event_type),
    }
    if payload:  # 信封-only 接入方可不携带载荷
        record["payload"] = payload
    return record
