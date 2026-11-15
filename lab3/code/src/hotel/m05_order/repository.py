"""订单的 SQLite 读写。"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime

from hotel.m05_order.model import (
    CancelRequest,
    CancelRequestStatus,
    ModifyRequest,
    ModifyRequestStatus,
    Order,
    OrderItem,
    OrderStatus,
)


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class OrderRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def request_seen(self, request_no: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM request_ledger WHERE request_no = ?", (request_no,)
        ).fetchone()
        return row is not None

    def record_request(self, request_no: str, created_at: datetime) -> None:
        self.conn.execute(
            "INSERT INTO request_ledger (request_no, created_at) VALUES (?, ?)",
            (request_no, created_at.isoformat()),
        )

    def find_order_by_request_no(self, request_no: str) -> Order | None:
        row = self.conn.execute(
            "SELECT id FROM orders WHERE request_no = ?", (request_no,)
        ).fetchone()
        return self.get_order(row["id"]) if row else None

    def insert_order(self, order: Order) -> None:
        self.conn.execute(
            "INSERT INTO orders (id, order_no, request_no, customer_id, store_id, status,"
            " total_cents, pay_deadline, check_in_date, check_out_date, room_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                order.id,
                order.order_no,
                order.request_no,
                order.customer_id,
                order.store_id,
                order.status.value,
                order.total_cents,
                order.pay_deadline.isoformat(),
                order.check_in_date.isoformat(),
                order.check_out_date.isoformat(),
                order.room_id,
                order.created_at.isoformat(),
            ),
        )

    def insert_item(self, item: OrderItem) -> None:
        self.conn.execute(
            "INSERT INTO order_item"
            " (id, order_id, room_type_id, stay_date, qty, unit_price_cents, subtotal_cents)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                item.id,
                item.order_id,
                item.room_type_id,
                item.stay_date.isoformat(),
                item.qty,
                item.unit_price_cents,
                item.subtotal_cents,
            ),
        )

    def delete_items(self, order_id: str) -> None:
        self.conn.execute("DELETE FROM order_item WHERE order_id = ?", (order_id,))

    def get_order(self, order_id: str) -> Order | None:
        row = self.conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            return None
        order = Order(
            id=row["id"],
            order_no=row["order_no"],
            request_no=row["request_no"],
            customer_id=row["customer_id"],
            store_id=row["store_id"],
            status=OrderStatus(row["status"]),
            total_cents=row["total_cents"],
            pay_deadline=datetime.fromisoformat(row["pay_deadline"]),
            check_in_date=date.fromisoformat(row["check_in_date"]),
            check_out_date=date.fromisoformat(row["check_out_date"]),
            room_id=row["room_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            checked_in_at=_parse_dt(row["checked_in_at"]),
            checked_out_at=_parse_dt(row["checked_out_at"]),
        )
        order.items = self.get_items(order_id)
        return order

    def get_items(self, order_id: str) -> list[OrderItem]:
        rows = self.conn.execute(
            "SELECT * FROM order_item WHERE order_id = ? ORDER BY stay_date, room_type_id",
            (order_id,),
        ).fetchall()
        return [
            OrderItem(
                id=row["id"],
                order_id=row["order_id"],
                room_type_id=row["room_type_id"],
                stay_date=date.fromisoformat(row["stay_date"]),
                qty=row["qty"],
                unit_price_cents=row["unit_price_cents"],
                subtotal_cents=row["subtotal_cents"],
            )
            for row in rows
        ]

    def update_status(
        self,
        order_id: str,
        status: OrderStatus,
        *,
        checked_in_at: datetime | None = None,
        checked_out_at: datetime | None = None,
    ) -> None:
        self.conn.execute(
            "UPDATE orders SET status = ?,"
            " checked_in_at = COALESCE(?, checked_in_at),"
            " checked_out_at = COALESCE(?, checked_out_at)"
            " WHERE id = ?",
            (
                status.value,
                checked_in_at.isoformat() if checked_in_at else None,
                checked_out_at.isoformat() if checked_out_at else None,
                order_id,
            ),
        )

    def set_dates(self, order_id: str, check_in: date, check_out: date) -> None:
        self.conn.execute(
            "UPDATE orders SET check_in_date = ?, check_out_date = ? WHERE id = ?",
            (check_in.isoformat(), check_out.isoformat(), order_id),
        )

    def set_total(self, order_id: str, total_cents: int) -> None:
        self.conn.execute("UPDATE orders SET total_cents = ? WHERE id = ?", (total_cents, order_id))

    def set_room(self, order_id: str, room_id: str | None) -> None:
        self.conn.execute("UPDATE orders SET room_id = ? WHERE id = ?", (room_id, order_id))

    def list_by_customer(self, customer_id: str) -> list[Order]:
        rows = self.conn.execute(
            "SELECT id FROM orders WHERE customer_id = ? ORDER BY created_at DESC",
            (customer_id,),
        ).fetchall()
        return [order for row in rows if (order := self.get_order(row["id"]))]

    def list_by_store(self, store_id: str) -> list[Order]:
        rows = self.conn.execute(
            "SELECT id FROM orders WHERE store_id = ? ORDER BY created_at DESC", (store_id,)
        ).fetchall()
        return [order for row in rows if (order := self.get_order(row["id"]))]

    def insert_cancel_request(self, request: CancelRequest) -> None:
        self.conn.execute(
            "INSERT INTO cancel_request"
            " (id, order_id, reason, applicant, approver, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                request.id,
                request.order_id,
                request.reason,
                request.applicant,
                request.approver,
                request.status.value,
                request.created_at.isoformat(),
            ),
        )

    def get_cancel_request(self, request_id: str) -> CancelRequest | None:
        row = self.conn.execute(
            "SELECT * FROM cancel_request WHERE id = ?", (request_id,)
        ).fetchone()
        if row is None:
            return None
        return CancelRequest(
            id=row["id"],
            order_id=row["order_id"],
            reason=row["reason"],
            applicant=row["applicant"],
            approver=row["approver"],
            status=CancelRequestStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def pending_cancel_request(self, order_id: str) -> CancelRequest | None:
        row = self.conn.execute(
            "SELECT id FROM cancel_request WHERE order_id = ? AND status = 'PENDING'",
            (order_id,),
        ).fetchone()
        return self.get_cancel_request(row["id"]) if row else None

    def set_cancel_request_status(
        self, request_id: str, status: CancelRequestStatus, approver: str
    ) -> None:
        self.conn.execute(
            "UPDATE cancel_request SET status = ?, approver = ? WHERE id = ?",
            (status.value, approver, request_id),
        )

    # ---------- 改期申请 ----------

    def insert_modify_request(self, request: ModifyRequest) -> None:
        self.conn.execute(
            "INSERT INTO modify_request"
            " (id, order_id, items_json, check_in_date, check_out_date,"
            "  old_total_cents, new_total_cents, applicant, approver, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                request.id,
                request.order_id,
                json.dumps([list(item) for item in request.items], ensure_ascii=False),
                request.check_in_date.isoformat(),
                request.check_out_date.isoformat(),
                request.old_total_cents,
                request.new_total_cents,
                request.applicant,
                request.approver,
                request.status.value,
                request.created_at.isoformat(),
            ),
        )

    def get_modify_request(self, request_id: str) -> ModifyRequest | None:
        row = self.conn.execute(
            "SELECT * FROM modify_request WHERE id = ?", (request_id,)
        ).fetchone()
        if row is None:
            return None
        return ModifyRequest(
            id=row["id"],
            order_id=row["order_id"],
            items=tuple((item[0], int(item[1])) for item in json.loads(row["items_json"])),
            check_in_date=date.fromisoformat(row["check_in_date"]),
            check_out_date=date.fromisoformat(row["check_out_date"]),
            old_total_cents=row["old_total_cents"],
            new_total_cents=row["new_total_cents"],
            applicant=row["applicant"],
            approver=row["approver"],
            status=ModifyRequestStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def set_modify_request_status(
        self, request_id: str, status: ModifyRequestStatus, approver: str
    ) -> None:
        self.conn.execute(
            "UPDATE modify_request SET status = ?, approver = ? WHERE id = ?",
            (status.value, approver, request_id),
        )

    def pending_modify_request(self, order_id: str) -> ModifyRequest | None:
        row = self.conn.execute(
            "SELECT id FROM modify_request WHERE order_id = ? AND status = 'PENDING'",
            (order_id,),
        ).fetchone()
        return self.get_modify_request(row["id"]) if row else None

    def list_pending_modify_requests(self, store_id: str) -> list[ModifyRequest]:
        rows = self.conn.execute(
            "SELECT m.id FROM modify_request m JOIN orders o ON o.id = m.order_id"
            " WHERE o.store_id = ? AND m.status = 'PENDING' ORDER BY m.created_at",
            (store_id,),
        ).fetchall()
        return [
            request for row in rows if (request := self.get_modify_request(row["id"])) is not None
        ]
