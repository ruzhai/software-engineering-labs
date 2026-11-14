"""统一的业务错误类型。

界面层只捕获 AppError，把 message 就地显示在 field 对应的输入框旁边，
不把异常栈暴露给用户（对应 REQ-027 的「指出具体字段与原因」）。
"""

from __future__ import annotations


class AppError(Exception):
    """所有可预期业务错误的基类。"""

    def __init__(self, message: str, field: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.field = field


class ValidationError(AppError):
    """输入校验失败。"""


class PermissionDenied(AppError):
    """角色或数据范围不匹配。"""


class NotFound(AppError):
    """对象不存在。"""


class ConflictError(AppError):
    """状态机不允许的转换，或并发冲突。"""
