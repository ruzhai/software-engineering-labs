"""操作日志写入。

REQ-014 要求订单、支付、退款与关键操作都留痕。各模块在自己的事务里调用本函数，
保证业务成功与日志写入要么都成功、要么都不发生。M9 负责查询与保留策略。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from hotel.core.ids import new_id


def record_audit(
    conn: sqlite3.Connection,
    *,
    operator_id: str,
    operator_role: str,
    action: str,
    object_type: str,
    object_id: str,
    reason: str = "",
    before_value: str | None = None,
    after_value: str | None = None,
    source: str = "SERVICE",
    moment: datetime | None = None,
) -> None:
    conn.execute(
        "INSERT INTO audit_log"
        " (id, operator_id, operator_role, action, object_type, object_id,"
        "  before_value, after_value, reason, source, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            new_id("log"),
            operator_id,
            operator_role,
            action,
            object_type,
            object_id,
            before_value,
            after_value,
            reason,
            source,
            (moment or datetime.now()).isoformat(),
        ),
    )
