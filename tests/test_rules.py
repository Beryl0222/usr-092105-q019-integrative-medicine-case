import unittest

from src.events import EventStore
from src.services import DomainError, Projection, TeachingCaseSystem

from scenario import CASE_ID, COURSE_ID, STUDENT_ID, build_system


class MechanismRuleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.system = build_system()

    def test_correlation_cannot_claim_efficacy(self) -> None:
        with self.assertRaises(DomainError) as ctx:
            self.system.add_observation(
                CASE_ID, "obs-m1", "candidate_mechanism", "某方剂改善胰岛素抵抗",
                evidence_kind="correlation", claim_strength="efficacy",
                occurred_at="2026-10-01T09:00:00+08:00",
            )
        self.assertTrue(any("疗效" in e for e in ctx.exception.errors))

    def test_correlation_may_claim_association(self) -> None:
        event = self.system.add_observation(
            CASE_ID, "obs-m1", "candidate_mechanism", "某方剂改善胰岛素抵抗",
            evidence_kind="correlation", claim_strength="association",
            occurred_at="2026-10-01T09:00:00+08:00",
        )
        self.assertEqual(event.payload["claim_strength"], "association")

    def test_mechanism_cannot_be_marked_confirmed(self) -> None:
        with self.assertRaises(DomainError) as ctx:
            self.system.add_observation(
                CASE_ID, "obs-m2", "candidate_mechanism", "某机制",
                evidence_kind="clinical_trial", claim_strength="efficacy", status="confirmed",
                occurred_at="2026-10-01T09:00:00+08:00",
            )
        self.assertTrue(any("candidate" in e for e in ctx.exception.errors))


class DecisionRuleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.system = build_system()

    def _submit(self, decisions) -> None:
        self.system.submit_plan(
            CASE_ID, STUDENT_ID, COURSE_ID, decisions,
            occurred_at="2026-10-02T09:00:00+08:00",
        )

    def test_decision_requires_rationale_text(self) -> None:
        with self.assertRaises(DomainError) as ctx:
            self._submit([{"item": "二甲双胍", "action": "keep",
                           "rationale": {"text": "", "references": [{"kind": "observation", "id": "obs-w2"}]}}])
        self.assertTrue(any("依据" in e for e in ctx.exception.errors))

    def test_decision_requires_references(self) -> None:
        with self.assertRaises(DomainError) as ctx:
            self._submit([{"item": "二甲双胍", "action": "keep",
                           "rationale": {"text": "继续用药", "references": []}}])
        self.assertTrue(any("引用" in e for e in ctx.exception.errors))

    def test_decision_reference_must_exist(self) -> None:
        with self.assertRaises(DomainError) as ctx:
            self._submit([{"item": "二甲双胍", "action": "keep",
                           "rationale": {"text": "继续用药",
                                         "references": [{"kind": "observation", "id": "obs-不存在"}]}}])
        self.assertTrue(any("不存在" in e for e in ctx.exception.errors))

    def test_system_priority_is_rejected(self) -> None:
        with self.assertRaises(DomainError) as ctx:
            self._submit([{"item": "二甲双胍", "action": "keep", "system_priority": "biomedicine",
                           "rationale": {"text": "西医优先",
                                         "references": [{"kind": "observation", "id": "obs-w2"}]}}])
        self.assertTrue(any("优先" in e for e in ctx.exception.errors))


class FeedbackCoexistenceTest(unittest.TestCase):
    def test_disagreeing_feedback_coexists(self) -> None:
        system = build_system()
        proj = Projection(system.store)
        plan_id = TeachingCaseSystem.plan_id(CASE_ID, STUDENT_ID)
        opinions = [
            e for e in proj.feedback[plan_id]
            if e.payload.get("kind") == "cross_discipline_opinion"
        ]
        self.assertEqual(len(opinions), 2)
        disciplines = {e.payload["discipline"] for e in opinions}
        self.assertEqual(disciplines, {"内分泌科", "中医科"})


if __name__ == "__main__":
    unittest.main()
