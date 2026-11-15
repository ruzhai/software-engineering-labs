"""支付与退款的 SQLite 读写。"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from hotel.m06_payment.model import (
    Payment,
    PaymentStatus,
    ReconciliationRecord,
    ReconciliationStatus,
    Refund,
    RefundStatus,
)


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class PaymentRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def insert_payment(self, payment: Payment) -> None:
        self.conn.execute(
            "INSERT INTO payment"
            " (id, pay_no, order_id, amount_cents, channel, txn_id, status, paid_at, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                payment.id,
                payment.pay_no,
                payment.order_id,
                payment.amount_cents,
                payment.channel,
                payment.txn_id,
                payment.status.value,
                payment.paid_at.isoformat() if payment.paid_at else None,
                payment.created_at.isoformat(),
            ),
        )

    def get_by_pay_no(self, pay_no: str) -> Payment | None:
        row = self.conn.execute("SELECT * FROM payment WHERE pay_no = ?", (pay_no,)).fetchone()
        return self._to_payment(row) if row else None

    def get_by_id(self, payment_id: str) -> Payment | None:
        row = self.conn.execute("SELECT * FROM payment WHERE id = ?", (payment_id,)).fetchone()
        return self._to_payment(row) if row else None

    def mark_success(self, payment_id: str, txn_id: str, paid_at: datetime) -> None:
        self.conn.execute(
            "UPDATE payment SET status = ?, txn_id = ?, paid_at = ? WHERE id = ?",
            (PaymentStatus.SUCCESS.value, txn_id, paid_at.isoformat(), payment_id),
        )

    def has_active_payment(self, order_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM payment WHERE order_id = ? AND status IN ('PENDING', 'SUCCESS')"
            " LIMIT 1",
            (order_id,),
        ).fetchone()
        return row is not None

    def count_successful(self, order_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM payment WHERE order_id = ? AND status = 'SUCCESS'",
            (order_id,),
        ).fetchone()
        return int(row["n"])

    def successful_payment_of_order(self, order_id: str) -> Payment | None:
        row = self.conn.execute(
            "SELECT * FROM payment WHERE order_id = ? AND status = 'SUCCESS'"
            " ORDER BY created_at LIMIT 1",
            (order_id,),
        ).fetchone()
        return self._to_payment(row) if row else None

    def insert_refund(self, refund: Refund) -> None:
        self.conn.execute(
            "INSERT INTO refund"
            " (id, refund_no, order_id, payment_id, amount_cents, reason, status, refunded_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                refund.id,
                refund.refund_no,
                refund.order_id,
                refund.payment_id,
                refund.amount_cents,
                refund.reason,
                refund.status.value,
                refund.refunded_at.isoformat() if refund.refunded_at else None,
            ),
        )

    def sum_refunded(self, order_id: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) AS n FROM refund"
            " WHERE order_id = ? AND status = 'SUCCESS'",
            (order_id,),
        ).fetchone()
        return int(row["n"])

    def refund_of_order(self, order_id: str) -> Refund | None:
        row = self.conn.execute(
            "SELECT * FROM refund WHERE order_id = ? LIMIT 1", (order_id,)
        ).fetchone()
        if row is None:
            return None
        return Refund(
            id=row["id"],
            refund_no=row["refund_no"],
            order_id=row["order_id"],
            payment_id=row["payment_id"],
            amount_cents=row["amount_cents"],
            reason=row["reason"],
            status=RefundStatus(row["status"]),
            refunded_at=_parse_dt(row["refunded_at"]),
        )

    def insert_reconciliation(self, record: ReconciliationRecord) -> None:
        self.conn.execute(
            "INSERT INTO reconciliation"
            " (id, payment_id, rec_date, diff_type, diff_cents, resolution, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record.id,
                record.payment_id,
                record.rec_date.isoformat(),
                record.diff_type,
                record.diff_cents,
                record.resolution,
                record.status.value,
            ),
        )

    def list_reconciliation(self, on_date: date) -> list[ReconciliationRecord]:
        rows = self.conn.execute(
            "SELECT * FROM reconciliation WHERE rec_date = ? ORDER BY id",
            (on_date.isoformat(),),
        ).fetchall()
        return [
            ReconciliationRecord(
                id=row["id"],
                payment_id=row["payment_id"],
                rec_date=date.fromisoformat(row["rec_date"]),
                diff_type=row["diff_type"],
                diff_cents=row["diff_cents"],
                resolution=row["resolution"],
                status=ReconciliationStatus(row["status"]),
            )
            for row in rows
        ]

    @staticmethod
    def _to_payment(row: sqlite3.Row) -> Payment:
        return Payment(
            id=row["id"],
            pay_no=row["pay_no"],
            order_id=row["order_id"],
            amount_cents=row["amount_cents"],
            channel=row["channel"],
            txn_id=row["txn_id"],
            status=PaymentStatus(row["status"]),
            paid_at=_parse_dt(row["paid_at"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
