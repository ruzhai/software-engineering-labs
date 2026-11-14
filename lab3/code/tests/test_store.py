"""M2 门店与房源的规则。"""

from __future__ import annotations

from datetime import date

import pytest

from hotel.core.db import Database
from hotel.core.errors import ConflictError, NotFound, ValidationError
from hotel.m02_store.model import StoreStatus
from hotel.m02_store.service import StoreService


def _seed(service: StoreService):
    area = service.create_area("南京片区")
    store = service.create_store(area.id, "新街口店", "南京", "新街口")
    room_type = service.create_room_type(store.id, "大床房", "大床", 2)
    return area, store, room_type


def test_create_store_and_room_type(store_service: StoreService) -> None:
    _, store, room_type = _seed(store_service)

    assert store.city == "南京"
    assert store.status is StoreStatus.OPEN
    assert room_type.max_guests == 2
    assert room_type.is_listed is True


def test_search_filters_city_and_guest_count(store_service: StoreService) -> None:
    area, _, room_type = _seed(store_service)
    hangzhou = store_service.create_store(area.id, "西湖店", "杭州", "西湖")
    store_service.create_room_type(hangzhou.id, "湖景房", "大床", 2)

    assert [item.room_type_id for item in store_service.list_room_types("南京", 2)] == [
        room_type.id
    ]
    assert store_service.list_room_types("南京", 3) == []


def test_closed_store_hidden_from_search(store_service: StoreService) -> None:
    _, store, _ = _seed(store_service)
    store_service.set_store_status(store.id, StoreStatus.CLOSED)

    assert store_service.list_room_types("南京", 2) == []


def test_unlisted_room_type_hidden_from_search(store_service: StoreService) -> None:
    _, _, room_type = _seed(store_service)
    store_service.set_room_type_listed(room_type.id, False)

    assert store_service.list_room_types("南京", 2) == []


def test_room_count_follows_actual_rooms(store_service: StoreService) -> None:
    _, _, room_type = _seed(store_service)
    for number in ("0801", "0802", "0803"):
        store_service.add_room(room_type.id, number)

    overview = store_service.list_room_types("南京", 2)[0]
    assert store_service.count_rooms(room_type.id) == 3
    assert overview.total_rooms == 3
    assert overview.under_repair == 0


def test_duplicate_room_no_rejected(store_service: StoreService) -> None:
    _, _, room_type = _seed(store_service)
    store_service.add_room(room_type.id, "0801")

    with pytest.raises(ConflictError):
        store_service.add_room(room_type.id, "0801")


def test_under_repair_counts_repairing_rooms(
    store_service: StoreService, database: Database
) -> None:
    _, _, room_type = _seed(store_service)
    room = store_service.add_room(room_type.id, "0801")
    with database.connect() as conn:
        conn.execute("UPDATE room SET status = 'REPAIRING' WHERE id = ?", (room.id,))
        conn.commit()

    assert store_service.count_under_repair(room_type.id, date(2026, 11, 14)) == 1


def test_invalid_inputs_rejected(store_service: StoreService) -> None:
    with pytest.raises(ValidationError):
        store_service.create_area("   ")

    area = store_service.create_area("南京片区")
    with pytest.raises(NotFound):
        store_service.create_store("missing-area", "某店", "南京", "新街口")

    store = store_service.create_store(area.id, "新街口店", "南京", "新街口")
    with pytest.raises(ValidationError):
        store_service.create_room_type(store.id, "大床房", "大床", 0)
    with pytest.raises(ValidationError):
        store_service.list_room_types("南京", 0)
