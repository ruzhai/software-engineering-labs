"""REQ-011 并发抢房与 REQ-012 改价互斥。"""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from hotel.core.db import Database
from hotel.core.errors import AppError, ConflictError
from hotel.m03_pricing.service import PricingService
from hotel.m04_inventory.service import InventoryService
from hotel.m05_order.service import OrderService, RoomRequest

NIGHT = date(2026, 11, 20)
NEXT_DAY = date(2026, 11, 21)


def _squeeze(database: Database, inventory_service: InventoryService, room_type_id: str) -> None:
    """把这一晚的线上可售压到只剩 1 间。"""
    with database.connect() as conn:
        inventory_service.query(room_type_id, NIGHT)
        conn.execute(
            "UPDATE daily_inventory SET online_limit = 1, online_sold = 0"
            " WHERE room_type_id = ? AND inv_date = ?",
            (room_type_id, NIGHT.isoformat()),
        )
        conn.commit()


def _book(order_service: OrderService, shop: dict, request_no: str) -> str:
    try:
        order_service.create_order(
            shop["customer"],
            store_id=shop["store"].id,
            request_no=request_no,
            items=[RoomRequest(shop["room_type"].id, 1)],
            check_in=NIGHT,
            check_out=NEXT_DAY,
        )
        return "ok"
    except AppError:
        return "rejected"
    except sqlite3.Error as exc:  # 数据库层面的错误必须暴露出来，不能被当成普通拒绝
        return f"db-error:{exc}"


def test_only_one_booking_wins_the_last_room(
    shop: dict,
    order_service: OrderService,
    inventory_service: InventoryService,
    database: Database,
) -> None:
    database.lock_timeout = 60.0
    _squeeze(database, inventory_service, shop["room_type"].id)
    barrier = threading.Barrier(100)

    def worker(index: int) -> str:
        barrier.wait()
        return _book(order_service, shop, f"race-{index}")

    with ThreadPoolExecutor(max_workers=100) as pool:
        results = list(pool.map(worker, range(100)))

    assert not any(result.startswith("db-error") for result in results), results
    assert results.count("ok") == 1, results
    assert inventory_service.query(shop["room_type"].id, NIGHT).online_sold == 1


def test_price_change_and_booking_do_not_mix(
    shop: dict,
    order_service: OrderService,
    pricing_service: PricingService,
    inventory_service: InventoryService,
    database: Database,
) -> None:
    database.lock_timeout = 60.0
    barrier = threading.Barrier(60)

    def change_price(index: int) -> str:
        barrier.wait()
        try:
            pricing_service.set_price(
                shop["manager"],
                room_type_id=shop["room_type"].id,
                on_date=NIGHT,
                price_cents=50000 if index % 2 else 60000,
            )
            return "changed"
        except AppError as exc:
            return f"rejected:{exc}"

    def place_order(index: int) -> object:
        barrier.wait()
        try:
            order = order_service.create_order(
                shop["customer"],
                store_id=shop["store"].id,
                request_no=f"mix-{index}",
                items=[RoomRequest(shop["room_type"].id, 1)],
                check_in=NIGHT,
                check_out=NEXT_DAY,
            )
            return order.total_cents
        except AppError:
            return None

    tasks = []
    for index in range(30):
        tasks.append(lambda i=index: change_price(i))
        tasks.append(lambda i=index: place_order(i))
    with ThreadPoolExecutor(max_workers=60) as pool:
        results = list(pool.map(lambda task: task(), tasks))

    totals = [value for value in results if isinstance(value, int)]
    assert totals, "至少应有一单成功"
    # 每一单的金额都必须是某一时刻完整生效的价格，不能是拼接出来的中间值。
    assert set(totals) <= {50000, 60000}
    assert not any(isinstance(value, str) and value.startswith("rejected:") for value in results)


def test_price_lock_times_out_instead_of_using_stale_price(
    shop: dict, pricing_service: PricingService, database: Database
) -> None:
    database.lock_timeout = 0.05
    lock = database.price_lock(shop["room_type"].id, NIGHT)
    assert lock.acquire()
    try:
        with pytest.raises(ConflictError):
            pricing_service.set_price(
                shop["manager"],
                room_type_id=shop["room_type"].id,
                on_date=NIGHT,
                price_cents=50000,
            )
    finally:
        lock.release()
