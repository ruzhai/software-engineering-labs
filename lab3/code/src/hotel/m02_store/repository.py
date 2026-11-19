"""门店与房源的 SQLite 读写。"""

from __future__ import annotations

import sqlite3
from datetime import date

from hotel.m02_store.model import (
    Area,
    Room,
    RoomStatus,
    RoomType,
    RoomTypeOverview,
    Store,
    StoreStatus,
)


def _to_store(row: sqlite3.Row) -> Store:
    return Store(
        id=row["id"],
        area_id=row["area_id"],
        name=row["name"],
        city=row["city"],
        district=row["district"],
        status=StoreStatus(row["status"]),
    )


def _to_room_type(row: sqlite3.Row) -> RoomType:
    return RoomType(
        id=row["id"],
        store_id=row["store_id"],
        name=row["name"],
        bed_type=row["bed_type"],
        max_guests=row["max_guests"],
        is_listed=bool(row["is_listed"]),
    )


def _to_room(row: sqlite3.Row) -> Room:
    return Room(
        id=row["id"],
        room_type_id=row["room_type_id"],
        room_no=row["room_no"],
        status=RoomStatus(row["status"]),
        repair_until=date.fromisoformat(row["repair_until"]) if row["repair_until"] else None,
    )


class StoreRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def insert_area(self, area: Area) -> None:
        self.conn.execute("INSERT INTO area (id, name) VALUES (?, ?)", (area.id, area.name))

    def get_area(self, area_id: str) -> Area | None:
        row = self.conn.execute("SELECT id, name FROM area WHERE id = ?", (area_id,)).fetchone()
        return Area(id=row["id"], name=row["name"]) if row else None

    def list_areas(self) -> list[Area]:
        rows = self.conn.execute("SELECT id, name FROM area ORDER BY name").fetchall()
        return [Area(id=row["id"], name=row["name"]) for row in rows]

    def insert_store(self, store: Store) -> None:
        self.conn.execute(
            "INSERT INTO store (id, area_id, name, city, district, status)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                store.id,
                store.area_id,
                store.name,
                store.city,
                store.district,
                store.status.value,
            ),
        )

    def get_store(self, store_id: str) -> Store | None:
        row = self.conn.execute("SELECT * FROM store WHERE id = ?", (store_id,)).fetchone()
        return _to_store(row) if row else None

    def list_of_area(self, area_id: str) -> list[Store]:
        rows = self.conn.execute(
            "SELECT * FROM store WHERE area_id = ? ORDER BY name", (area_id,)
        ).fetchall()
        return [_to_store(row) for row in rows]

    def update_store_status(self, store_id: str, status: StoreStatus) -> None:
        self.conn.execute("UPDATE store SET status = ? WHERE id = ?", (status.value, store_id))

    def insert_room_type(self, room_type: RoomType) -> None:
        self.conn.execute(
            "INSERT INTO room_type (id, store_id, name, bed_type, max_guests, is_listed)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                room_type.id,
                room_type.store_id,
                room_type.name,
                room_type.bed_type,
                room_type.max_guests,
                int(room_type.is_listed),
            ),
        )

    def get_room_type(self, room_type_id: str) -> RoomType | None:
        row = self.conn.execute("SELECT * FROM room_type WHERE id = ?", (room_type_id,)).fetchone()
        return _to_room_type(row) if row else None

    def list_room_types_of_store(self, store_id: str) -> list[RoomType]:
        rows = self.conn.execute(
            "SELECT * FROM room_type WHERE store_id = ? ORDER BY name", (store_id,)
        ).fetchall()
        return [_to_room_type(row) for row in rows]

    def set_listed(self, room_type_id: str, listed: bool) -> None:
        self.conn.execute(
            "UPDATE room_type SET is_listed = ? WHERE id = ?", (int(listed), room_type_id)
        )

    def insert_room(self, room: Room) -> None:
        self.conn.execute(
            "INSERT INTO room (id, room_type_id, room_no, status, repair_until)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                room.id,
                room.room_type_id,
                room.room_no,
                room.status.value,
                room.repair_until.isoformat() if room.repair_until else None,
            ),
        )

    def get_room(self, room_id: str) -> Room | None:
        row = self.conn.execute("SELECT * FROM room WHERE id = ?", (room_id,)).fetchone()
        return _to_room(row) if row else None

    def list_rooms(self, room_type_id: str) -> list[Room]:
        rows = self.conn.execute(
            "SELECT * FROM room WHERE room_type_id = ? ORDER BY room_no", (room_type_id,)
        ).fetchall()
        return [_to_room(row) for row in rows]

    def count_rooms(self, room_type_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM room WHERE room_type_id = ?", (room_type_id,)
        ).fetchone()
        return int(row["n"])

    def count_under_repair(self, room_type_id: str, on_date: date) -> int:
        # 未登记修复日期的维修房间按「持续占用」计（REQ-034）。
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM room"
            " WHERE room_type_id = ? AND status = 'REPAIRING'"
            " AND (repair_until IS NULL OR repair_until >= ?)",
            (room_type_id, on_date.isoformat()),
        ).fetchone()
        return int(row["n"])

    def list_overview(self, city: str, guests: int) -> list[RoomTypeOverview]:
        rows = self.conn.execute(
            """
            SELECT t.id AS room_type_id,
                   t.name AS room_type_name,
                   s.id AS store_id,
                   s.name AS store_name,
                   s.city AS city,
                   s.district AS district,
                   t.bed_type AS bed_type,
                   t.max_guests AS max_guests,
                   (SELECT COUNT(*) FROM room r WHERE r.room_type_id = t.id) AS total_rooms,
                   (SELECT COUNT(*) FROM room r
                     WHERE r.room_type_id = t.id AND r.status = 'REPAIRING') AS under_repair
              FROM room_type t
              JOIN store s ON s.id = t.store_id
             WHERE s.city = ? AND s.status = 'OPEN' AND t.is_listed = 1 AND t.max_guests >= ?
             ORDER BY s.name, t.name
            """,
            (city, guests),
        ).fetchall()
        return [
            RoomTypeOverview(
                room_type_id=row["room_type_id"],
                room_type_name=row["room_type_name"],
                store_id=row["store_id"],
                store_name=row["store_name"],
                city=row["city"],
                district=row["district"],
                bed_type=row["bed_type"],
                max_guests=row["max_guests"],
                total_rooms=row["total_rooms"],
                under_repair=row["under_repair"],
            )
            for row in rows
        ]
