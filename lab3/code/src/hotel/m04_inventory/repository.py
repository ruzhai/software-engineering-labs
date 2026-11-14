"""库存的 SQLite 读写。"""

from __future__ import annotations

import sqlite3
from datetime import date

from hotel.m04_inventory.model import DailyInventory


def _to_inventory(row: sqlite3.Row) -> DailyInventory:
    return DailyInventory(
        room_type_id=row["room_type_id"],
        inv_date=date.fromisoformat(row["inv_date"]),
        online_limit=row["online_limit"],
        online_sold=row["online_sold"],
        offline_reserved=row["offline_reserved"],
        offline_sold=row["offline_sold"],
    )


class InventoryRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, room_type_id: str, on_date: date) -> DailyInventory | None:
        row = self.conn.execute(
            "SELECT * FROM daily_inventory WHERE room_type_id = ? AND inv_date = ?",
            (room_type_id, on_date.isoformat()),
        ).fetchone()
        return _to_inventory(row) if row else None

    def insert_row(self, room_type_id: str, on_date: date, online_limit: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO daily_inventory"
            " (room_type_id, inv_date, online_limit, online_sold, offline_reserved, offline_sold)"
            " VALUES (?, ?, ?, 0, 0, 0)",
            (room_type_id, on_date.isoformat(), online_limit),
        )

    def set_limits(
        self, room_type_id: str, on_date: date, online_limit: int, offline_reserved: int
    ) -> None:
        self.conn.execute(
            "UPDATE daily_inventory SET online_limit = ?, offline_reserved = ?"
            " WHERE room_type_id = ? AND inv_date = ?",
            (online_limit, offline_reserved, room_type_id, on_date.isoformat()),
        )

    def try_reserve_online(self, room_type_id: str, on_date: date, qty: int) -> bool:
        # 条件更新是防超卖的关键：影响行数为 0 说明这一晚已经不够了。
        cursor = self.conn.execute(
            "UPDATE daily_inventory SET online_sold = online_sold + ?"
            " WHERE room_type_id = ? AND inv_date = ? AND online_sold + ? <= online_limit",
            (qty, room_type_id, on_date.isoformat(), qty),
        )
        return cursor.rowcount == 1

    def release_online(self, room_type_id: str, on_date: date, qty: int) -> None:
        self.conn.execute(
            "UPDATE daily_inventory SET online_sold = MAX(online_sold - ?, 0)"
            " WHERE room_type_id = ? AND inv_date = ?",
            (qty, room_type_id, on_date.isoformat()),
        )

    def try_reserve_offline(self, room_type_id: str, on_date: date, qty: int) -> bool:
        cursor = self.conn.execute(
            "UPDATE daily_inventory SET offline_sold = offline_sold + ?"
            " WHERE room_type_id = ? AND inv_date = ? AND offline_sold + ? <= offline_reserved",
            (qty, room_type_id, on_date.isoformat(), qty),
        )
        return cursor.rowcount == 1

    def release_offline(self, room_type_id: str, on_date: date, qty: int) -> None:
        self.conn.execute(
            "UPDATE daily_inventory SET offline_sold = MAX(offline_sold - ?, 0)"
            " WHERE room_type_id = ? AND inv_date = ?",
            (qty, room_type_id, on_date.isoformat()),
        )

    def list_between(self, room_type_id: str, start: date, end: date) -> list[DailyInventory]:
        rows = self.conn.execute(
            "SELECT * FROM daily_inventory"
            " WHERE room_type_id = ? AND inv_date >= ? AND inv_date <= ?"
            " ORDER BY inv_date",
            (room_type_id, start.isoformat(), end.isoformat()),
        ).fetchall()
        return [_to_inventory(row) for row in rows]

    def store_of_room_type(self, room_type_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT store_id FROM room_type WHERE id = ?", (room_type_id,)
        ).fetchone()
        return row["store_id"] if row else None
