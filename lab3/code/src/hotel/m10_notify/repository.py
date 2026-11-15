"""通知记录的 SQLite 读写。"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from hotel.m10_notify.model import Channel, Notification, NotificationStatus


def _to_notification(row: sqlite3.Row) -> Notification:
    return Notification(
        id=row["id"],
        order_id=row["order_id"],
        type=row["type"],
        channel=Channel(row["channel"]),
        status=NotificationStatus(row["status"]),
        failure_reason=row["failure_reason"],
        retry_count=row["retry_count"],
        sent_at=datetime.fromisoformat(row["sent_at"]) if row["sent_at"] else None,
        payload=row["payload"],
    )


class NotificationRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def of_order_and_type(self, order_id: str, event_type: str) -> Notification | None:
        row = self.conn.execute(
            "SELECT * FROM notification WHERE order_id = ? AND type = ? LIMIT 1",
            (order_id, event_type),
        ).fetchone()
        return _to_notification(row) if row else None

    def insert(self, notification: Notification) -> None:
        self.conn.execute(
            "INSERT INTO notification"
            " (id, order_id, type, channel, status, failure_reason, retry_count,"
            "  sent_at, payload)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                notification.id,
                notification.order_id,
                notification.type,
                notification.channel.value,
                notification.status.value,
                notification.failure_reason,
                notification.retry_count,
                notification.sent_at.isoformat() if notification.sent_at else None,
                notification.payload,
            ),
        )

    def update_result(
        self,
        notification_id: str,
        status: NotificationStatus,
        failure_reason: str | None,
        retry_count: int,
        sent_at: datetime | None,
    ) -> None:
        self.conn.execute(
            "UPDATE notification SET status = ?, failure_reason = ?, retry_count = ?,"
            " sent_at = ? WHERE id = ?",
            (
                status.value,
                failure_reason,
                retry_count,
                sent_at.isoformat() if sent_at else None,
                notification_id,
            ),
        )

    def list_failed(self, max_retries: int) -> list[Notification]:
        rows = self.conn.execute(
            "SELECT * FROM notification WHERE status = 'FAILED' AND retry_count < ?",
            (max_retries,),
        ).fetchall()
        return [_to_notification(row) for row in rows]

    def list_by_store(self, store_id: str) -> list[Notification]:
        rows = self.conn.execute(
            "SELECT n.* FROM notification n JOIN orders o ON o.id = n.order_id"
            " WHERE o.store_id = ? ORDER BY n.id DESC LIMIT 200",
            (store_id,),
        ).fetchall()
        return [_to_notification(row) for row in rows]

    def list_by_order(self, order_id: str) -> list[Notification]:
        rows = self.conn.execute(
            "SELECT * FROM notification WHERE order_id = ? ORDER BY id", (order_id,)
        ).fetchall()
        return [_to_notification(row) for row in rows]
