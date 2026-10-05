import unittest

from src.events import EventStore
from src.services import Projection
from src.sync import export_events, import_events
from src.validator import validate_event

from scenario import CASE_ID, STUDENT_ID, build_system
from src.services import TeachingCaseSystem


class SyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = build_system()

    def test_exported_records_match_envelope(self) -> None:
        records = export_events(self.source.store)
        self.assertEqual(len(records), len(self.source.store.all()))
        for record in records:
            self.assertEqual(validate_event(record), [])
        aggregates = {r["aggregate_type"] for r in records}
        self.assertEqual(
            aggregates,
            {"teaching_case", "clinical_observation", "student_plan", "faculty_feedback"},
        )

    def test_import_into_empty_store(self) -> None:
        records = export_events(self.source.store)
        target = EventStore()
        result = import_events(target, records)
        self.assertEqual(len(result["imported"]), len(records))
        self.assertEqual(result["errors"], [])
        self.assertEqual(
            [e.to_dict() for e in target.all()],
            [e.to_dict() for e in self.source.store.all()],
        )

    def test_retry_with_same_event_id_is_idempotent(self) -> None:
        records = export_events(self.source.store)
        target = EventStore()
        import_events(target, records)
        retry = import_events(target, records)
        self.assertEqual(retry["imported"], [])
        self.assertEqual(len(retry["skipped_duplicates"]), len(records))
        self.assertEqual(len(target.all()), len(records))

    def test_invalid_record_is_reported_not_imported(self) -> None:
        target = EventStore()
        result = import_events(target, [{"event_id": "evt-bad-0001"}])
        self.assertEqual(result["imported"], [])
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(target.all(), [])

    def test_projection_consistent_after_sync(self) -> None:
        target = EventStore()
        import_events(target, export_events(self.source.store))
        plan_id = TeachingCaseSystem.plan_id(CASE_ID, STUDENT_ID)
        self.assertEqual(
            len(Projection(target).plan_revisions(plan_id)),
            len(Projection(self.source.store).plan_revisions(plan_id)),
        )


if __name__ == "__main__":
    unittest.main()
