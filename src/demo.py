"""命令行走查：python3 -m src.demo

打印分层事件、两次方案修订并排视图、跨课程同步与到期后成绩证据保留。
"""

from __future__ import annotations

from .revision import build_revision_view, render_revision_markdown
from .scenario import (
    CASE_ID, COURSE_A, COURSE_B, COURSE_OUTSIDE, build_scenario,
)
from .sync import CourseBus
from .system import TeachingCaseSystem


def main() -> None:
    scenario = build_scenario()
    sys_ = scenario["system"]

    print("=" * 78)
    print("一、被守卫拦下的操作（系统不替师生裁判，只要求依据与证据边界）")
    print("=" * 78)
    for label, msg in scenario["rejected"].items():
        print(f"· [{label}] {msg}")

    print()
    print("=" * 78)
    print("二、分层事件流（四层聚合，版本连续）")
    print("=" * 78)
    for e in sys_.store.all_events():
        print(f"v{e['version']:>2} {e['aggregate_type']:<22} {e['event_type']:<24} {e['summary']}")

    case = sys_.projection.case(CASE_ID)
    for revision in (1, 2):
        view = build_revision_view(case, "plan-2026-017", revision)
        print()
        print(render_revision_markdown(view))

    print()
    print("=" * 78)
    print("三、跨课程同步（teaching_case / clinical_observation / student_plan / faculty_feedback）")
    print("=" * 78)
    course_a = TeachingCaseSystem()
    course_b = TeachingCaseSystem()
    course_out = TeachingCaseSystem()
    bus = CourseBus()
    bus.register(COURSE_A, course_a)
    bus.register(COURSE_B, course_b)
    bus.register(COURSE_OUTSIDE, course_out)

    counts = bus.publish(sys_)
    print(f"同步投递计数：{counts}")
    print(f"同意范围外课程（{COURSE_OUTSIDE}）收到的病例事件："
          f"{len(course_out.store.all_events())} 条（期望 0）")

    cp_b = course_b.projection.case(CASE_ID)
    ok_b, reason_b = cp_b.access_status(COURSE_B, "2026-12-01T00:00:00+08:00")
    print(f"课程 B 在授权期内访问：{ok_b}（{reason_b}）")
    grade_in_b = [e for e in course_b.store.all_events() if e["event_type"] == "COMPETENCY_EVALUATED"]
    print(f"课程 B 收到的成绩证据事件：{len(grade_in_b)} 条（默认不外发，期望 0）")
    obs_b = [e for e in course_b.store.all_events() if e["event_type"] == "OBSERVATION_ADDED"]
    plans_b = [e for e in course_b.store.all_events() if e["event_type"] == "PLAN_SUBMITTED"]
    print(f"课程 B 收到观察事件 {len(obs_b)} 条、学生方案事件 {len(plans_b)} 条（扇出给授权课程）")

    # 重复同步幂等
    again = bus.publish(sys_)
    print(f"再次同步投递计数：{again}（期望 {{}} 或仅 duplicate 日志）")

    print()
    print("=" * 78)
    print("四、授权到期：停止新课程访问，成绩证据按规则匿名保留")
    print("=" * 78)
    for course, course_id, name in (
        (course_a, COURSE_A, "课程A"),
        (course_b, COURSE_B, "课程B"),
    ):
        cp = course.projection.case(CASE_ID)
        ok, reason = cp.access_status(course_id, "2027-03-01T00:00:00+08:00")
        print(f"{name} 到期后访问：{ok}（{reason}）")
    evidence = sys_.projection.case(CASE_ID).grade_evidence()
    print(f"中心日志保留的成绩证据 {len(evidence)} 条（retain_anonymized）：")
    for item in evidence:
        print(f"· 评价 {item['evaluation_id']} → 匿名标识 {item.get('student_pseudonym')}，"
              f"维度 {sorted(item['dimensions'])}，来源事件 {item['event_id']}")


if __name__ == "__main__":
    main()
