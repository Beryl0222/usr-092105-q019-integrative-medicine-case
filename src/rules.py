"""领域规则：体系中立、证据表述、取舍依据。

这些规则把教学要求固化为可校验的结构约束：

1. 体系中立：系统不为任何医学体系排定优先级，方案与取舍不得携带
   “体系优先”类字段；取舍依据必须引用事实层记录，而不是诉诸体系偏好。
2. 相关性不等于疗效：候选机制的证据等级约束其表述强度，
   相关性证据最高只能表述为“关联”，不得表述为“疗效”。
3. 取舍必有依据：每一次合并、保留或排除都必须给出文字说明，
   并引用至少一条事实、相互作用、候选机制或教师意见。
"""

from __future__ import annotations

from typing import Any

TRADITIONS = ("biomedicine", "tcm", "shared")

OBSERVATION_KINDS = (
    "symptom",
    "exam_result",
    "pattern_observation",
    "problem_statement",
    "drug_interaction",
    "candidate_mechanism",
)

DECISION_ACTIONS = ("merge", "keep", "exclude")

# 证据等级由弱到强；表述强度不得越过证据等级。
EVIDENCE_KINDS = (
    "expert_consensus",
    "correlation",
    "mechanism_study",
    "clinical_trial",
    "systematic_review",
)

CLAIM_STRENGTHS = ("hypothesis", "association", "efficacy")

# 各表述强度所要求的最低证据等级。
_CLAIM_MIN_EVIDENCE = {
    "hypothesis": "expert_consensus",
    "association": "correlation",
    "efficacy": "clinical_trial",
}

FEEDBACK_KINDS = (
    "cross_discipline_opinion",
    "clinical_review",
    "competency_feedback",
)

INTERACTION_KINDS = ("duplication", "antagonism", "toxicity", "other")

# 禁止出现的“体系优先”类字段：系统不替师生裁定医学体系优先级。
_FORBIDDEN_PRIORITY_KEYS = ("system_priority", "tradition_rank", "preferred_system")


def validate_mechanism(payload: dict[str, Any]) -> list[str]:
    """候选机制：相关性不得包装成疗效，候选不得标记为已证实。"""
    errors: list[str] = []
    evidence = payload.get("evidence_kind")
    claim = payload.get("claim_strength", "hypothesis")
    if evidence not in EVIDENCE_KINDS:
        errors.append(f"候选机制缺少合法证据等级 evidence_kind（可选：{'、'.join(EVIDENCE_KINDS)}）")
    if claim not in CLAIM_STRENGTHS:
        errors.append(f"未知表述强度 claim_strength：{claim}")
    elif evidence in EVIDENCE_KINDS:
        required = _CLAIM_MIN_EVIDENCE[claim]
        if EVIDENCE_KINDS.index(evidence) < EVIDENCE_KINDS.index(required):
            if claim == "efficacy":
                errors.append("相关性或机制研究证据不能表述为疗效，疗效表述需要临床试验或系统综述证据")
            else:
                errors.append(f"表述强度 {claim} 需要至少 {required} 级别的证据")
    status = payload.get("status", "candidate")
    if status != "candidate":
        errors.append("候选机制只能保持 candidate 状态，系统不得将其标记为已证实")
    return errors


def validate_interaction(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    involves = payload.get("involves") or []
    if len(involves) < 2:
        errors.append("药物相互作用必须涉及至少两个治疗项目")
    if payload.get("interaction_kind") not in INTERACTION_KINDS:
        errors.append(f"相互作用类型 interaction_kind 需为：{'、'.join(INTERACTION_KINDS)}")
    return errors


def validate_problem(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if "linked_observations" not in payload:
        errors.append("问题表述必须给出 linked_observations（可以为空列表，但字段必须存在）")
    return errors


def validate_decision(decision: dict[str, Any]) -> list[str]:
    """每次取舍必须说明合并、保留或排除的依据。"""
    errors: list[str] = []
    item = decision.get("item") or "<未命名项目>"
    if decision.get("action") not in DECISION_ACTIONS:
        errors.append(f"治疗项目「{item}」的取舍动作需为 merge/keep/exclude")
    rationale = decision.get("rationale") or {}
    if not str(rationale.get("text") or "").strip():
        errors.append(f"治疗项目「{item}」的取舍必须说明依据（rationale.text）")
    references = rationale.get("references") or []
    if not references:
        errors.append(
            f"治疗项目「{item}」的取舍依据必须引用至少一条事实、相互作用、候选机制或教师意见（rationale.references）"
        )
    for key in _FORBIDDEN_PRIORITY_KEYS:
        if key in decision:
            errors.append(f"治疗项目「{item}」不得携带体系优先字段 {key}：系统不裁定医学体系优先级")
    return errors


def validate_plan_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in _FORBIDDEN_PRIORITY_KEYS:
        if key in payload:
            errors.append(f"方案不得携带体系优先字段 {key}：系统不裁定医学体系优先级")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        errors.append("方案必须包含至少一条治疗取舍（decisions）")
        return errors
    for decision in decisions:
        errors.extend(validate_decision(decision))
    return errors


def validate_consent(consent: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if consent.get("scope") != "teaching":
        errors.append("教学同意必须明确 scope=teaching")
    if consent.get("deidentified") is not True:
        errors.append("病例必须完成脱敏（deidentified=true）才能用于教学")
    if not consent.get("valid_until"):
        errors.append("教学同意必须给出授权到期时间 valid_until")
    return errors
