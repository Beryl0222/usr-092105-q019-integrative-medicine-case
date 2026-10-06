"""一个完整的中文融合医学教学案场景，供演示与测试复用。

病例：62 岁女性，2 型糖尿病、高血压，活动后胸闷、乏力；舌暗有齿痕、脉细涩。
学生第 1 版把西医药物与十余味中药并排抄录（被相互作用/重复用药守卫两次拦下后
带确认提交，但结构上仍是拼贴）；两学科教师分歧并存；第 2 版学生做出跨体系合并、
有依据地排除，并被模拟、临床回顾与能力评价跟进；授权到期后停止新课程访问，
成绩证据按规则匿名保留。
"""

from __future__ import annotations

from typing import Any

from .errors import AuthorizationError, DomainError, ValidationError
from .system import TeachingCaseSystem

CASE_ID = "case-dm-htn-2026-001"
COURSE_A = "course-integrmed-2026-aut"          # 开课课程：中西医结合思路
COURSE_B = "course-tcm-classical-2026"          # 共同使用该病例的第二门课
COURSE_OUTSIDE = "course-pediatrics-2026"       # 不在同意范围内的课程

ADMIN = {"id": "teacher-office-admin", "role": "admin"}
STUDENT = {"id": "stu-2026-017", "role": "student"}
F_WEST = {"id": "faculty-neixue-li", "role": "faculty"}
F_TCM = {"id": "faculty-jingfang-wang", "role": "faculty"}
SYSTEM = {"id": "consent-guardian", "role": "system"}


