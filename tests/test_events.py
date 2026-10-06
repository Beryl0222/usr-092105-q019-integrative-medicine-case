"""事件信封与分层载荷校验测试。"""

import unittest

from src.errors import ValidationError
from src.events import (
    AGGREGATE_TYPES,
    EVENT_AGGREGATE,
    EVENT_TYPES,
    make_event,
    validate_event,
)
from src.store import EventStore


def envelope(**over):
    base = {
        "event_id": "evt-abcdef-0001",
        "event_type": "CASE_RELEASED",
        "aggregate_type": "teaching_case",
        "aggregate_id": "c1",
        "occurred_at": "2026-09-01T09:00:00+08:00",
        "version": 1,
        "summary": "测试事件",
    }
    base.update(over)
    return base


class EnvelopeTest(unittest.TestCase):
    def test_envelope_only_still_valid(self) -> None:
        self.assertEqual(validate_event(envelope()), [])

    def test_missing_fields(self) -> None:
        errors = validate_event({"event_id": "x"})
        self.assertTrue(any("event_type" in e for e in errors))

    def test_event_type_must_match_aggregate(self) -> None:
        errors = validate_event(envelope(event_type="PLAN_SUBMITTED", aggregate_type="teaching_case"))
        self.assertTrue(any("必须属于聚合" in e for e in errors))

    def test_aggregate_layer_completeness(self) -> None:
        self.assertEqual(set(AGGREGATE_TYPES),
                         {"teaching_case", "clinical_observation", "student_plan", "faculty_feedback"})
        self.assertEqual(set(EVENT_TYPES), set(EVENT_AGGREGATE))
        # 四类课程间同步通道都有事件
        layers = set(EVENT_AGGREGATE.values())
        self.assertEqual(layers, set(AGGREGATE_TYPES))

    def test_store_rejects_invalid(self) -> None:
        with self.assertRaises(ValidationError):
            EventStore().append(envelope(version=0))

    def test_make_event_assigns_aggregate(self) -> None:
        e = make_event("PLAN_SUBMITTED", "c1:plan:s1", {}, version=1, occurred_at="2026-09-10T09:00:00+08:00")
        self.assertEqual(e["aggregate_type"], "student_plan")
        self.assertEqual(validate_event(e), [])


def release_payload(**over):
    p = {
        "case_id": "c1",
        "actor": {"id": "admin-1", "role": "admin"},
        "title": "测试病例",
        "courses": ["course-a"],
        "consent": {
            "consent_id": "consent-1", "basis": "书面同意",
            "consented_at": "2026-08-21T10:00:00+08:00", "scope_text": "仅课程教学",
        },
        "de_identification": {
            "direct_identifiers_removed": True, "pseudonym": "P-001",
            "data_categories": ["症状"], "checked_by": "reviewer-1",
        },
        "authorization": {"valid_from": "2026-09-01T00:00:00+08:00",
                          "valid_until": "2027-01-31T23:59:59+08:00"},
    }
    p.update(over)
    return p


