"""领域错误：错误信息可直接展示给师生或接入系统。"""


class DomainError(Exception):
    """所有领域规则违反的基类。"""


class ValidationError(DomainError):
    """事件或命令未通过结构化校验。"""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("；".join(errors))


class ConcurrencyError(DomainError):
    """聚合版本冲突或事件标识被不一致地重试。"""


class AuthorizationError(DomainError):
    """课程在授权范围外访问病例，或角色无权写入该层。"""