def build_scenario() -> dict[str, Any]:
    sys_ = TeachingCaseSystem()
    rejected: list[dict[str, str]] = {}
    ids: dict[str, Any] = {}

    def attempt(label: str, fn):
        try:
            return fn()
        except (DomainError, ValidationError, AuthorizationError) as exc:  # noqa: PERF203
            rejected[label] = str(exc)
            return None

    # ------------------------------------------------------------ 授权层

    sys_.release_case({
        "case_id": CASE_ID,
        "actor": ADMIN,
        "title": "62岁女性：2型糖尿病合并高血压，活动后胸闷、乏力",
        "courses": [COURSE_A, COURSE_B],
        "consent": {
            "consent_id": "consent-2026-08-21-007",
            "basis": "本人签署的脱敏教学病例使用同意书",
            "consented_at": "2026-08-21T10:00:00+08:00",
            "scope_text": "同意脱敏后用于中西医结合临床思路与中医经典两门课程的课堂教学与形成性评价，不得用于商业培训",
        },
        "de_identification": {
            "direct_identifiers_removed": True,
            "pseudonym": "DM-HTN-007",
            "data_categories": ["症状", "体征", "舌脉", "实验室", "影像", "诊疗经过"],
            "checked_by": "病案室脱敏审核员 zhou",
        },
        "authorization": {"valid_from": "2026-09-01T00:00:00+08:00",
                          "valid_until": "2027-01-31T23:59:59+08:00"},
    }, at="2026-09-01T09:00:00+08:00")

    # ------------------------------------------------------------ 事实 / 证候层

    e = sys_.add_observation({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": STUDENT,
        "observation_id": "obs-chest-tightness", "layer": "fact", "category": "symptom",
        "text": "活动后胸闷、气短3月，伴倦怠乏力，无夜间阵发性呼吸困难",
        "observed_at": "2026-09-03T08:30:00+08:00",
    }, at="2026-09-03T09:00:00+08:00")
    ids["evt_chest"] = e["event_id"]

    e = sys_.add_observation({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": STUDENT,
        "observation_id": "obs-hba1c", "layer": "fact", "category": "lab",
        "text": "糖化血红蛋白 8.4%，空腹血糖 9.1 mmol/L",
        "lab_value": {"value": 8.4, "unit": "%", "marker": "HbA1c"},
        "observed_at": "2026-09-03T08:40:00+08:00",
    }, at="2026-09-03T09:05:00+08:00")
    ids["evt_hba1c"] = e["event_id"]

    e = sys_.add_observation({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": STUDENT,
        "observation_id": "obs-platelet", "layer": "fact", "category": "lab",
        "text": "血小板 198×10^9/L，凝血功能正常范围",
        "lab_value": {"value": 198, "unit": "10^9/L", "marker": "PLT"},
        "observed_at": "2026-09-03T08:41:00+08:00",
    }, at="2026-09-03T09:06:00+08:00")

    e = sys_.add_observation({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": F_TCM,
        "observation_id": "obs-tongue", "layer": "tcm_observation", "category": "tongue",
        "text": "舌质暗淡，边有齿痕，苔薄白微腻，舌下脉络迂曲",
        "observed_at": "2026-09-03T09:10:00+08:00",
    }, at="2026-09-03T09:20:00+08:00")
    ids["evt_tongue"] = e["event_id"]

    e = sys_.add_observation({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": F_TCM,
        "observation_id": "obs-pulse", "layer": "tcm_observation", "category": "pulse",
        "text": "脉细涩，寸口尤甚",
        "observed_at": "2026-09-03T09:11:00+08:00",
    }, at="2026-09-03T09:21:00+08:00")

    e = sys_.add_observation({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": F_TCM,
        "observation_id": "obs-pattern-qiyin", "layer": "tcm_observation", "category": "pattern",
        "pattern_name": "气阴两虚，兼血瘀",
        "text": "倦怠乏力、舌暗齿痕、脉细涩，辨为气阴两虚、心血瘀阻",
        "linked_fact_ids": ["obs-chest-tightness", "obs-tongue", "obs-pulse"],
        "observed_at": "2026-09-03T09:15:00+08:00",
    }, at="2026-09-03T09:25:00+08:00")
    ids["evt_pattern"] = e["event_id"]

    # 更正也保留来路：补录实验室单位口径
    sys_.correct_observation({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": F_WEST,
        "observation_id": "obs-hba1c", "supersedes_event_id": ids["evt_hba1c"],
        "correction_reason": "原始记录漏标检测方法，补注为高效液相色谱法，数值不变",
        "patch": {"lab_value": {"value": 8.4, "unit": "%", "marker": "HbA1c", "method": "HPLC"}},
    }, at="2026-09-03T10:00:00+08:00")

    # ------------------------------------------------------------ 相互作用 / 冲突 / 候选机制

    sys_.flag_interaction({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": F_WEST,
        "flag_id": "flag-ginkgo-aspirin",
        "substances": ["银杏叶提取物", "阿司匹林"],
        "risk_text": "银杏叶提取物可抑制血小板活化因子，与阿司匹林长期联用增加出血风险",
        "severity": "high",
        "references": [{"type": "drug_interaction_db", "name": "教学用相互作用手册 2025 版"}],
    }, at="2026-09-05T14:00:00+08:00")

    sys_.formulate_problem({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": STUDENT,
        "problem_id": "prob-glycemic", "perspective": "western",
        "formulation": "2型糖尿病血糖控制不达标（HbA1c 8.4%），需评估用药依从性与方案强度",
        "linked_observation_ids": ["obs-hba1c"],
    }, at="2026-09-07T10:00:00+08:00")

    sys_.formulate_problem({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": STUDENT,
        "problem_id": "prob-cardio-risk", "perspective": "western",
        "formulation": "心血管高危人群的抗血小板治疗与出血风险平衡",
        "linked_observation_ids": ["obs-chest-tightness", "obs-platelet"],
    }, at="2026-09-07T10:05:00+08:00")

    sys_.formulate_problem({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": STUDENT,
        "problem_id": "prob-qiyin", "perspective": "tcm",
        "formulation": "气阴两虚：乏力、齿痕舌、脉细",
        "linked_observation_ids": ["obs-pattern-qiyin", "obs-tongue"],
    }, at="2026-09-07T10:10:00+08:00")

    sys_.formulate_problem({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": STUDENT,
        "problem_id": "prob-blood-stasis", "perspective": "tcm",
        "formulation": "心血瘀阻：胸闷、舌暗、脉涩、舌下脉络迂曲",
        "linked_observation_ids": ["obs-pattern-qiyin", "obs-pulse"],
    }, at="2026-09-07T10:15:00+08:00")

    sys_.identify_conflict({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": STUDENT,
        "conflict_id": "conflict-antiplatelet-huoxue",
        "conflict_type": "cross_system",
        "between_refs": ["prob-cardio-risk", "prob-blood-stasis"],
        "description": "西医的抗血小板聚集与中医的活血化瘀是否在指同一机制？若不能等同，联用是协同还是重复抗凝？",
        "status": "open",
    }, at="2026-09-07T10:30:00+08:00")

    sys_.propose_mechanism({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": STUDENT,
        "mechanism_id": "mech-endothelium-correlation",
        "title": "内皮功能异常与气虚血瘀征象共同解释胸闷、舌暗、脉涩（相关性观察）",
        "claim_scope": "correlation",
        "linked_refs": ["prob-cardio-risk", "prob-blood-stasis", "obs-tongue"],
        "citations": [{"type": "cross_sectional_study", "note": "教学文献中的横断面相关性报道"}],
    }, at="2026-09-08T11:00:00+08:00")

    # 试图把相关性包装成疗效：被拦截
    attempt("机制越界为疗效", lambda: sys_.propose_mechanism({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": STUDENT,
        "mechanism_id": "mech-overclaim",
        "title": "声称活血化瘀方已被验证可替代阿司匹林",
        "claim_scope": "validated_outcome",
        "linked_refs": ["prob-blood-stasis"],
        "citations": [{"type": "case_series", "design": "case_series"}],
    }, at="2026-09-08T11:10:00+08:00"))

    # ------------------------------------------------------------ 学生方案第 1 版（拼贴）

    v1_base = {
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": STUDENT,
        "student_id": STUDENT["id"], "plan_id": "plan-2026-017", "revision": 1,
        "decisions": [
            {"decision_id": "d-met", "label": "二甲双胍缓释片", "system": "western", "action": "retained",
             "rationale": "一线降糖，患者既往耐受，继续原剂量", "target_problem_ids": ["prob-glycemic"],
             "evidence_refs": [ids["evt_hba1c"]], "substances": ["盐酸二甲双胍"]},
            {"decision_id": "d-asp", "label": "阿司匹林肠溶片", "system": "western", "action": "retained",
             "rationale": "心血管二级预防带教用药，先维持", "target_problem_ids": ["prob-cardio-risk"],
             "evidence_refs": [ids["evt_chest"]], "substances": ["阿司匹林"]},
            {"decision_id": "d-ginkgo", "label": "银杏叶片", "system": "tcm", "action": "retained",
             "rationale": "患者自购改善循环，先抄录在案", "target_problem_ids": ["prob-blood-stasis"],
             "evidence_refs": [ids["evt_pattern"]], "substances": ["银杏叶提取物"]},
            {"decision_id": "d-danshen-dw", "label": "复方丹参滴丸", "system": "tcm", "action": "retained",
             "rationale": "舌下含服缓解胸闷，家属要求继续", "target_problem_ids": ["prob-blood-stasis"],
             "evidence_refs": [ids["evt_pattern"]], "substances": ["丹参", "三七", "冰片"]},
            {"decision_id": "d-xuefu", "label": "血府逐瘀汤", "system": "tcm", "action": "retained",
             "rationale": "对应血瘀证，原样抄入查房方", "target_problem_ids": ["prob-blood-stasis"],
             "evidence_refs": [ids["evt_pattern"]],
             "substances": ["丹参", "桃仁", "红花", "当归", "川芎", "生地"]},
            {"decision_id": "d-yiqi", "label": "益气养阴方", "system": "tcm", "action": "retained",
             "rationale": "针对气阴两虚", "target_problem_ids": ["prob-qiyin"],
             "evidence_refs": [ids["evt_pattern"]],
             "substances": ["黄芪", "党参", "麦冬", "五味子"]},
            {"decision_id": "d-life", "label": "生活方式干预", "system": "nonpharmacologic", "action": "retained",
             "rationale": "糖尿病饮食与循序渐进的有氧运动", "target_problem_ids": ["prob-glycemic"],
             "evidence_refs": [ids["evt_hba1c"]], "substances": []},
        ],
    }

    # 第一次：重复成分与高危相互作用都未确认 → 被拦
    attempt("v1未确认重复与相互作用", lambda: sys_.submit_plan(v1_base, at="2026-09-10T09:00:00+08:00"))

    # 第二次：只确认重复，相互作用仍未处理 → 再次被拦
    v1_dup_only = {**v1_base, "duplication_acknowledgments": [
        {"substance": "丹参", "decision_a": "d-danshen-dw", "decision_b": "d-xuefu",
         "rationale": "两方均含丹参，已知重复", "resolution": "先并列，下版考虑减量"},
    ]}
    attempt("v1未处理高危相互作用", lambda: sys_.submit_plan(v1_dup_only, at="2026-09-10T09:05:00+08:00"))

    # 第三次：两类风险均显式确认后接受（但结构上仍是拼贴，由指标与教师指出）
    v1 = {**v1_dup_only, "interaction_acknowledgments": [
        {"flag_id": "flag-ginkgo-aspirin",
         "rationale": "已知银杏叶提取物与阿司匹林存在高危联用，患者目前无出血表现",
         "resolution": "暂时维持并在2周后复查凝血与牙龈/皮肤出血征象"},
    ]}
    e = sys_.submit_plan(v1, at="2026-09-10T09:10:00+08:00")
    ids["evt_plan_v1"] = e["event_id"]

    # ------------------------------------------------------------ 教师分歧并存

    e = sys_.record_opinion({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": F_WEST,
        "opinion_id": "op-west-bleeding", "faculty_id": F_WEST["id"], "discipline": "西医内科学",
        "stance": "concern",
        "content": "银杏叶片与阿司匹林高危联用未给出停药路径，仅安排复查偏被动；建议本版即停用银杏叶片。",
        "target": {"kind": "decision", "id": "d-ginkgo"},
    }, at="2026-09-11T15:00:00+08:00")
    ids["evt_op_west"] = e["event_id"]

    e = sys_.record_opinion({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": F_TCM,
        "opinion_id": "op-tcm-ginkgo", "faculty_id": F_TCM["id"], "discipline": "中医经典",
        "stance": "alternative",
        "content": "不赞成简单停用全部活血药：可保留辨证汤剂，把成药与阿司匹林的暴露量重新分配，并监测出血。",
        "target": {"kind": "decision", "id": "d-ginkgo"},
        "relation_to": {"opinion_id": "op-west-bleeding", "relation": "disputes"},
    }, at="2026-09-11T16:30:00+08:00")
    ids["evt_op_tcm"] = e["event_id"]

    sys_.record_opinion({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": F_WEST,
        "opinion_id": "op-west-merge", "faculty_id": F_WEST["id"], "discipline": "西医内科学",
        "stance": "alternative",
        "content": "下一版请把降糖、抗栓两条主线与中医治法对齐到共同问题，而不是继续并列七项治疗。",
        "target": {"kind": "plan_revision", "id": "r1"},
    }, at="2026-09-12T09:00:00+08:00")

    # 西医教师不能覆盖中医教师的意见，只能再发一条并存意见
    attempt("教师覆盖他人意见被拒", lambda: sys_.correct_opinion({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": F_WEST,
        "opinion_id": "op-tcm-ginkgo", "supersedes_event_id": ids["evt_op_tcm"],
        "correction_reason": "不同意，想直接改掉",
        "patch": {"content": "活血药应全部停用"},
    }, at="2026-09-12T10:00:00+08:00"))

    # ------------------------------------------------------------ 第 2 版之前新增事实与第二个高危旗标

    sys_.add_observation({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": STUDENT,
        "observation_id": "obs-ecchymosis", "layer": "fact", "category": "symptom",
        "text": "刷牙时牙龈少量出血2周，前臂可见2处小瘀斑",
        "observed_at": "2026-09-17T08:20:00+08:00",
    }, at="2026-09-17T08:40:00+08:00")

    sys_.flag_interaction({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": F_WEST,
        "flag_id": "flag-danshen-aspirin",
        "substances": ["丹参", "阿司匹林"],
        "risk_text": "丹参成分具抗血小板/抗凝活性，与阿司匹林联用且已有出血倾向时需调整暴露量并监测",
        "severity": "high",
        "references": [{"type": "drug_interaction_db", "name": "教学用相互作用手册 2025 版"},
                       {"type": "case_report", "name": "教学案例库既往出血个案"}],
    }, at="2026-09-17T09:00:00+08:00")

    # ------------------------------------------------------------ 学生方案第 2 版（有取舍的整合）

    v2 = {
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": STUDENT,
        "student_id": STUDENT["id"], "plan_id": "plan-2026-017", "revision": 2,
        "decisions": [
            {"decision_id": "d-glycemic-int", "label": "降糖与益气养阴整合管理",
             "system": "other", "action": "merged",
             "rationale": "高血糖与气阴两虚共同解释乏力与血糖失控：西医控糖达标，中医益气养阴改善症状，"
                          "合并为一条管理决策以便共同评估，而非两套各管各的",
             "target_problem_ids": ["prob-glycemic", "prob-qiyin"],
             "evidence_refs": [ids["evt_hba1c"], ids["evt_pattern"]],
             "substances": ["盐酸二甲双胍", "黄芪", "党参", "麦冬", "五味子"],
             "merged_from": [
                 {"label": "二甲双胍缓释片", "system": "western"},
                 {"label": "益气养阴方", "system": "tcm"},
             ]},
            {"decision_id": "d-antithromb-int", "label": "整合抗栓与活血化瘀方案",
             "system": "other", "action": "merged",
             "rationale": "抗血小板聚集与活血化瘀共同针对胸闷、舌暗、脉涩这一组问题，但不等同机制："
                          "保留阿司匹林做二级预防，以复方丹参滴丸承载活血化瘀，剂量重新分配并监测出血",
             "target_problem_ids": ["prob-cardio-risk", "prob-blood-stasis"],
             "evidence_refs": [ids["evt_chest"], ids["evt_pattern"], ids["evt_op_tcm"]],
             "substances": ["阿司匹林", "丹参", "三七", "冰片"],
             "merged_from": [
                 {"label": "阿司匹林肠溶片", "system": "western"},
                 {"label": "复方丹参滴丸", "system": "tcm"},
             ]},
            {"decision_id": "d-ginkgo-off", "label": "银杏叶片", "system": "tcm", "action": "excluded",
             "rationale": "患者已出现牙龈出血与瘀斑，银杏叶与阿司匹林高危联用且与丹参功效重叠，停用收益大于风险",
             "exclusion_reason": "interaction_risk",
             "target_problem_ids": ["prob-blood-stasis"],
             "evidence_refs": ["flag-ginkgo-aspirin", ids["evt_op_west"], "obs-ecchymosis"],
             "substances": ["银杏叶提取物"]},
            {"decision_id": "d-xuefu-off", "label": "血府逐瘀汤", "system": "tcm", "action": "excluded",
             "rationale": "与复方丹参滴丸在丹参等活血成分上重复，保留滴丸后汤剂不再并行，避免重复暴露",
             "exclusion_reason": "duplication",
             "target_problem_ids": ["prob-blood-stasis"],
             "evidence_refs": ["obs-ecchymosis"],
             "substances": ["丹参", "桃仁", "红花"]},
            {"decision_id": "d-life-2", "label": "生活方式干预", "system": "nonpharmacologic", "action": "retained",
             "rationale": "继续糖尿病饮食与运动教育，作为两条整合主线的共同基础",
             "target_problem_ids": ["prob-glycemic", "prob-qiyin"],
             "evidence_refs": [ids["evt_hba1c"]], "substances": []},
        ],
        "interaction_acknowledgments": [
            {"flag_id": "flag-danshen-aspirin",
             "rationale": "合并方案仍同时含阿司匹林与丹参，且已有轻度出血倾向",
             "resolution": "阿司匹林减量至 50mg/日，复方丹参滴丸改为每日2次，每2周复查出血征象与PLT"},
        ],
    }
    e = sys_.submit_plan(v2, at="2026-09-18T09:30:00+08:00")
    ids["evt_plan_v2"] = e["event_id"]

    # 同体系伪合并被拦
    attempt("同体系伪合并被拒", lambda: sys_.submit_plan({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": STUDENT,
        "student_id": STUDENT["id"], "plan_id": "plan-bad-merge", "revision": 1,
        "decisions": [{
            "decision_id": "x1", "label": "两种西药伪合并", "system": "western", "action": "merged",
            "rationale": "想把同体系两药记成合并", "target_problem_ids": ["prob-glycemic"],
            "evidence_refs": [ids["evt_hba1c"]], "substances": ["A", "B"],
            "merged_from": [{"label": "药甲", "system": "western"}, {"label": "药乙", "system": "western"}],
        }],
    }, at="2026-09-18T10:00:00+08:00"))

    # ------------------------------------------------------------ 模拟 / 回顾 / 能力评价

    sys_.record_simulation({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": F_WEST,
        "simulation_id": "sim-v2-bleeding", "linked_revision": 2,
        "tool": "教学版药物相互作用与出血风险模拟器 v3",
        "scenario": "阿司匹林50mg + 复方丹参滴丸每日2次，PLT 198，随访4周",
        "outputs": {"predicted_minor_bleeding_probability_4w": 0.11, "flag": "低于v1方案的0.23"},
        "limitations": "基于教学参数的模拟，不代表该患者真实结局，不能作为疗效证据",
    }, at="2026-09-19T11:00:00+08:00")

    sys_.record_case_review({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": F_WEST,
        "review_id": "review-followup-4w",
        "follow_up_at": "2026-10-16T09:00:00+08:00",
        "actual_findings": "4周后未再新发瘀斑，牙龈出血消失，HbA1c 复查 7.8%；为单病例随访所见",
        "claim_scope": "individual_followup",
    }, at="2026-10-17T10:00:00+08:00")

    # 单病例回顾想声明 validated_outcome → 被拦
    attempt("个案随访越界为疗效", lambda: sys_.record_case_review({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": F_WEST,
        "review_id": "review-overclaim",
        "follow_up_at": "2026-10-16T09:00:00+08:00",
        "actual_findings": "症状好转即声称方案被验证有效",
        "claim_scope": "validated_outcome",
    }, at="2026-10-17T10:10:00+08:00"))

    sys_.evaluate_competency({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": F_WEST,
        "evaluation_id": "comp-2026-017-r2", "student_id": STUDENT["id"], "plan_revision": 2,
        "dimensions": {
            "事实与证候分层": {"score": 88, "evidence_refs": [ids["evt_pattern"], "obs-ecchymosis"]},
            "共同问题解释": {"score": 82, "evidence_refs": [ids["evt_plan_v2"], "mech-endothelium-correlation"]},
            "治疗取舍依据": {"score": 90, "evidence_refs": [ids["evt_plan_v2"], ids["evt_op_west"]]},
            "证据边界自觉": {"score": 85, "evidence_refs": [ids["evt_plan_v2"], "sim-v2-bleeding"]},
        },
    }, at="2026-09-25T14:00:00+08:00")

    # ------------------------------------------------------------ 授权到期

    sys_.expire_access({
        "case_id": CASE_ID, "actor": SYSTEM,
        "reason": "consent_expired", "effective_at": "2027-02-01T00:00:00+08:00",
        "retention": {"grade_evidence": "retain_anonymized",
                      "rule_reference": "医学院教学档案管理细则第12条：授权到期后停止教学访问，形成性成绩证据匿名保留3年"},
    }, at="2027-02-01T00:00:00+08:00")

    attempt("到期后新增观察被拒", lambda: sys_.add_observation({
        "case_id": CASE_ID, "course_id": COURSE_A, "actor": STUDENT,
        "observation_id": "obs-after-expiry", "layer": "fact", "category": "symptom",
        "text": "授权到期后试图补录的症状",
        "observed_at": "2027-03-01T08:00:00+08:00",
    }, at="2027-03-01T08:00:00+08:00"))

    return {"system": sys_, "ids": ids, "rejected": rejected}
