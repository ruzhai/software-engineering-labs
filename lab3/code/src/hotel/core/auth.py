"""会话有效性校验。

Session 是登录那一刻的快照，账号被停用后它本身不会失效。REQ-001 要求
「账号停用后立即失去权限」，所以服务层在拿到连接后再查一次账号状态，
而不是信任快照。
"""

from __future__ import annotations

import sqlite3

from hotel.core.errors import PermissionDenied

ACTIVE = "ACTIVE"


def ensure_active(conn: sqlite3.Connection, session) -> None:
    row = conn.execute("SELECT status FROM user WHERE id = ?", (session.user_id,)).fetchone()
    if row is None or row["status"] != ACTIVE:
        raise PermissionDenied("账号已停用")
