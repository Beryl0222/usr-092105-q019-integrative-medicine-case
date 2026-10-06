"""课程间事件同步。

规则
----
1. 按四类聚合通道同步：teaching_case / clinical_observation / student_plan / faculty_feedback。
2. 病例事件（CASE_RELEASED）携带授权课程清单；只投递给在同意范围内的课程。
3. 授权终止（ACCESS_EXPIRED / CONSENT_WITHDRAWN）作为墓碑（tombstone）优先投递：
   接收课程收到后立即停止新课程访问；已同步事件不物理删除（事件不可变），
   由各课程自己的读模型按授权状态遮蔽。
4. 成绩证据（COMPETENCY_EVALUATED）默认不外发：成绩按保留规则归属于开课课程，
   除非目标课程在病例授权课程清单内且发送方显式允许。
5. 投递幂等：同一 event_id 重复投递无副作用；事件内容不一致则拒绝。
"""

from __future__ import annotations

from typing import Any

from .errors import AuthorizationError, DomainError
from .events import EVENT_AGGREGATE, parse_dt, validate_event
from .system import TeachingCaseSystem

GRADE_EVIDENCE_EVENT = "COMPETENCY_EVALUATED"
TOMBSTONE_EVENTS = frozenset({"ACCESS_EXPIRED", "CONSENT_WITHDRAWN"})
CASE_LIFECYCLE_EVENTS = frozenset({"CASE_RELEASED"}) | TOMBSTONE_EVENTS


class CourseBus:
    """以内存中的各课程系统模拟课程间总线；真实部署可替换为消息总线实现。"""

    def __init__(self) -> None:
        self._systems: dict[str, TeachingCaseSystem] = {}
        self.delivery_log: list[dict[str, Any]] = []

    def register(self, course_id: str, system: TeachingCaseSystem) -> None:
        self._systems[course_id] = system

    def courses(self) -> list[str]:
        return sorted(self._systems)

    # ------------------------------------------------------------ 投递判定

    def route_for(self, event: dict[str, Any], source: TeachingCaseSystem,
                  *, allow_grade_export: bool = False) -> list[str]:
        """决定一条事件应投递给哪些已注册课程。

        - 病例生命周期：发布投同意范围内课程；墓碑（撤回/到期）广播全部持有方；
        - 成绩证据：只回开课课程（默认不外发）；
        - 其余三层（观察/方案/意见）：扇出到病例授权课程清单内的全部已注册课程。
        """
        p = event.get("payload") or {}
        etype = event["event_type"]

        if etype in CASE_LIFECYCLE_EVENTS:
            if etype == "CASE_RELEASED":
                return [c for c in p.get("courses", []) if c in self._systems]
            # 墓碑只广播给已持有该病例副本的课程，避免在无关课程凭空制造到期事件
            case_id = event["aggregate_id"]
            return [
                c for c, sys_ in self._systems.items()
                if sys_.projection.case(case_id).release is not None
            ]

        target_course = p.get("course_id")
        case_id = p.get("case_id")
        authorized = set(source.projection.case(case_id).courses) if case_id else set()
        recipients = [c for c in self._systems if c in authorized]
        if etype == GRADE_EVIDENCE_EVENT:
            if not allow_grade_export:
                return [target_course] if target_course in self._systems else []
        return recipients

    # ------------------------------------------------------------ 同步

    def publish(self, system: TeachingCaseSystem, *, since_index: int = 0,
                allow_grade_export: bool = False) -> dict[str, int]:
        """把源系统（教学案中心日志）的事件按层同步到路由命中的课程系统。

        墓碑事件优先；其余按全局限序。返回各课程投递计数。
        """
        events = system.store.all_events()[since_index:]
        releases = [e for e in events if e["event_type"] == "CASE_RELEASED"]
        tombstones = [e for e in events if e["event_type"] in TOMBSTONE_EVENTS]
        ordinary = [
            e for e in events
            if e["event_type"] not in TOMBSTONE_EVENTS and e["event_type"] != "CASE_RELEASED"
        ]
        counts: dict[str, int] = {}

        # 顺序：发布 → 墓碑（到期/撤回优先于业务事件生效）→ 其余按日志顺序
        for event in releases + tombstones + ordinary:
            errors = validate_event(event)
            if errors:
                raise DomainError(f"事件 {event.get('event_id')} 未通过契约校验，拒绝同步：{errors}")
            for course_id in self.route_for(event, system, allow_grade_export=allow_grade_export):
                target = self._systems[course_id]
                status = self._deliver_one(target, course_id, event)
                if status == "delivered":
                    counts[course_id] = counts.get(course_id, 0) + 1
        return counts

    def _deliver_one(self, target: TeachingCaseSystem, course_id: str, event: dict[str, Any]) -> str:
        """返回 delivered / duplicate。"""
        etype = event["event_type"]
        p = event.get("payload") or {}
        case_id = p.get("case_id") or event["aggregate_id"]

        # 接收侧：墓碑必须接受（即使按访问状态已不能写），其余事件须仍在授权期
        if etype not in CASE_LIFECYCLE_EVENTS:
            cp = target.projection.case(case_id)
            if cp.release is None:
                raise AuthorizationError(
                    f"课程 {course_id} 尚未收到病例发布事件，拒绝孤立同步 {event['event_id']}"
                )
            ok, reason = cp.access_status(course_id, event["occurred_at"])
            if not ok:
                raise AuthorizationError(f"课程 {course_id} 拒绝事件 {event['event_id']}：{reason}")

        if target.store.exists(event["event_id"]):
            existing = target.store.get(event["event_id"])
            if existing != event:
                raise DomainError(
                    f"课程 {course_id} 已存在同标识不同内容的事件 {event['event_id']}，同步中止"
                )
            self.delivery_log.append({"course_id": course_id, "event_id": event["event_id"], "status": "duplicate"})
            return "duplicate"

        target.ingest(event)
        self.delivery_log.append({"course_id": course_id, "event_id": event["event_id"], "status": "delivered"})
        return "delivered"

    # ------------------------------------------------------------ 查询

    def delivery_status(self, event_id: str) -> list[dict[str, Any]]:
        return [d for d in self.delivery_log if d["event_id"] == event_id]
