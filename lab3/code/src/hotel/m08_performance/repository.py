"""评价与绩效的 SQLite 读写。"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from hotel.m08_performance.model import Performance, Review, ReviewStatus


class ReviewRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def insert(self, review: Review) -> None:
        self.conn.execute(
            "INSERT INTO review (id, order_id, score, content, submitted_at, status)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                review.id,
                review.order_id,
                review.score,
                review.content,
                review.submitted_at.isoformat(),
                review.status.value,
            ),
        )

    def of_order(self, order_id: str) -> Review | None:
        row = self.conn.execute("SELECT * FROM review WHERE order_id = ?", (order_id,)).fetchone()
        return self._to_review(row) if row else None

    def get(self, review_id: str) -> Review | None:
        row = self.conn.execute("SELECT * FROM review WHERE id = ?", (review_id,)).fetchone()
        return self._to_review(row) if row else None

    def set_status(self, review_id: str, status: ReviewStatus) -> None:
        self.conn.execute("UPDATE review SET status = ? WHERE id = ?", (status.value, review_id))

    def list_of_store(self, store_id: str) -> list[Review]:
        rows = self.conn.execute(
            "SELECT r.* FROM review r JOIN orders o ON o.id = r.order_id"
            " WHERE o.store_id = ? ORDER BY r.submitted_at DESC",
            (store_id,),
        ).fetchall()
        return [self._to_review(row) for row in rows]

    def insert_performance(self, performance: Performance) -> None:
        self.conn.execute(
            "INSERT INTO store_performance"
            " (id, store_id, period, order_count, occupancy_rate, avg_score)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                performance.id,
                performance.store_id,
                performance.period,
                performance.order_count,
                performance.occupancy_rate,
                performance.avg_score,
            ),
        )

    @staticmethod
    def _to_review(row: sqlite3.Row) -> Review:
        return Review(
            id=row["id"],
            order_id=row["order_id"],
            score=row["score"],
            content=row["content"],
            submitted_at=datetime.fromisoformat(row["submitted_at"]),
            status=ReviewStatus(row["status"]),
        )
