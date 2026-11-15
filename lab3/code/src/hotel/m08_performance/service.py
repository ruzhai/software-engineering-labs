"""评价与绩效的服务层。

评价只能由顾客在自己的已退房订单上提交一次；绩效按门店汇总，
评价分数只计入门店与店长，不计入前台（REQ-003、REQ-006、REQ-007）。
"""

from __future__ import annotations

from datetime import date

from hotel.core.auth import ensure_active
from hotel.core.clock import Clock
from hotel.core.db import Database, UnitOfWork
from hotel.core.errors import ConflictError, NotFound, PermissionDenied, ValidationError
from hotel.core.ids import new_id
from hotel.m01_account.model import Role, Session
from hotel.m05_order.model import OrderStatus
from hotel.m05_order.repository import OrderRepository
from hotel.m08_performance.model import Performance, Review, ReviewStatus
from hotel.m08_performance.repository import ReviewRepository


class PerformanceService:
    def __init__(self, database: Database, clock: Clock) -> None:
        self._db = database
        self._clock = clock

    def submit_review(self, actor: Session, *, order_id: str, score: int, content: str) -> Review:
        if actor.role is not Role.CUSTOMER:
            raise PermissionDenied("只有顾客能提交评价")
        if not 1 <= score <= 5:
            raise ValidationError("评分需在 1 到 5 之间", field="score")
        if not content.strip():
            raise ValidationError("评价内容不能为空", field="content")
        with UnitOfWork(self._db) as conn:
            ensure_active(conn, actor)
            order = OrderRepository(conn).get_order(order_id)
            if order is None:
                raise NotFound("订单不存在", field="order_id")
            if order.customer_id != actor.user_id:
                raise PermissionDenied("只能评价自己的订单")
            if order.status is not OrderStatus.CHECKED_OUT:
                raise ConflictError("只有已退房的订单可以评价", field="status")
            repo = ReviewRepository(conn)
            if repo.of_order(order_id) is not None:
                raise ConflictError("该订单已经评价过了", field="order_id")
            review = Review(
                id=new_id("rev"),
                order_id=order_id,
                score=score,
                content=content.strip(),
                submitted_at=self._clock.now(),
                status=ReviewStatus.PUBLISHED,
            )
            repo.insert(review)
        return review

    def moderate_review(self, actor: Session, review_id: str, *, publish: bool) -> Review:
        if actor.role not in (Role.STORE_MANAGER, Role.AREA_MANAGER):
            raise PermissionDenied("只有店长或片区负责人能审核评价")
        with UnitOfWork(self._db) as conn:
            ensure_active(conn, actor)
            repo = ReviewRepository(conn)
            review = repo.get(review_id)
            if review is None:
                raise NotFound("评价不存在", field="review_id")
            order = OrderRepository(conn).get_order(review.order_id)
            assert order is not None
            if actor.role is Role.STORE_MANAGER and order.store_id != actor.store_id:
                raise PermissionDenied("只能审核本店评价")
            repo.set_status(review_id, ReviewStatus.PUBLISHED if publish else ReviewStatus.HIDDEN)
            updated = repo.get(review_id)
        assert updated is not None
        return updated

    def list_reviews(self, actor: Session, store_id: str) -> list[Review]:
        if actor.role not in (Role.STORE_MANAGER, Role.AREA_MANAGER):
            raise PermissionDenied("只有店长或片区负责人能查看评价")
        if actor.role is Role.STORE_MANAGER and actor.store_id != store_id:
            raise PermissionDenied("只能查看本店评价")
        with UnitOfWork(self._db) as conn:
            return ReviewRepository(conn).list_of_store(store_id)

    def aggregate_performance(
        self, actor: Session, *, store_id: str, start: date, end: date, period: str
    ) -> Performance:
        if actor.role is Role.STORE_MANAGER and actor.store_id != store_id:
            raise PermissionDenied("只能汇总本店绩效")
        if actor.role is Role.AREA_MANAGER:
            row = self._conn_scalar(
                "SELECT area_id FROM store WHERE id = ?", (store_id,), "area_id"
            )
            if row != actor.area_id:
                raise PermissionDenied("只能汇总本片区门店的绩效")
        if actor.role not in (Role.STORE_MANAGER, Role.AREA_MANAGER):
            raise PermissionDenied("当前角色不能查看绩效")
        if end < start:
            raise ValidationError("结束日期不能早于开始日期", field="end")

        days = (end - start).days + 1
        with UnitOfWork(self._db) as conn:
            order_count = conn.execute(
                "SELECT COUNT(*) AS n FROM orders"
                " WHERE store_id = ? AND substr(created_at, 1, 10) BETWEEN ? AND ?"
                " AND status <> 'CANCELLED'",
                (store_id, start.isoformat(), end.isoformat()),
            ).fetchone()["n"]
            total_rooms = conn.execute(
                "SELECT COUNT(*) AS n FROM room r JOIN room_type t ON t.id = r.room_type_id"
                " WHERE t.store_id = ?",
                (store_id,),
            ).fetchone()["n"]
            occupied = conn.execute(
                "SELECT COUNT(DISTINCT o.room_id || '|' || o.stay_date) AS n"
                " FROM occupancy o JOIN orders od ON od.id = o.order_id"
                " WHERE od.store_id = ? AND o.stay_date BETWEEN ? AND ?",
                (store_id, start.isoformat(), end.isoformat()),
            ).fetchone()["n"]
            avg_score = conn.execute(
                "SELECT AVG(r.score) AS s FROM review r JOIN orders o ON o.id = r.order_id"
                " WHERE o.store_id = ? AND r.status = 'PUBLISHED'"
                " AND substr(r.submitted_at, 1, 10) BETWEEN ? AND ?",
                (store_id, start.isoformat(), end.isoformat()),
            ).fetchone()["s"]
            capacity = total_rooms * days
            performance = Performance(
                id=new_id("perf"),
                store_id=store_id,
                period=period,
                order_count=int(order_count),
                occupancy_rate=round(occupied / capacity, 4) if capacity else 0.0,
                avg_score=round(float(avg_score), 2) if avg_score is not None else 0.0,
            )
            ReviewRepository(conn).insert_performance(performance)
        return performance

    def _conn_scalar(self, sql: str, params: tuple, key: str):
        with UnitOfWork(self._db) as conn:
            row = conn.execute(sql, params).fetchone()
        return row[key] if row else None