class PayloadValidationTest(unittest.TestCase):
    def test_release_ok(self) -> None:
        e = envelope(payload=release_payload())
        self.assertEqual(validate_event(e), [])

    def test_release_requires_consent_and_deidentification(self) -> None:
        p = release_payload()
        del p["consent"]
        errors = validate_event(envelope(payload=p))
        self.assertTrue(any("consent" in e for e in errors))

    def test_release_rejects_unremoved_identifiers(self) -> None:
        p = release_payload()
        p["de_identification"]["direct_identifiers_removed"] = False
        errors = validate_event(envelope(payload=p))
        self.assertTrue(any("直接标识" in e for e in errors))

    def test_release_valid_until_must_be_after_from(self) -> None:
        p = release_payload()
        p["authorization"]["valid_until"] = "2025-01-01T00:00:00+08:00"
        errors = validate_event(envelope(payload=p))
        self.assertTrue(any("valid_until" in e for e in errors))

    def test_tcm_pattern_requires_fact_links(self) -> None:
        p = {
            "case_id": "c1", "course_id": "course-a",
            "actor": {"id": "t1", "role": "faculty"},
            "observation_id": "o1", "layer": "tcm_observation", "category": "pattern",
            "pattern_name": "气虚", "text": "乏力", "observed_at": "2026-09-03T09:00:00+08:00",
        }
        errors = validate_event(envelope(event_type="OBSERVATION_ADDED",
                                         aggregate_type="clinical_observation", payload=p))
        self.assertTrue(any("linked_fact_ids" in e for e in errors))

    def test_plan_requires_rationale_and_refs(self) -> None:
        p = {
            "case_id": "c1", "course_id": "course-a",
            "actor": {"id": "s1", "role": "student"},
            "plan_id": "pl1", "revision": 1, "student_id": "s1",
            "decisions": [{
                "decision_id": "d1", "label": "药甲", "system": "western",
                "action": "retained",
                "rationale": "",
                "target_problem_ids": [], "evidence_refs": [], "substances": [],
            }],
        }
        errors = validate_event(envelope(event_type="PLAN_SUBMITTED",
                                         aggregate_type="student_plan", payload=p))
        self.assertTrue(any("rationale" in e for e in errors))
        self.assertTrue(any("target_problem_ids" in e for e in errors))

    def test_merge_must_cross_systems(self) -> None:
        p = {
            "case_id": "c1", "course_id": "course-a",
            "actor": {"id": "s1", "role": "student"},
            "plan_id": "pl1", "revision": 1, "student_id": "s1",
            "decisions": [{
                "decision_id": "d1", "label": "伪合并", "system": "western", "action": "merged",
                "rationale": "依据", "target_problem_ids": ["pr1"], "evidence_refs": ["ev1"],
                "merged_from": [
                    {"label": "药甲", "system": "western"},
                    {"label": "药乙", "system": "western"},
                ],
            }],
        }
        errors = validate_event(envelope(event_type="PLAN_SUBMITTED",
                                         aggregate_type="student_plan", payload=p))
        self.assertTrue(any("跨越至少两个体系" in e for e in errors))

    def test_validated_outcome_requires_interventional_citation(self) -> None:
        p = {
            "case_id": "c1", "course_id": "course-a",
            "actor": {"id": "s1", "role": "student"},
            "mechanism_id": "m1", "title": "机制",
            "claim_scope": "validated_outcome",
            "linked_refs": ["pr1"],
            "citations": [{"design": "case_series"}],
        }
        errors = validate_event(envelope(event_type="MECHANISM_PROPOSED",
                                         aggregate_type="clinical_observation", payload=p))
        self.assertTrue(any("干预性研究" in e for e in errors))

    def test_interaction_flag_forbids_efficacy_claim(self) -> None:
        p = {
            "case_id": "c1", "course_id": "course-a",
            "actor": {"id": "s1", "role": "student"},
            "flag_id": "f1", "substances": ["A", "B"], "risk_text": "出血",
            "severity": "high", "references": [{"name": "手册"}],
            "is_efficacy_claim": True,
        }
        errors = validate_event(envelope(event_type="INTERACTION_FLAGGED",
                                         aggregate_type="clinical_observation", payload=p))
        self.assertTrue(any("疗效断言" in e for e in errors))

    def test_competency_requires_evidence_refs(self) -> None:
        p = {
            "case_id": "c1", "course_id": "course-a",
            "actor": {"id": "t1", "role": "faculty"},
            "evaluation_id": "ev1", "student_id": "s1", "plan_revision": 1,
            "dimensions": {"整合能力": {"score": 80}},
        }
        errors = validate_event(envelope(event_type="COMPETENCY_EVALUATED",
                                         aggregate_type="faculty_feedback", payload=p))
        self.assertTrue(any("evidence_refs" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
