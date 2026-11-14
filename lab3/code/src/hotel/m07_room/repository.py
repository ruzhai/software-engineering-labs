"""房态与工单的 SQLite 读写。"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from hotel.core.ids import new_id
from hotel.m07_room.model import WorkOrder, WorkOrderStatus, WorkOrderType


class RoomStateRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def set_room_status(self, room_id: str, status: str, repair_until: date | None = None) -> None:
        self.conn.execute(
            "UPDATE room SET status = ?, repair_until = ? WHERE id = ?",
            (status, repair_until.isoformat() if repair_until else None, room_id),
        )

    def add_occupancy(self, order_id: str, room_id: str, stay_date: date) -> None:
        self.conn.execute(
            "INSERT INTO occupancy (id, order_id, room_id, stay_date) VALUES (?, ?, ?, ?)",
            (new_id("occ"), order_id, room_id, stay_date.isoformat()),
        )

    def room_occupied_by_other(self, room_id: str, order_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM orders WHERE room_id = ? AND id <> ?"
            " AND status IN ('CONFIRMED', 'CHECKED_IN', 'NO_SHOW')",
            (room_id, order_id),
        ).fetchone()
        return row is not None

    def insert_work_order(self, work_order: WorkOrder) -> None:
        self.conn.execute(
            "INSERT INTO work_order"
            " (id, room_id, type, reason, involved_date, status, submitter, executor, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                work_order.id,
                work_order.room_id,
                work_order.type.value,
                work_order.reason,
                work_order.involved_date.isoformat(),
                work_order.status.value,
                work_order.submitter,
                work_order.executor,
                work_order.created_at.isoformat(),
            ),
        )

    def get_work_order(self, work_order_id: str) -> WorkOrder | None:
        row = self.conn.execute(
            "SELECT * FROM work_order WHERE id = ?", (work_order_id,)
        ).fetchone()
        if row is None:
            return None
        return WorkOrder(
            id=row["id"],
            room_id=row["room_id"],
            type=WorkOrderType(row["type"]),
            reason=row["reason"],
            involved_date=date.fromisoformat(row["involved_date"]),
            status=WorkOrderStatus(row["status"]),
            submitter=row["submitter"],
            executor=row["executor"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def open_work_order_of_room(self, room_id: str) -> WorkOrder | None:
        row = self.conn.execute(
            "SELECT id FROM work_order WHERE room_id = ? AND status = 'OPEN'", (room_id,)
        ).fetchone()
        return self.get_work_order(row["id"]) if row else None

    def close_work_order(self, work_order_id: str, status: WorkOrderStatus, executor: str) -> None:
        self.conn.execute(
            "UPDATE work_order SET status = ?, executor = ? WHERE id = ?",
            (status.value, executor, work_order_id),
        )

    def list_open_work_orders(self, store_id: str) -> list[WorkOrder]:
        rows = self.conn.execute(
            "SELECT w.id FROM work_order w"
            " JOIN room r ON r.id = w.room_id"
            " JOIN room_type t ON t.id = r.room_type_id"
            " WHERE t.store_id = ? AND w.status = 'OPEN'"
            " ORDER BY w.created_at",
            (store_id,),
        ).fetchall()
        return [order for row in rows if (order := self.get_work_order(row["id"]))]
