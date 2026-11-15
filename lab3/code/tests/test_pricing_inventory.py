"""M3 定价与 M4 库存的规则。"""

from __future__ import annotations

from datetime import date

import pytest

from hotel.core.db import Database
from hotel.core.errors import ConflictError, NotFound, PermissionDenied, ValidationError
from hotel.m03_pricing.service import PricingService
from hotel.m04_inventory.service import InventoryService

DAY = date(2026, 11, 20)


def _mark_repairing(database: Database, room_type_id: str, count: int) -> None:
    with database.connect() as conn:
        rooms = conn.execute(
            "SELECT id FROM room WHERE room_type_id = ? ORDER BY room_no LIMIT ?",
            (room_type_id, count),
        ).fetchall()
        for room in rooms:
            conn.execute("UPDATE room SET status = 'REPAIRING' WHERE id = ?", (room["id"],))
        conn.commit()


def test_online_limit_follows_formula(
    shop: dict, inventory_service: InventoryService, database: Database
) -> None:
    room_type_id = shop["room_type"].id
    _mark_repairing(database, room_type_id, 1)

    inventory = inventory_service.set_offline_reserved(
        shop["manager"], room_type_id=room_type_id, on_date=DAY, reserved=3
    )

    assert inventory.online_limit == 6
    assert inventory.offline_reserved == 3


def test_reserved_more_than_available_rejected(
    shop: dict, inventory_service: InventoryService, database: Database
) -> None:
    room_type_id = shop["room_type"].id
    _mark_repairing(database, room_type_id, 1)

    with pytest.raises(ValidationError):
        inventory_service.set_offline_reserved(
            shop["manager"], room_type_id=room_type_id, on_date=DAY, reserved=10
        )


def test_limit_cannot_drop_below_sold(shop: dict, inventory_service: InventoryService) -> None:
    room_type_id = shop["room_type"].id
    inventory_service.query(room_type_id, DAY)
    with inventory_service._db.connect() as conn:  # noqa: SLF001 - 直接造已售
        conn.execute(
            "UPDATE daily_inventory SET online_sold = 5" " WHERE room_type_id = ? AND inv_date = ?",
            (room_type_id, DAY.isoformat()),
        )
        conn.commit()

    with pytest.raises(ValidationError):
        inventory_service.set_offline_reserved(
            shop["manager"], room_type_id=room_type_id, on_date=DAY, reserved=6
        )


def test_reserve_is_atomic_and_never_negative(
    shop: dict, inventory_service: InventoryService
) -> None:
    room_type_id = shop["room_type"].id
    with inventory_service._db.connect() as conn:
        inventory_service.query(room_type_id, DAY)
        assert inventory_service.reserve_online(conn, room_type_id, DAY, 10) is True
        assert inventory_service.reserve_online(conn, room_type_id, DAY, 1) is False
        conn.commit()

    inventory = inventory_service.query(room_type_id, DAY)
    assert inventory.online_sold == 10
    assert inventory.online_remaining == 0


def test_release_restores_inventory(shop: dict, inventory_service: InventoryService) -> None:
    room_type_id = shop["room_type"].id
    with inventory_service._db.connect() as conn:
        inventory_service.query(room_type_id, DAY)
        inventory_service.reserve_online(conn, room_type_id, DAY, 2)
        inventory_service.release_online(conn, room_type_id, DAY, 2)
        conn.commit()

    assert inventory_service.query(room_type_id, DAY).online_sold == 0


def test_price_must_be_inside_range(shop: dict, pricing_service: PricingService) -> None:
    room_type_id = shop["room_type"].id

    price = pricing_service.set_price(
        shop["manager"], room_type_id=room_type_id, on_date=DAY, price_cents=50000
    )
    assert price.price_cents == 50000

    with pytest.raises(ValidationError):
        pricing_service.set_price(
            shop["manager"], room_type_id=room_type_id, on_date=DAY, price_cents=90000
        )
    with pytest.raises(ValidationError):
        pricing_service.set_price(
            shop["manager"], room_type_id=room_type_id, on_date=DAY, price_cents=100
        )


def test_only_store_manager_can_change_price(shop: dict, pricing_service: PricingService) -> None:
    with pytest.raises(PermissionDenied):
        pricing_service.set_price(
            shop["front"],
            room_type_id=shop["room_type"].id,
            on_date=DAY,
            price_cents=50000,
        )


def test_price_change_request_flow(shop: dict, pricing_service: PricingService) -> None:
    room_type_id = shop["room_type"].id
    pricing_service.set_price(
        shop["manager"], room_type_id=room_type_id, on_date=DAY, price_cents=50000
    )

    request = pricing_service.request_price_change(
        shop["front"], room_type_id=room_type_id, on_date=DAY, new_cents=60000
    )
    pending = pricing_service.list_pending_requests(shop["manager"], shop["store"].id)
    assert [item.id for item in pending] == [request.id]

    pricing_service.approve_price_change(shop["manager"], request.id)
    assert pricing_service.get_price(room_type_id, DAY).price_cents == 60000

    with pytest.raises(ConflictError):
        pricing_service.approve_price_change(shop["manager"], request.id)


def test_price_range_only_from_area_manager(shop: dict, pricing_service: PricingService) -> None:
    with pytest.raises(PermissionDenied):
        pricing_service.set_price_range(
            shop["manager"],
            store_id=shop["store"].id,
            effective_date=DAY,
            min_cents=1,
            max_cents=2,
        )


def test_missing_price_raises(shop: dict, pricing_service: PricingService) -> None:
    with pytest.raises(NotFound):
        pricing_service.get_price(shop["room_type"].id, date(2027, 1, 1))


def test_price_range_endpoints_are_inclusive(shop: dict, pricing_service: PricingService) -> None:
    for cents in (20000, 80000):
        price = pricing_service.set_price(
            shop["manager"], room_type_id=shop["room_type"].id, on_date=DAY, price_cents=cents
        )
        assert price.price_cents == cents

    for cents in (19999, 80001):
        with pytest.raises(ValidationError):
            pricing_service.set_price(
                shop["manager"],
                room_type_id=shop["room_type"].id,
                on_date=DAY,
                price_cents=cents,
            )
