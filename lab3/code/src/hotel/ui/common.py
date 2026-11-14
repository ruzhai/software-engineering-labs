"""界面公用：错误兜底与日期解析。"""

from __future__ import annotations

from datetime import date
from functools import wraps
from tkinter import messagebox

from hotel.core.errors import AppError, ValidationError


def parse_date(text: str, field: str) -> date:
    try:
        return date.fromisoformat(text.strip())
    except ValueError as exc:
        raise ValidationError("日期格式应为 YYYY-MM-DD", field=field) from exc


def guarded(func):
    """把业务异常转成提示框，绝不让异常冒到 Tk 主循环。"""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except AppError as exc:
            messagebox.showwarning("操作未完成", exc.message)
            return None
        except Exception as exc:  # pylint: disable=broad-exception-caught
            messagebox.showerror("出错了", str(exc))
            return None

    return wrapper
