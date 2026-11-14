"""操作日志写入。

REQ-014 要求订单、支付、退款与关键操作都留痕，且按角色的数据范围做查询过滤。
日志归属的门店由对象本身推出（订单看 store_id，房间看所属房型），
这样「系统」发起的日志也能被对应门店的管理者看到。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from hotel.core.ids import new_id

_STORE_LOOKUPS = {
    "order": "SELECT store_id FROM orders WHERE id = ?",
    "room": (
        "SELECT t.store_id FROM room r JOIN room_type t ON t.id = r.room_type_id" " WHERE r.id = ?"
    ),
    "work_order": (
        "SELECT t.store_id FROM work_order w JOIN room r ON r.id = w.room_id"
        " JOIN room_type t ON t.id = r.room_type_id WHERE w.id = ?"
    ),
}


def _resolve_store(conn: sqlite3.Connection, object_type: str, object_id: str) -> str | None:
    sql = _STORE_LOOKUPS.get(object_type)
    if sql is None:
        return None
    row = conn.execute(sql, (object_id,)).fetchone()
    return row["store_id"] if row else None


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
    store_id: str | None = None,
) -> None:
    if store_id is None:
        store_id = _resolve_store(conn, object_type, object_id)
    conn.execute(
        "INSERT INTO audit_log"
        " (id, operator_id, operator_role, action, object_type, object_id,"
        "  before_value, after_value, reason, source, store_id, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            store_id,
            (moment or datetime.now()).isoformat(),
        ),
    )
