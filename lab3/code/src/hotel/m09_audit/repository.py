"""审计日志与删除申请的 SQLite 读写。"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from hotel.m09_audit.model import AuditEntry, DeletionRequest, DeletionStatus

# 删除订单时要连带清掉的子表，顺序按外键依赖从叶子到根。
ORDER_DELETE_STEPS = (
    ("reconciliation", "payment_id IN (SELECT id FROM payment WHERE order_id = ?)"),
    ("refund", "order_id = ?"),
    ("payment", "order_id = ?"),
    ("order_item", "order_id = ?"),
    ("occupancy", "order_id = ?"),
    ("review", "order_id = ?"),
    ("notification", "order_id = ?"),
    ("cancel_request", "order_id = ?"),
    ("upgrade_request", "order_id = ?"),
)


class AuditRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list_entries(
        self, scope_sql: str, params: tuple, action: str | None, limit: int
    ) -> list[AuditEntry]:
        sql = f"SELECT * FROM audit_log WHERE {scope_sql}"
        query_params = list(params)
        if action:
            sql += " AND action = ?"
            query_params.append(action)
        sql += " ORDER BY created_at DESC LIMIT ?"
        query_params.append(limit)
        rows = self.conn.execute(sql, tuple(query_params)).fetchall()
        return [
            AuditEntry(
                id=row["id"],
                operator_id=row["operator_id"],
                operator_role=row["operator_role"],
                action=row["action"],
                object_type=row["object_type"],
                object_id=row["object_id"],
                before_value=row["before_value"],
                after_value=row["after_value"],
                reason=row["reason"],
                source=row["source"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def insert_deletion_request(self, request: DeletionRequest) -> None:
        self.conn.execute(
            "INSERT INTO deletion_request"
            " (id, area_id, object_type, object_id, reason, applicant, approver, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                request.id,
                request.area_id,
                request.object_type,
                request.object_id,
                request.reason,
                request.applicant,
                request.approver,
                request.status.value,
            ),
        )

    def get_deletion_request(self, request_id: str) -> DeletionRequest | None:
        row = self.conn.execute(
            "SELECT * FROM deletion_request WHERE id = ?", (request_id,)
        ).fetchone()
        if row is None:
            return None
        return DeletionRequest(
            id=row["id"],
            area_id=row["area_id"],
            object_type=row["object_type"],
            object_id=row["object_id"],
            reason=row["reason"],
            applicant=row["applicant"],
            approver=row["approver"],
            status=DeletionStatus(row["status"]),
        )

    def set_deletion_status(self, request_id: str, status: DeletionStatus, approver: str) -> None:
        self.conn.execute(
            "UPDATE deletion_request SET status = ?, approver = ? WHERE id = ?",
            (status.value, approver, request_id),
        )

    def list_deletion_requests(self, area_id: str) -> list[DeletionRequest]:
        rows = self.conn.execute(
            "SELECT id FROM deletion_request WHERE area_id = ? ORDER BY id", (area_id,)
        ).fetchall()
        return [
            request for row in rows if (request := self.get_deletion_request(row["id"])) is not None
        ]

    def delete_order(self, order_id: str) -> None:
        for table, condition in ORDER_DELETE_STEPS:
            self.conn.execute(f"DELETE FROM {table} WHERE {condition}", (order_id,))
        self.conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))

    def count_older_than(self, table: str, column: str, cutoff_iso: str) -> int:
        row = self.conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE {column} < ?", (cutoff_iso,)
        ).fetchone()
        return int(row["n"])
