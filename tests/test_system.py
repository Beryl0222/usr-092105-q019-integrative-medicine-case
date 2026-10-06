"""端到端领域规则测试：授权生命周期、中立性守卫、修订视图、跨课程同步。"""

import unittest

from src.errors import AuthorizationError, ConcurrencyError, DomainError, ValidationError
from src.projections import Projection
from src.revision import build_revision_view, render_revision_markdown
from src.scenario import (
    CASE_ID, COURSE_A, COURSE_B, COURSE_OUTSIDE, build_scenario,
)
from src.store import EventStore
from src.sync import CourseBus
from src.system import TeachingCaseSystem


class ScenarioInvariantsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scenario = build_scenario()
        cls.sys = cls.scenario["system"]

    def test_expected_guard_rejections(self) -> None:
        rejected = self.scenario["rejected"]
        self.assertIn("机制越界为疗效", rejected)
        self.assertIn("v1未确认重复与相互作用", rejected)
        self.assertIn("v1未处理高危相互作用", rejected)
        self.assertIn("教师覆盖他人意见被拒", rejected)
        self.assertIn("同体系伪合并被拒", rejected)
        self.assertIn("个案随访越界为疗效", rejected)
        self.assertIn("到期后新增观察被拒", rejected)

    def test_layered_streams_have_continuous_versions(self) -> None:
        for aggregate_id, stream in {
            aid: self.sys.store.stream(aid) for aid in {
                e["aggregate_id"] for e in self.sys.store.all_events()
            }
        }.items():
            versions = [e["version"] for e in stream]
            self.assertEqual(versions, list(range(1, len(versions) + 1)), f"{aggregate_id} 版本不连续")

    def test_student_cannot_write_to_unauthorized_course(self) -> None:
        with self.assertRaises(AuthorizationError):
            self.sys.add_observation({
                "case_id": CASE_ID, "course_id": COURSE_OUTSIDE,
                "actor": {"id": "s99", "role": "student"},
                "observation_id": "obs-x", "layer": "fact", "category": "symptom",
                "text": "越权课程写入", "observed_at": "2026-10-01T08:00:00+08:00",
            })

    def test_expired_case_keeps_grade_evidence_anonymized(self) -> None:
        cp = self.sys.projection.case(CASE_ID)
        evidence = cp.grade_evidence()
        self.assertEqual(len(evidence), 1)
        item = evidence[0]
        self.assertEqual(item["retention_grade"], "retain_anonymized")
        self.assertIn("student_pseudonym", item)
        self.assertNotIn("student_id", item)
        # 维度评分与证据来路仍然完整保留
        self.assertEqual(set(item["dimensions"]),
                         {"事实与证候分层", "共同问题解释", "治疗取舍依据", "证据边界自觉"})

    def test_access_status_transitions(self) -> None:
        cp = self.sys.projection.case(CASE_ID)
        ok, _ = cp.access_status(COURSE_A, "2026-09-15T00:00:00+08:00")
        self.assertTrue(ok)
        ok, reason = cp.access_status(COURSE_A, "2027-03-01T00:00:00+08:00")
        self.assertFalse(ok)
        self.assertIn("consent_expired", reason)
        ok, reason = cp.access_status(COURSE_OUTSIDE, "2026-09-15T00:00:00+08:00")
        self.assertFalse(ok)
        self.assertIn("同意范围", reason)

    def test_faculty_disagreements_coexist(self) -> None:
        cp = self.sys.projection.case(CASE_ID)
        self.assertIn("op-west-bleeding", cp.opinions)
        self.assertIn("op-tcm-ginkgo", cp.opinions)
        self.assertEqual(cp.opinions["op-tcm-ginkgo"].current["relation_to"]["relation"], "disputes")

    def test_observation_correction_keeps_history(self) -> None:
        cp = self.sys.projection.case(CASE_ID)
        rec = cp.observations["obs-hba1c"]
        self.assertEqual(rec.current["lab_value"]["method"], "HPLC")
        self.assertEqual(len(rec.history), 2)  # 原始 + 更正

    def test_conflict_cannot_be_deleted(self) -> None:
        cp = self.sys.projection.case(CASE_ID)
        conflict = cp.conflicts["conflict-antiplatelet-huoxue"]
        self.assertEqual(conflict.current["status"], "open")
        self.assertGreaterEqual(len(conflict.history), 1)


class RevisionViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scenario = build_scenario()
        cls.case = cls.scenario["system"].projection.case(CASE_ID)

    def test_revision1_shows_juxtaposition(self) -> None:
        v1 = build_revision_view(self.case, "plan-2026-017", 1)
        m = v1["metrics"]
        self.assertEqual(m["decision_counts"], {"merged": 0, "retained": 7, "excluded": 0, "deferred": 0})
        self.assertEqual(m["cross_system_merges"], [])
        self.assertTrue(any("全部并列保留" in s for s in m["juxtaposition_signals"]))
        # 第 1 版四栏都有来路
        self.assertGreaterEqual(len(v1["columns"]["new_facts"]), 6)
        self.assertEqual(len(v1["columns"]["conflicts"]), 1)
        self.assertEqual(len(v1["columns"]["treatment_decisions"]), 7)
        self.assertEqual(len(v1["columns"]["faculty_input"]["all_opinions"]), 3)

    def test_revision2_shows_real_integration(self) -> None:
        v2 = build_revision_view(self.case, "plan-2026-017", 2)
        m = v2["metrics"]
        self.assertEqual(m["decision_counts"]["merged"], 2)
        self.assertEqual(m["decision_counts"]["excluded"], 2)
        self.assertEqual(len(m["cross_system_merges"]), 2)
        self.assertEqual(m["previous_decision_counts"]["retained"], 7)
        # 银杏/血府逐瘀有明确排除，没有悄悄删药
        self.assertEqual(v2["columns"]["silent_drops"], [])
        labels = {d["label"]: d for d in v2["columns"]["treatment_decisions"]}
        self.assertEqual(labels["银杏叶片"]["change_from_previous"], "retained->excluded")
        self.assertEqual(labels["银杏叶片"]["exclusion_reason"], "interaction_risk")
        self.assertEqual(labels["血府逐瘀汤"]["exclusion_reason"], "duplication")
        # 上一版两位教师的分歧被本版取舍引用
        opinions = v2["columns"]["faculty_input"]["all_opinions"]
        informed = {o["opinion_id"] for o in opinions if o.get("informed_this_revision")}
        self.assertIn("op-tcm-ginkgo", informed)
        self.assertIn("op-west-bleeding", informed)
        # 新增事实窗口只含 v1→v2 之间的那条
        self.assertEqual([f["observation_id"] for f in v2["columns"]["new_facts"]], ["obs-ecchymosis"])
        self.assertEqual(len(v2["columns"]["interactions"]), 1)

    def test_markdown_renders_four_columns_and_metrics(self) -> None:
        v2 = build_revision_view(self.case, "plan-2026-017", 2)
        md = render_revision_markdown(v2)
        self.assertIn("新增事实 / 冲突识别 / 治疗取舍 / 教师分歧", md)
        self.assertIn("跨体系合并：2", md)
        self.assertIn("被本版取舍引用", md)

    def test_missing_revision_raises(self) -> None:
        with self.assertRaises(KeyError):
            build_revision_view(self.case, "plan-2026-017", 9)


class StoreTest(unittest.TestCase):
    def test_idempotent_retry_and_conflicting_retry(self) -> None:
        store = EventStore()
        e = {
            "event_id": "evt-retry-0001", "event_type": "ACCESS_EXPIRED",
            "aggregate_type": "teaching_case", "aggregate_id": "c1",
            "occurred_at": "2027-02-01T00:00:00+08:00", "version": 1, "summary": "到期",
        }
        store.append(e)
        store.append(dict(e))  # 完全相同重试：幂等
        with self.assertRaises(ConcurrencyError):
            store.append({**e, "summary": "被篡改的重试"})
        with self.assertRaises(ConcurrencyError):
            store.append({**e, "version": 3})

    def test_rebuild_from_events(self) -> None:
        scenario = build_scenario()
        events = scenario["system"].store.all_events()
        rebuilt = Projection().rebuild(events)
        self.assertIn(CASE_ID, rebuilt)
        self.assertEqual(len(rebuilt[CASE_ID].plans.get("plan-2026-017", [])), 2)


class SyncTest(unittest.TestCase):
    def test_fanout_tombstone_and_retention(self) -> None:
        source = build_scenario()["system"]
        a, b, outside = TeachingCaseSystem(), TeachingCaseSystem(), TeachingCaseSystem()
        bus = CourseBus()
        bus.register(COURSE_A, a)
        bus.register(COURSE_B, b)
        bus.register(COURSE_OUTSIDE, outside)

        counts = bus.publish(source)
        self.assertEqual(counts[COURSE_B], 25)  # 授权课程：除成绩证据外的全部事件
        self.assertNotIn(COURSE_OUTSIDE, counts)
        self.assertEqual(len(outside.store.all_events()), 0)

        # 成绩证据不跨课程外发
        self.assertFalse(any(e["event_type"] == "COMPETENCY_EVALUATED"
                             for e in b.store.all_events()))

        # 幂等：第二次同步不产生新投递
        self.assertEqual(bus.publish(source), {})
        dupes = [d for d in bus.delivery_log if d["status"] == "duplicate"]
        self.assertTrue(dupes)

        # 课程 B 收到墓碑，到期后同样无法继续访问
        cp_b = b.projection.case(CASE_ID)
        ok, _ = cp_b.access_status(COURSE_B, "2026-11-01T00:00:00+08:00")
        self.assertTrue(ok)
        ok, reason = cp_b.access_status(COURSE_B, "2027-03-01T00:00:00+08:00")
        self.assertFalse(ok)
        self.assertIn("consent_expired", reason)

    def test_orphan_event_rejected(self) -> None:
        source = build_scenario()["system"]
        a = TeachingCaseSystem()
        bus = CourseBus()
        bus.register(COURSE_A, a)
        # 只同步一条业务事件、没有 CASE_RELEASED → 接收侧拒绝孤立事件
        events = [e for e in source.store.all_events() if e["event_type"] == "OBSERVATION_ADDED"][:1]
        with self.assertRaises(AuthorizationError):
            for e in events:
                bus._deliver_one(a, COURSE_A, e)

    def test_grade_export_opt_in(self) -> None:
        source = build_scenario()["system"]
        b = TeachingCaseSystem()
        bus = CourseBus()
        bus.register(COURSE_B, b)
        bus.publish(source, allow_grade_export=True)
        self.assertTrue(any(e["event_type"] == "COMPETENCY_EVALUATED"
                            for e in b.store.all_events()))


if __name__ == "__main__":
    unittest.main()
