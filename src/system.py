"""融合医学临床教学案系统：授权生命周期、写入矩阵、引用完整性与中立性规则。

系统只做"记录与来路"的守门，不做医学裁判：
- 不校验哪个体系的诊断"更正确"，跨体系冲突以 CONFLICT_IDENTIFIED 并存；
- 不把相关性/机制假说/个案随访提升为疗效（在 events 层已结构化拦截）；
- 学生每次治疗取舍必须给依据，重复用药与高危相互作用必须显式确认；
- 教师分歧以 OPINION_RECORDED 的 supports/disputes 关系并存，不做少数服从多数。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .errors import AuthorizationError, DomainError, ValidationError
from .events import make_event
from .projections import CaseProjection, Projection
from .store import EventStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(name: str) -> str:
    return "".join(str(name).lower().split())


class TeachingCaseSystem:
    def __init__(self, store: EventStore | None = None, projection: Projection | None = None) -> None:
        self.store = store or EventStore()
        self.projection = projection or Projection()
        self.projection.rebuild(self.store.all_events())

    # ================================================================ 内部

    def _case(self, case_id: str) -> CaseProjection:
        return self.projection.case(case_id)

    def _next_version(self, aggregate_id: str) -> int:
        return len(self.store.stream(aggregate_id)) + 1

    def _append(
        self,
        *,
        event_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
        at: str | None = None,
        event_id: str | None = None,
        summary: str | None = None,
    ) -> dict[str, Any]:
        at = at or payload.get("occurred_at") or _now()
        version = self._next_version(aggregate_id)
        event = make_event(
            event_type,
            aggregate_id,
            payload,
            version=version,
            occurred_at=at,
            event_id=event_id,
            summary=summary,
        )
        self.store.append(event)
        self.projection.apply(event)
        return event

    def _require_active_course(self, case_id: str, course_id: str, at: str, *, actor_role: str) -> None:
        if actor_role in ("admin", "system"):
            return
        cp = self._case(case_id)
        ok, reason = cp.access_status(course_id, at)
        if not ok:
            raise AuthorizationError(f"课程 {course_id} 无法写入病例 {case_id}：{reason}")

    def _require_role(self, payload: dict, allowed: tuple[str, ...]) -> None:
        role = payload.get("actor", {}).get("role")
        if role not in allowed:
            raise AuthorizationError(f"该操作允许的角色为 {allowed}，当前角色为 {role}")

    def _known_refs(self, case_id: str) -> set[str]:
        cp = self._case(case_id)
        ids: set[str] = set()
        for coll in (cp.observations, cp.conflicts, cp.interaction_flags, cp.mechanisms, cp.problems, cp.opinions):
            ids.update(coll.keys())
        for ev in cp.simulations:
            ids.add(ev["payload"]["simulation_id"])
        for ev in cp.reviews:
            ids.add(ev["payload"]["review_id"])
        for ev in cp.competency:
            ids.add(ev["payload"]["evaluation_id"])
        for submissions in cp.plans.values():
            for sub in submissions:
                ids.add(sub["payload"]["plan_id"])
                ids.update(d["decision_id"] for d in sub["payload"]["decisions"])
        for ev in cp.events:
            ids.add(ev["event_id"])
        return ids

    def _require_refs_exist(self, case_id: str, refs: list[str], label: str) -> None:
        known = self._known_refs(case_id)
        missing = [r for r in refs if r not in known]
        if missing:
            raise DomainError(f"{label} 引用了病例中不存在的记录：{missing}（禁止悬空引用）")

    # ================================================================ 授权层

    def release_case(self, payload: dict[str, Any], *, at: str | None = None) -> dict[str, Any]:
        """发布脱敏病例并登记教学同意与授权期限。"""
        self._require_role(payload, ("admin",))
        case_id = payload["case_id"]
        if self._case(case_id).release is not None:
            raise DomainError(f"病例 {case_id} 已发布，授权变更须走撤回/到期事件")
        return self._append(
            event_type="CASE_RELEASED", aggregate_id=case_id, payload=payload,
            at=at, summary=f"发布脱敏教学病例：{payload.get('title', case_id)}",
        )

    def withdraw_consent(self, payload: dict[str, Any], *, at: str | None = None) -> dict[str, Any]:
        """数据主体（或其代理人）撤回教学同意。"""
        self._require_role(payload, ("data_subject", "admin"))
        case_id = payload["case_id"]
        if self._case(case_id).release is None:
            raise DomainError("病例尚未发布，无法撤回同意")
        return self._append(
            event_type="CONSENT_WITHDRAWN", aggregate_id=case_id, payload=payload,
            at=at, summary=f"教学同意撤回：{payload.get('reason', '')}",
        )

    def expire_access(self, payload: dict[str, Any], *, at: str | None = None) -> dict[str, Any]:
        """登记授权终止与成绩证据保留规则；到期后停止新课程访问。"""
        self._require_role(payload, ("system", "admin"))
        case_id = payload["case_id"]
        if self._case(case_id).release is None:
            raise DomainError("病例尚未发布，不能登记到期")
        return self._append(
            event_type="ACCESS_EXPIRED", aggregate_id=case_id, payload=payload,
            at=at or payload.get("effective_at"),
            summary=f"病例授权终止（{payload['reason']}），成绩证据按 {payload['retention']['grade_evidence']} 保留",
        )

    # ================================================================ 观察 / 分析层

    def add_observation(self, payload: dict[str, Any], *, at: str | None = None) -> dict[str, Any]:
        self._require_role(payload, ("student", "faculty"))
        self._require_active_course(payload["case_id"], payload["course_id"], at or payload.get("observed_at") or _now(),
                                    actor_role=payload["actor"]["role"])
        if payload.get("category") == "pattern":
            self._require_refs_exist(payload["case_id"], payload["linked_fact_ids"], "证候判断 linked_fact_ids")
        return self._append(
            event_type="OBSERVATION_ADDED",
            aggregate_id=f"{payload['case_id']}:clinical_observation",
            payload=payload, at=at,
            summary=f"记录{('证候观察' if payload['layer'] == 'tcm_observation' else '事实')}：{payload['text'][:30]}",
        )

    def correct_observation(self, payload: dict[str, Any], *, at: str | None = None) -> dict[str, Any]:
        self._require_role(payload, ("faculty", "admin"))
        self._require_active_course(payload["case_id"], payload["course_id"], at or _now(),
                                    actor_role=payload["actor"]["role"])
        cp = self._case(payload["case_id"])
        if payload["observation_id"] not in cp.observations:
            raise DomainError("被更正的观察不存在；更正不能凭空创造记录")
        self._require_refs_exist(payload["case_id"], [payload["supersedes_event_id"]], "supersedes_event_id")
        return self._append(
            event_type="OBSERVATION_CORRECTED",
            aggregate_id=f"{payload['case_id']}:clinical_observation",
            payload=payload, at=at,
            summary=f"更正观察 {payload['observation_id']}：{payload['correction_reason'][:30]}",
        )

    def identify_conflict(self, payload: dict[str, Any], *, at: str | None = None) -> dict[str, Any]:
        """登记冲突（事实/解释/跨体系/时间）。冲突允许并存，只能被解释或确认，不能删除。"""
        self._require_role(payload, ("student", "faculty"))
        self._require_active_course(payload["case_id"], payload["course_id"], at or _now(),
                                    actor_role=payload["actor"]["role"])
        self._require_refs_exist(payload["case_id"], payload["between_refs"], "冲突 between_refs")
        return self._append(
            event_type="CONFLICT_IDENTIFIED",
            aggregate_id=f"{payload['case_id']}:clinical_observation",
            payload=payload, at=at,
            summary=f"识别{payload['conflict_type']}冲突：{payload['description'][:30]}",
        )

    def flag_interaction(self, payload: dict[str, Any], *, at: str | None = None) -> dict[str, Any]:
        self._require_role(payload, ("student", "faculty"))
        self._require_active_course(payload["case_id"], payload["course_id"], at or _now(),
                                    actor_role=payload["actor"]["role"])
        return self._append(
            event_type="INTERACTION_FLAGGED",
            aggregate_id=f"{payload['case_id']}:clinical_observation",
            payload=payload, at=at,
            summary=f"药物相互作用旗标（{payload['severity']}）：{'×'.join(payload['substances'])}",
        )

    def propose_mechanism(self, payload: dict[str, Any], *, at: str | None = None) -> dict[str, Any]:
        """登记候选机制。三档 claim_scope：相关性 / 机制假说 / 已验证结局，后者须有干预性研究。"""
        self._require_role(payload, ("student", "faculty"))
        self._require_active_course(payload["case_id"], payload["course_id"], at or _now(),
                                    actor_role=payload["actor"]["role"])
        self._require_refs_exist(payload["case_id"], payload["linked_refs"], "机制 linked_refs")
        return self._append(
            event_type="MECHANISM_PROPOSED",
            aggregate_id=f"{payload['case_id']}:clinical_observation",
            payload=payload, at=at,
            summary=f"候选机制（{payload['claim_scope']}）：{payload['title'][:30]}",
        )

    # ================================================================ 学生决策层

    def formulate_problem(self, payload: dict[str, Any], *, at: str | None = None) -> dict[str, Any]:
        self._require_role(payload, ("student",))
        self._require_active_course(payload["case_id"], payload["course_id"], at or _now(), actor_role="student")
        self._require_refs_exist(payload["case_id"], payload["linked_observation_ids"], "问题 linked_observation_ids")
        return self._append(
            event_type="PROBLEM_FORMULATED",
            aggregate_id=f"{payload['case_id']}:plan:{payload['actor']['id']}",
            payload=payload, at=at,
            summary=f"问题表述（{payload['perspective']}）：{payload['formulation'][:30]}",
        )

    def submit_plan(self, payload: dict[str, Any], *, at: str | None = None) -> dict[str, Any]:
        """提交一版方案。系统在此强制：取舍依据、引用完整、跨体系合并的来路、
        重复用药与高危相互作用的显式确认。系统不判断治疗选择本身是否"正确"。"""
        self._require_role(payload, ("student",))
        self._require_active_course(payload["case_id"], payload["course_id"], at or _now(), actor_role="student")
        case_id = payload["case_id"]
        cp = self._case(case_id)

        if payload.get("student_id") != payload["actor"]["id"]:
            raise DomainError("student_id 必须与提交者 actor.id 一致")

        plan_id = payload["plan_id"]
        expected_rev = cp.latest_revision(plan_id) + 1
        if payload["revision"] != expected_rev:
            raise DomainError(f"方案 {plan_id} 下一版本应为 revision={expected_rev}，收到 {payload['revision']}")

        # 引用完整性
        for d in payload["decisions"]:
            self._require_refs_exist(case_id, d["target_problem_ids"], f"取舍 {d.get('label')} 的 target_problem_ids")
            self._require_refs_exist(case_id, d["evidence_refs"], f"取舍 {d.get('label')} 的 evidence_refs")
            if d["action"] == "merged":
                self._validate_merge(cp, plan_id, payload["revision"], d)

        self._check_duplication(cp, payload)
        self._check_interaction_ack(cp, payload)

        return self._append(
            event_type="PLAN_SUBMITTED",
            aggregate_id=f"{case_id}:plan:{payload['actor']['id']}",
            payload=payload, at=at,
            summary=f"提交方案第 {payload['revision']} 版，含 {len(payload['decisions'])} 项治疗取舍",
        )

    def _validate_merge(self, cp: CaseProjection, plan_id: str, revision: int, d: dict[str, Any]) -> None:
        """合并项必须能在上一版找到被合并治疗的来路；首版即合并的，只校验跨体系与来源标签。"""
        prior = cp.plan_revision(plan_id, revision - 1)
        if prior is not None:
            prior_labels = {
                old["label"]
                for old in prior["payload"]["decisions"]
                if old["action"] in ("merged", "retained")
            }
            missing = [part.get("label") for part in d["merged_from"] if part.get("label") not in prior_labels]
            if missing:
                raise DomainError(
                    f"合并 {d['label']} 的 merged_from 在上一版方案中找不到：{missing}；"
                    "每一次合并都要能说清合并了什么"
                )
        systems = {part.get("system") for part in d["merged_from"]}
        if None in systems or len(systems) < 2:
            raise DomainError(f"合并 {d['label']} 必须跨越至少两个体系；同体系删减应记为 retained/excluded")

    def _check_duplication(self, cp: CaseProjection, payload: dict[str, Any]) -> None:
        """同名成分在多个仍保留/合并的治疗中出现时，必须逐条确认重复是否有意。"""
        active = [d for d in payload["decisions"] if d["action"] in ("merged", "retained")]
        owners: dict[str, list[str]] = {}
        for d in active:
            for sub in d.get("substances", []):
                owners.setdefault(_norm(sub), []).append(d["decision_id"])
        duplicated = {s: ids for s, ids in owners.items() if len(set(ids)) > 1}
        acks = payload.get("duplication_acknowledgments", [])
        acked_pairs: set[tuple[str, str, str]] = {
            (_norm(a.get("substance", "")), a.get("decision_a", ""), a.get("decision_b", ""))
            for a in acks
        }
        for sub, ids in duplicated.items():
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    a, b = sorted((ids[i], ids[j]))
                    if (sub, a, b) not in acked_pairs:
                        raise DomainError(
                            f"治疗 {a} 与 {b} 含有同名成分且均被保留/合并，但未在 "
                            f"duplication_acknowledgments 中说明该重复是否有意、是否减量"
                        )

    def _check_interaction_ack(self, cp: CaseProjection, payload: dict[str, Any]) -> None:
        """方案保留的成分若命中在案的高危/禁忌相互作用旗标，必须逐条确认并说明处置。"""
        active_substances = {
            _norm(s)
            for d in payload["decisions"] if d["action"] in ("merged", "retained")
            for s in d.get("substances", [])
        }
        acks = {a.get("flag_id"): a for a in payload.get("interaction_acknowledgments", [])}
        for flag_id, rec in cp.interaction_flags.items():
            flag = rec.current
            if flag["severity"] not in ("high", "contraindicated"):
                continue  # 中低危由修订视图提示，不阻断提交
            flagged = {_norm(s) for s in flag["substances"]}
            # 相互作用是"组合"风险：旗标涉及的成分全部仍被保留/合并时才要求确认；
            # 组合中的任一方已被排除，该具体组合即不成立（其余旗标各自独立判定）。
            if flagged <= active_substances:
                ack = acks.get(flag_id)
                if ack is None or not ack.get("rationale") or not ack.get("resolution"):
                    raise DomainError(
                        f"方案保留了高危/禁忌相互作用旗标 {flag_id}（{'×'.join(flag['substances'])}）涉及的成分，"
                        "必须在 interaction_acknowledgments 中给出 rationale 与 resolution（调整/监测/停用）"
                    )

    # ================================================================ 教师意见层

    def record_opinion(self, payload: dict[str, Any], *, at: str | None = None) -> dict[str, Any]:
        """记录跨学科意见。支持/担忧/反对/替代并存，可用 relation_to 标明对其他意见的态度。"""
        self._require_role(payload, ("faculty",))
        self._require_active_course(payload["case_id"], payload["course_id"], at or _now(), actor_role="faculty")
        rel = payload.get("relation_to")
        if rel:
            if rel["opinion_id"] not in self._case(payload["case_id"]).opinions:
                raise DomainError(f"relation_to 引用的意见 {rel['opinion_id']} 不存在")
        return self._append(
            event_type="OPINION_RECORDED",
            aggregate_id=f"{payload['case_id']}:feedback",
            payload=payload, at=at,
            summary=f"{payload['discipline']}教师意见（{payload['stance']}）",
        )

    def correct_opinion(self, payload: dict[str, Any], *, at: str | None = None) -> dict[str, Any]:
        """教师只能更正本人意见；他人的不同意见只能并存，不能覆盖。"""
        self._require_role(payload, ("faculty",))
        cp = self._case(payload["case_id"])
        rec = cp.opinions.get(payload["opinion_id"])
        if rec is None:
            raise DomainError("被更正的意见不存在")
        if rec.current["actor"]["id"] != payload["actor"]["id"]:
            raise AuthorizationError("只能更正本人意见；对他人意见有异议请新发 OPINION_RECORDED 与之 dispute")
        return self._append(
            event_type="OPINION_CORRECTED",
            aggregate_id=f"{payload['case_id']}:feedback",
            payload=payload, at=at,
            summary=f"教师更正本人意见 {payload['opinion_id']}",
        )

    def record_simulation(self, payload: dict[str, Any], *, at: str | None = None) -> dict[str, Any]:
        self._require_role(payload, ("faculty",))
        self._require_active_course(payload["case_id"], payload["course_id"], at or _now(), actor_role="faculty")
        cp = self._case(payload["case_id"])
        plan = next((pid for pid, subs in cp.plans.items()
                     if any(s["payload"]["revision"] == payload["linked_revision"] for s in subs)), None)
        if plan is None:
            raise DomainError(f"模拟结果 linked_revision={payload['linked_revision']} 找不到对应方案版本")
        return self._append(
            event_type="SIMULATION_RECORDED",
            aggregate_id=f"{payload['case_id']}:feedback",
            payload=payload, at=at,
            summary=f"模拟结果（{payload['tool']}）关联方案第 {payload['linked_revision']} 版",
        )

    def record_case_review(self, payload: dict[str, Any], *, at: str | None = None) -> dict[str, Any]:
        """临床回顾：个案随访只能记为 individual_followup，不得升级为疗效结论。"""
        self._require_role(payload, ("faculty",))
        self._require_active_course(payload["case_id"], payload["course_id"], at or _now(), actor_role="faculty")
        return self._append(
            event_type="CASE_REVIEWED",
            aggregate_id=f"{payload['case_id']}:feedback",
            payload=payload, at=at,
            summary="临床回顾与实际随访登记",
        )

    def evaluate_competency(self, payload: dict[str, Any], *, at: str | None = None) -> dict[str, Any]:
        """能力评价：每个维度评分都必须引用方案/观察/意见事件作为证据。"""
        self._require_role(payload, ("faculty",))
        self._require_active_course(payload["case_id"], payload["course_id"], at or _now(), actor_role="faculty")
        self._require_refs_exist(
            payload["case_id"],
            [r for d in payload["dimensions"].values() for r in d.get("evidence_refs", [])],
            "能力评价 evidence_refs",
        )
        return self._append(
            event_type="COMPETENCY_EVALUATED",
            aggregate_id=f"{payload['case_id']}:feedback",
            payload=payload, at=at,
            summary=f"能力评价（{payload['evaluation_id']}）针对方案第 {payload['plan_revision']} 版",
        )

    # ================================================================ 通用重放入口（同步用）

    def ingest(self, event: dict[str, Any]) -> dict[str, Any]:
        """接受来自其他课程的已校验事件（同步通道）。

        授权与角色已在来源系统判定；这里只保证结构、版本连续性与幂等。
        成绩证据类事件的外发策略由 sync 模块在发送侧控制。
        """
        self.store.append(event)
        self.projection.apply(event)
        return event
