import tempfile
import unittest
from pathlib import Path

from src.events import EventStore
from src.services import AccessDenied, DomainError, TeachingCaseSystem

from scenario import CASE_ID, CONSENT, COURSE_ID, STUDENT_ID, build_system

AFTER_EXPIRY = "2027-01-05T09:00:00+08:00"


class AccessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.system = build_system()

    def test_grant_after_expiry_is_denied(self) -> None:
        with self.assertRaises(AccessDenied):
            self.system.grant_access(CASE_ID, "course-2027-spring", at=AFTER_EXPIRY)

    def test_learning_access_stops_after_expiry(self) -> None:
        allowed, reason = self.system.can_access(CASE_ID, COURSE_ID, at=AFTER_EXPIRY, purpose="learning")
        self.assertFalse(allowed)
        self.assertIn("到期", reason)

    def test_grade_evidence_is_retained_for_existing_course(self) -> None:
        allowed, _ = self.system.can_access(CASE_ID, COURSE_ID, at=AFTER_EXPIRY, purpose="grade_evidence")
        self.assertTrue(allowed)

    def test_new_course_has_no_access_after_expiry(self) -> None:
        allowed, _ = self.system.can_access(CASE_ID, "course-2027-spring", at=AFTER_EXPIRY, purpose="grade_evidence")
        self.assertFalse(allowed)

    def test_case_content_freezes_after_expiry(self) -> None:
        with self.assertRaises(DomainError):
            self.system.add_observation(CASE_ID, "obs-late", "symptom", "新症状",
                                        tradition="biomedicine", occurred_at=AFTER_EXPIRY)
        with self.assertRaises(DomainError):
            self.system.submit_plan(CASE_ID, STUDENT_ID, COURSE_ID,
                                    [{"item": "二甲双胍", "action": "keep",
                                      "rationale": {"text": "继续",
                                                    "references": [{"kind": "observation", "id": "obs-w2"}]}}],
                                    occurred_at=AFTER_EXPIRY)

    def test_grade_evidence_events_are_retained(self) -> None:
        self.system.record_expiry(CASE_ID, occurred_at=AFTER_EXPIRY)
        plan_id = TeachingCaseSystem.plan_id(CASE_ID, STUDENT_ID)
        plans = self.system.store.stream("student_plan", plan_id)
        feedback = self.system.store.stream("faculty_feedback", plan_id)
        self.assertEqual(len([e for e in plans if e.event_type == "PLAN_SUBMITTED"]), 2)
        self.assertEqual(len(feedback), 3)

    def test_consent_extension_reopens_access(self) -> None:
        self.system.update_consent(
            CASE_ID, "授权延期至 2027 学年",
            {**CONSENT, "valid_until": "2027-06-30T23:59:59+08:00"},
            occurred_at="2026-12-01T09:00:00+08:00",
        )
        self.system.grant_access(CASE_ID, "course-2027-spring", at=AFTER_EXPIRY)
        allowed, _ = self.system.can_access(CASE_ID, "course-2027-spring", at=AFTER_EXPIRY)
        self.assertTrue(allowed)


class GrantPersistenceTest(unittest.TestCase):
    def test_grants_survive_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "events.jsonl"
            grants_path = Path(tmp) / "grants.json"
            first = TeachingCaseSystem(EventStore(store_path), grants_path=grants_path)
            first.release_case(CASE_ID, "发布教学案", CONSENT,
                               occurred_at="2026-09-20T09:00:00+08:00", event_id="evt-case-0001")
            first.grant_access(CASE_ID, COURSE_ID, at="2026-09-21T09:00:00+08:00")

            reloaded = TeachingCaseSystem(EventStore(store_path), grants_path=grants_path)
            allowed, _ = reloaded.can_access(CASE_ID, COURSE_ID, at="2026-10-01T09:00:00+08:00")
            self.assertTrue(allowed)


if __name__ == "__main__":
    unittest.main()
