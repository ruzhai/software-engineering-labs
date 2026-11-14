"""门店与房源的服务层。测试接缝就在这里。"""

from __future__ import annotations

import sqlite3
from datetime import date

from hotel.core.db import Database, UnitOfWork
from hotel.core.errors import ConflictError, NotFound, ValidationError
from hotel.core.ids import new_id
from hotel.m02_store.model import (
    Area,
    Room,
    RoomStatus,
    RoomType,
    RoomTypeOverview,
    Store,
    StoreStatus,
)
from hotel.m02_store.repository import StoreRepository


class StoreService:
    def __init__(self, database: Database) -> None:
        self._db = database

    def create_area(self, name: str) -> Area:
        if not name.strip():
            raise ValidationError("片区名称不能为空", field="name")
        area = Area(id=new_id("area"), name=name.strip())
        with UnitOfWork(self._db) as conn:
            StoreRepository(conn).insert_area(area)
        return area

    def create_store(self, area_id: str, name: str, city: str, district: str) -> Store:
        for value, field, label in (
            (name, "name", "门店名称"),
            (city, "city", "城市"),
            (district, "district", "地段"),
        ):
            if not value.strip():
                raise ValidationError(f"{label}不能为空", field=field)
        store = Store(
            id=new_id("store"),
            area_id=area_id,
            name=name.strip(),
            city=city.strip(),
            district=district.strip(),
            status=StoreStatus.OPEN,
        )
        with UnitOfWork(self._db) as conn:
            repo = StoreRepository(conn)
            if repo.get_area(area_id) is None:
                raise NotFound("片区不存在", field="area_id")
            repo.insert_store(store)
        return store

    def set_store_status(self, store_id: str, status: StoreStatus) -> None:
        with UnitOfWork(self._db) as conn:
            repo = StoreRepository(conn)
            if repo.get_store(store_id) is None:
                raise NotFound("门店不存在", field="store_id")
            repo.update_store_status(store_id, status)

    def create_room_type(
        self, store_id: str, name: str, bed_type: str, max_guests: int, listed: bool = True
    ) -> RoomType:
        if not name.strip():
            raise ValidationError("房型名称不能为空", field="name")
        if max_guests <= 0:
            raise ValidationError("最大入住人数必须为正整数", field="max_guests")
        room_type = RoomType(
            id=new_id("rt"),
            store_id=store_id,
            name=name.strip(),
            bed_type=bed_type.strip(),
            max_guests=max_guests,
            is_listed=listed,
        )
        with UnitOfWork(self._db) as conn:
            repo = StoreRepository(conn)
            if repo.get_store(store_id) is None:
                raise NotFound("门店不存在", field="store_id")
            repo.insert_room_type(room_type)
        return room_type

    def set_room_type_listed(self, room_type_id: str, listed: bool) -> None:
        with UnitOfWork(self._db) as conn:
            repo = StoreRepository(conn)
            if repo.get_room_type(room_type_id) is None:
                raise NotFound("房型不存在", field="room_type_id")
            repo.set_listed(room_type_id, listed)

    def add_room(self, room_type_id: str, room_no: str) -> Room:
        if not room_no.strip():
            raise ValidationError("房号不能为空", field="room_no")
        room = Room(
            id=new_id("room"),
            room_type_id=room_type_id,
            room_no=room_no.strip(),
            status=RoomStatus.FREE,
            repair_until=None,
        )
        try:
            with UnitOfWork(self._db) as conn:
                repo = StoreRepository(conn)
                if repo.get_room_type(room_type_id) is None:
                    raise NotFound("房型不存在", field="room_type_id")
                repo.insert_room(room)
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"房号 {room_no} 在该房型下已存在", field="room_no") from exc
        return room

    def add_rooms(self, room_type_id: str, room_numbers: list[str]) -> list[Room]:
        """批量加房，一次事务完成。店长建店时用，避免逐间往返。"""
        cleaned = [number.strip() for number in room_numbers]
        if any(not number for number in cleaned):
            raise ValidationError("房号不能为空", field="room_no")
        if len(set(cleaned)) != len(cleaned):
            raise ConflictError("同一批房号不能重复", field="room_no")
        rooms = [
            Room(
                id=new_id("room"),
                room_type_id=room_type_id,
                room_no=number,
                status=RoomStatus.FREE,
                repair_until=None,
            )
            for number in cleaned
        ]
        try:
            with UnitOfWork(self._db) as conn:
                repo = StoreRepository(conn)
                if repo.get_room_type(room_type_id) is None:
                    raise NotFound("房型不存在", field="room_type_id")
                for room in rooms:
                    repo.insert_room(room)
        except sqlite3.IntegrityError as exc:
            raise ConflictError("房号已存在", field="room_no") from exc
        return rooms

    def list_rooms(self, room_type_id: str) -> list[Room]:
        with UnitOfWork(self._db) as conn:
            return StoreRepository(conn).list_rooms(room_type_id)

    def count_rooms(self, room_type_id: str) -> int:
        with UnitOfWork(self._db) as conn:
            return StoreRepository(conn).count_rooms(room_type_id)

    def count_under_repair(self, room_type_id: str, on_date: date) -> int:
        with UnitOfWork(self._db) as conn:
            return StoreRepository(conn).count_under_repair(room_type_id, on_date)

    def list_room_types(self, city: str, guests: int) -> list[RoomTypeOverview]:
        if guests <= 0:
            raise ValidationError("入住人数必须为正整数", field="guests")
        with UnitOfWork(self._db) as conn:
            return StoreRepository(conn).list_overview(city.strip(), guests)
