"""定价的 SQLite 读写。"""

from __future__ import annotations

import sqlite3
from datetime import date

from hotel.m03_pricing.model import (
    ChangeRequestStatus,
    DailyPrice,
    PriceChangeRequest,
    PriceRange,
    PriceSource,
)


class PricingRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def store_of_room_type(self, room_type_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT store_id FROM room_type WHERE id = ?", (room_type_id,)
        ).fetchone()
        return row["store_id"] if row else None

    def area_of_store(self, store_id: str) -> str | None:
        row = self.conn.execute("SELECT area_id FROM store WHERE id = ?", (store_id,)).fetchone()
        return row["area_id"] if row else None

    def insert_price_range(self, price_range: PriceRange) -> None:
        self.conn.execute(
            "INSERT INTO price_range (id, store_id, effective_date, min_cents, max_cents)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                price_range.id,
                price_range.store_id,
                price_range.effective_date.isoformat(),
                price_range.min_cents,
                price_range.max_cents,
            ),
        )

    def latest_range(self, store_id: str, on_date: date) -> PriceRange | None:
        row = self.conn.execute(
            "SELECT * FROM price_range WHERE store_id = ? AND effective_date <= ?"
            " ORDER BY effective_date DESC LIMIT 1",
            (store_id, on_date.isoformat()),
        ).fetchone()
        if row is None:
            return None
        return PriceRange(
            id=row["id"],
            store_id=row["store_id"],
            effective_date=date.fromisoformat(row["effective_date"]),
            min_cents=row["min_cents"],
            max_cents=row["max_cents"],
        )

    def get_price(self, room_type_id: str, on_date: date) -> DailyPrice | None:
        row = self.conn.execute(
            "SELECT * FROM daily_price WHERE room_type_id = ? AND price_date = ?",
            (room_type_id, on_date.isoformat()),
        ).fetchone()
        if row is None:
            return None
        return DailyPrice(
            room_type_id=row["room_type_id"],
            price_date=date.fromisoformat(row["price_date"]),
            price_cents=row["price_cents"],
            source=PriceSource(row["source"]),
        )

    def upsert_price(
        self, room_type_id: str, on_date: date, price_cents: int, source: PriceSource
    ) -> None:
        self.conn.execute(
            "INSERT INTO daily_price (room_type_id, price_date, price_cents, source)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(room_type_id, price_date) DO UPDATE SET"
            " price_cents = excluded.price_cents, source = excluded.source",
            (room_type_id, on_date.isoformat(), price_cents, source.value),
        )

    def insert_request(self, request: PriceChangeRequest) -> None:
        self.conn.execute(
            "INSERT INTO price_change_request"
            " (id, room_type_id, price_date, old_cents, new_cents, applicant,"
            "  approver, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                request.id,
                request.room_type_id,
                request.price_date.isoformat(),
                request.old_cents,
                request.new_cents,
                request.applicant,
                request.approver,
                request.status.value,
                request.price_date.isoformat(),
            ),
        )

    def get_request(self, request_id: str) -> PriceChangeRequest | None:
        row = self.conn.execute(
            "SELECT * FROM price_change_request WHERE id = ?", (request_id,)
        ).fetchone()
        if row is None:
            return None
        return PriceChangeRequest(
            id=row["id"],
            room_type_id=row["room_type_id"],
            price_date=date.fromisoformat(row["price_date"]),
            old_cents=row["old_cents"],
            new_cents=row["new_cents"],
            applicant=row["applicant"],
            approver=row["approver"],
            status=ChangeRequestStatus(row["status"]),
        )

    def set_request_status(
        self, request_id: str, status: ChangeRequestStatus, approver: str
    ) -> None:
        self.conn.execute(
            "UPDATE price_change_request SET status = ?, approver = ? WHERE id = ?",
            (status.value, approver, request_id),
        )

    def list_pending_requests(self, store_id: str) -> list[PriceChangeRequest]:
        rows = self.conn.execute(
            "SELECT r.* FROM price_change_request r"
            " JOIN room_type t ON t.id = r.room_type_id"
            " WHERE t.store_id = ? AND r.status = 'PENDING'"
            " ORDER BY r.created_at",
            (store_id,),
        ).fetchall()
        return [
            PriceChangeRequest(
                id=row["id"],
                room_type_id=row["room_type_id"],
                price_date=date.fromisoformat(row["price_date"]),
                old_cents=row["old_cents"],
                new_cents=row["new_cents"],
                applicant=row["applicant"],
                approver=row["approver"],
                status=ChangeRequestStatus(row["status"]),
            )
            for row in rows
        ]
