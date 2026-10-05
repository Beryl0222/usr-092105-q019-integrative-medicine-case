import unittest

from src.analytics import course_report, plan_progress
from src.services import Projection, TeachingCaseSystem

from scenario import CASE_ID, COURSE_ID, STUDENT_ID, build_system


class AnalyticsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.system = build_system()
        self.proj = Projection(self.system.store)
        self.plan_id = TeachingCaseSystem.plan_id(CASE_ID, STUDENT_ID)

    def test_progress_across_revisions(self) -> None:
        progress = plan_progress(self.proj, CASE_ID, self.plan_id)
        self.assertEqual([p["revision"] for p in progress], [1, 2])
        first, last = progress
        # 第 1 版：问题表述只连接西医观察，共同解释率为 0。
        self.assertEqual(first["joint_explanation_ratio"], 0.0)
        # 第 2 版：obs-p2 同时连接两套观察，共同解释率上升。
        self.assertEqual(last["joint_explanation_ratio"], 0.5)
        # 取舍有据率两版都为 1（依据均引用事实层记录）。
        self.assertEqual(first["decision_grounding_ratio"], 1.0)
        self.assertEqual(last["decision_grounding_ratio"], 1.0)
        self.assertLess(last["juxtaposition_index"], first["juxtaposition_index"])

    def test_course_report_marks_improvement(self) -> None:
        report = course_report(self.proj, COURSE_ID)
        self.assertEqual(report["student_count"], 1)
        student = report["students"][0]
        self.assertTrue(student["improving"])
        self.assertFalse(student["still_juxtaposing"])
        self.assertEqual(report["flagged_plans"], [])

    def test_course_report_flags_juxtaposition(self) -> None:
        # 另一名学生的方案只引用教师意见、不连接事实，且从未改进。
        self.system.sign_feedback(
            CASE_ID, "student-wang", "faculty-chen", "内分泌科", "cross_discipline_opinion",
            "建议再斟酌", occurred_at="2026-09-24T09:00:00+08:00", event_id="evt-fb-0009",
        )
        self.system.submit_plan(
            CASE_ID, "student-wang", COURSE_ID,
            decisions=[{"item": "消渴丸", "action": "keep",
                        "rationale": {"text": "老师建议保留",
                                      "references": [{"kind": "feedback", "id": "evt-fb-0009"}]}}],
            occurred_at="2026-09-26T09:00:00+08:00", event_id="evt-plan-0009",
        )
        proj = Projection(self.system.store)
        report = course_report(proj, COURSE_ID)
        self.assertEqual(report["student_count"], 2)
        wang_plan = TeachingCaseSystem.plan_id(CASE_ID, "student-wang")
        self.assertIn(wang_plan, report["flagged_plans"])
        wang = next(s for s in report["students"] if s["plan_id"] == wang_plan)
        self.assertEqual(wang["revisions"][0]["decision_grounding_ratio"], 0.0)
        self.assertTrue(wang["still_juxtaposing"])


if __name__ == "__main__":
    unittest.main()
