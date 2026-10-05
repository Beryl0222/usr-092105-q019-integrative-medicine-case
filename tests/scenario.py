"""各测试共用的中文教学场景：2 型糖尿病融合教学案。"""

from __future__ import annotations

from src.events import EventStore
from src.services import TeachingCaseSystem

CASE_ID = "case-tang-001"
COURSE_ID = "course-2026-autumn"
STUDENT_ID = "student-zhou"
CONSENT = {
    "scope": "teaching",
    "deidentified": True,
    "valid_until": "2026-12-31T23:59:59+08:00",
    "consent_id": "consent-2026-0918",
}


def build_system(store: EventStore | None = None) -> TeachingCaseSystem:
    system = TeachingCaseSystem(store or EventStore())
    system.release_case(
        CASE_ID, "发布 2 型糖尿病融合医学教学案（已脱敏）", CONSENT,
        occurred_at="2026-09-20T09:00:00+08:00", event_id="evt-case-0001",
    )
    system.grant_access(CASE_ID, COURSE_ID, at="2026-09-21T09:00:00+08:00")

    system.add_observation(CASE_ID, "obs-w1", "symptom", "口干多饮、体重下降",
                           tradition="biomedicine", occurred_at="2026-09-22T09:00:00+08:00",
                           event_id="evt-obs-0001")
    system.add_observation(CASE_ID, "obs-w2", "exam_result", "空腹血糖 9.8 mmol/L，HbA1c 8.4%",
                           tradition="biomedicine", occurred_at="2026-09-22T09:05:00+08:00",
                           event_id="evt-obs-0002")
    system.add_observation(CASE_ID, "obs-t1", "pattern_observation", "舌红少津、脉细数，辨为阴虚燥热",
                           tradition="tcm", occurred_at="2026-09-22T09:10:00+08:00",
                           event_id="evt-obs-0003")
    system.add_observation(CASE_ID, "obs-p1", "problem_statement", "血糖控制不佳",
                           linked_observations=["obs-w1", "obs-w2"],
                           occurred_at="2026-09-23T10:00:00+08:00", event_id="evt-obs-0004")

    # 第 1 版方案：两套术语并排，未识别重复用药。
    system.submit_plan(
        CASE_ID, STUDENT_ID, COURSE_ID,
        decisions=[
            {"item": "格列本脲", "action": "keep",
             "rationale": {"text": "空腹血糖仍高，继续磺脲类降糖",
                           "references": [{"kind": "observation", "id": "obs-w2"}]}},
            {"item": "消渴丸", "action": "keep",
             "rationale": {"text": "阴虚燥热证候明显，保留中成药",
                           "references": [{"kind": "observation", "id": "obs-t1"}]}},
        ],
        note="初版方案", occurred_at="2026-09-25T14:00:00+08:00", event_id="evt-plan-0001",
    )

    # 新事实：识别出重复用药冲突。
    system.add_observation(CASE_ID, "obs-x1", "drug_interaction", "消渴丸含格列本脲，两药存在重复用药",
                           involves=["格列本脲", "消渴丸"], interaction_kind="duplication",
                           occurred_at="2026-09-26T09:00:00+08:00", event_id="evt-obs-0005")

    # 两位教师意见分歧，并存保留。
    fb_a = system.sign_feedback(
        CASE_ID, STUDENT_ID, "faculty-chen", "内分泌科", "cross_discipline_opinion",
        "建议停用消渴丸，避免磺脲类成分叠加导致低血糖",
        targets=["消渴丸"], occurred_at="2026-09-26T15:00:00+08:00", event_id="evt-fb-0001",
    )
    system.sign_feedback(
        CASE_ID, STUDENT_ID, "faculty-li", "中医科", "cross_discipline_opinion",
        "可保留消渴丸但需减量并加强血糖监测，不认同直接停用",
        targets=["消渴丸"], occurred_at="2026-09-27T10:00:00+08:00", event_id="evt-fb-0002",
    )

    # 新事实：共同解释的问题表述。
    system.add_observation(CASE_ID, "obs-p2", "problem_statement", "阴虚燥热与高血糖相互影响的共同问题",
                           linked_observations=["obs-w2", "obs-t1"],
                           occurred_at="2026-09-27T11:00:00+08:00", event_id="evt-obs-0006")

    # 第 2 版方案：基于冲突与教师意见做出取舍。
    system.submit_plan(
        CASE_ID, STUDENT_ID, COURSE_ID,
        decisions=[
            {"item": "格列本脲", "action": "keep",
             "rationale": {"text": "单药继续，剂量不变",
                           "references": [{"kind": "observation", "id": "obs-w2"}]}},
            {"item": "消渴丸", "action": "merge",
             "rationale": {"text": "与格列本脲成分重复，合并为单药方案以避免低血糖",
                           "references": [{"kind": "observation", "id": "obs-x1"},
                                          {"kind": "feedback", "id": fb_a.event_id}]}},
        ],
        note="根据重复用药冲突修订", occurred_at="2026-09-28T14:00:00+08:00", event_id="evt-plan-0002",
    )

    system.record_simulation(
        CASE_ID, STUDENT_ID, COURSE_ID, "低血糖情景模拟",
        {"result": "通过", "notes": "合并用药后未再出现低血糖"},
        occurred_at="2026-09-29T10:00:00+08:00", event_id="evt-sim-0001",
    )
    system.sign_feedback(
        CASE_ID, STUDENT_ID, "faculty-chen", "内分泌科", "competency_feedback",
        "能基于相互作用证据调整方案",
        dimensions=[{"dimension": "整合问题表述", "level": 3},
                    {"dimension": "取舍依据", "level": 4}],
        occurred_at="2026-09-30T09:00:00+08:00", event_id="evt-fb-0003",
    )
    return system
