import unittest

from src.revision import compare_revisions, render_side_by_side
from src.services import Projection, TeachingCaseSystem

from scenario import CASE_ID, STUDENT_ID, build_system


class RevisionViewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.system = build_system()
        self.proj = Projection(self.system.store)
        self.plan_id = TeachingCaseSystem.plan_id(CASE_ID, STUDENT_ID)
        self.view = compare_revisions(self.proj, CASE_ID, self.plan_id, 1, 2)

    def test_new_facts_in_window(self) -> None:
        fact_ids = {f["obs_id"] for f in self.view["new_facts"]}
        self.assertEqual(fact_ids, {"obs-x1", "obs-p2"})

    def test_conflicts_identified(self) -> None:
        conflicts = self.view["conflicts_identified"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["interaction_kind"], "duplication")
        self.assertEqual(conflicts[0]["involves"], ["格列本脲", "消渴丸"])

    def test_trade_offs_show_action_change_and_rationale(self) -> None:
        trade_offs = {t["item"]: t for t in self.view["trade_offs"]}
        self.assertEqual(set(trade_offs), {"消渴丸"})
        change = trade_offs["消渴丸"]
        self.assertEqual((change["before"], change["after"]), ("keep", "merge"))
        ref_ids = {r["id"] for r in change["rationale"]["references"]}
        self.assertIn("obs-x1", ref_ids)
        self.assertIn("evt-fb-0001", ref_ids)

    def test_faculty_disagreements_carry_provenance(self) -> None:
        disagreements = self.view["faculty_disagreements"]
        self.assertEqual(len(disagreements), 2)
        by_faculty = {d["faculty_id"]: d for d in disagreements}
        self.assertEqual(set(by_faculty), {"faculty-chen", "faculty-li"})
        for d in disagreements:
            self.assertTrue(d["event_id"].startswith("evt-fb-"))
            self.assertTrue(d["occurred_at"])

    def test_render_side_by_side(self) -> None:
        text = render_side_by_side(self.view)
        for header in ("【新增事实】", "【冲突识别】", "【治疗取舍】", "【教师分歧】"):
            self.assertIn(header, text)
        self.assertIn("保留 → 合并", text)
        self.assertIn("faculty-li", text)

    def test_missing_revision_raises(self) -> None:
        with self.assertRaises(ValueError):
            compare_revisions(self.proj, CASE_ID, self.plan_id, 1, 9)


if __name__ == "__main__":
    unittest.main()
