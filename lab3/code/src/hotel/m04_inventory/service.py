"""库存的服务层。

可售上限由「房间总数 − 当日维修中 − 线下保留额度」实时算出（REQ-033），
所以维修、保留额度变化后都要重算一次。
"""

from __future__ import annotations

import sqlite3
from datetime import date

from hotel.core.auth import ensure_active
from hotel.core.db import Database, UnitOfWork
from hotel.core.errors import NotFound, PermissionDenied, ValidationError
from hotel.m01_account.model import Role, Session
from hotel.m02_store.repository import StoreRepository
from hotel.m04_inventory.model import DailyInventory
from hotel.m04_inventory.repository import InventoryRepository


class InventoryService:
    def __init__(self, database: Database) -> None:
        self._db = database

    def available_rooms(self, conn: sqlite3.Connection, room_type_id: str, on_date: date) -> int:
        store_repo = StoreRepository(conn)
        return store_repo.count_rooms(room_type_id) - store_repo.count_under_repair(
            room_type_id, on_date
        )

    def ensure_row(
        self, conn: sqlite3.Connection, room_type_id: str, on_date: date
    ) -> DailyInventory:
        repo = InventoryRepository(conn)
        existing = repo.get(room_type_id, on_date)
        if existing is not None:
            return existing
        repo.insert_row(room_type_id, on_date, self.available_rooms(conn, room_type_id, on_date))
        fresh = repo.get(room_type_id, on_date)
        assert fresh is not None
        return fresh

    def query(self, room_type_id: str, on_date: date) -> DailyInventory:
        with UnitOfWork(self._db) as conn:
            return self.ensure_row(conn, room_type_id, on_date)

    def list_between(self, room_type_id: str, start: date, end: date) -> list[DailyInventory]:
        with UnitOfWork(self._db) as conn:
            repo = InventoryRepository(conn)
            for offset in range((end - start).days + 1):
                self.ensure_row(conn, room_type_id, date.fromordinal(start.toordinal() + offset))
            return repo.list_between(room_type_id, start, end)

    def set_offline_reserved(
        self, actor: Session, *, room_type_id: str, on_date: date, reserved: int
    ) -> DailyInventory:
        if actor.role is not Role.STORE_MANAGER:
            raise PermissionDenied("只有店长能设置线下保留额度")
        if reserved < 0:
            raise ValidationError("保留额度不能为负", field="reserved")
        with UnitOfWork(self._db) as conn:
            ensure_active(conn, actor)
            repo = InventoryRepository(conn)
            if repo.store_of_room_type(room_type_id) != actor.store_id:
                raise PermissionDenied("只能设置本店房型的保留额度")
            row = self.ensure_row(conn, room_type_id, on_date)
            available = self.available_rooms(conn, room_type_id, on_date)
            if reserved > available:
                raise ValidationError(
                    f"保留额度不能超过当日可用房间数 {available} 间", field="reserved"
                )
            new_limit = available - reserved
            if new_limit < row.online_sold:
                raise ValidationError(
                    f"线上已售 {row.online_sold} 间，可售上限不能低于已售数量", field="reserved"
                )
            repo.set_limits(room_type_id, on_date, new_limit, reserved)
            updated = repo.get(room_type_id, on_date)
        assert updated is not None
        return updated

    def recompute(self, conn: sqlite3.Connection, room_type_id: str, on_date: date) -> bool:
        """维修状态变化后重算上限。返回是否出现「已售超过上限」的冲突。

        冲突时不自动取消订单，只把差异留给前台换房处理（REQ-033、REQ-034）。
        """
        repo = InventoryRepository(conn)
        row = self.ensure_row(conn, room_type_id, on_date)
        available = self.available_rooms(conn, room_type_id, on_date)
        reserved = min(row.offline_reserved, available)
        limit = available - reserved
        conflict = row.online_sold > limit
        repo.set_limits(room_type_id, on_date, max(limit, 0), reserved)
        return conflict

    def reserve_online(
        self, conn: sqlite3.Connection, room_type_id: str, on_date: date, qty: int
    ) -> bool:
        if qty <= 0:
            raise ValidationError("间数必须为正整数", field="qty")
        self.ensure_row(conn, room_type_id, on_date)
        return InventoryRepository(conn).try_reserve_online(room_type_id, on_date, qty)

    def release_online(
        self, conn: sqlite3.Connection, room_type_id: str, on_date: date, qty: int
    ) -> None:
        self.ensure_row(conn, room_type_id, on_date)
        InventoryRepository(conn).release_online(room_type_id, on_date, qty)

    def reserve_offline(
        self, conn: sqlite3.Connection, room_type_id: str, on_date: date, qty: int
    ) -> bool:
        if qty <= 0:
            raise ValidationError("间数必须为正整数", field="qty")
        self.ensure_row(conn, room_type_id, on_date)
        return InventoryRepository(conn).try_reserve_offline(room_type_id, on_date, qty)

    def release_offline(
        self, conn: sqlite3.Connection, room_type_id: str, on_date: date, qty: int
    ) -> None:
        self.ensure_row(conn, room_type_id, on_date)
        InventoryRepository(conn).release_offline(room_type_id, on_date, qty)

    def get_room_type_or_raise(self, room_type_id: str) -> str:
        with UnitOfWork(self._db) as conn:
            store_id = InventoryRepository(conn).store_of_room_type(room_type_id)
        if store_id is None:
            raise NotFound("房型不存在", field="room_type_id")
        return store_id
