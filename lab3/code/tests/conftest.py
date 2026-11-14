"""测试夹具：每个用例一个独立的 SQLite 库。"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from hotel.core.clock import FakeClock
from hotel.core.db import Database
from hotel.m01_account.model import Role
from hotel.m01_account.service import AccountService
from hotel.m02_store.service import StoreService
from hotel.m03_pricing.service import PricingService
from hotel.m04_inventory.service import InventoryService
from hotel.m05_order.service import OrderService
from hotel.m06_payment.service import PaymentService
from hotel.m07_room.service import RoomService
from hotel.m08_performance.service import PerformanceService
from hotel.m09_audit.service import AuditService


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "hotel.db")
    db.initialize()
    return db


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 11, 14, 10, 0))


@pytest.fixture
def store_service(database: Database) -> StoreService:
    return StoreService(database)


@pytest.fixture
def account_service(database: Database, clock: FakeClock) -> AccountService:
    return AccountService(database, clock)


@pytest.fixture
def pricing_service(database: Database) -> PricingService:
    return PricingService(database)


@pytest.fixture
def inventory_service(database: Database) -> InventoryService:
    return InventoryService(database)


@pytest.fixture
def order_service(
    database: Database, clock: FakeClock, inventory_service: InventoryService
) -> OrderService:
    return OrderService(database, clock, inventory_service)


@pytest.fixture
def payment_service(
    database: Database, clock: FakeClock, inventory_service: InventoryService
) -> PaymentService:
    return PaymentService(database, clock, inventory_service)


@pytest.fixture
def room_service(
    database: Database, clock: FakeClock, inventory_service: InventoryService
) -> RoomService:
    return RoomService(database, clock, inventory_service)


@pytest.fixture
def performance_service(database: Database, clock: FakeClock) -> PerformanceService:
    return PerformanceService(database, clock)


@pytest.fixture
def audit_service(database: Database, clock: FakeClock) -> AuditService:
    return AuditService(database, clock)


@pytest.fixture
def wired_order_service(
    order_service: OrderService, payment_service: PaymentService
) -> OrderService:
    """把支付模块接到订单上，取消订单时才会真的发起退款。"""
    order_service.attach_payment(payment_service)
    return order_service


@pytest.fixture
def shop(
    store_service: StoreService,
    account_service: AccountService,
    pricing_service: PricingService,
) -> dict:
    """一家营业中的门店：两个房型、15 间房、一周房价、四类账号。"""
    area = store_service.create_area("南京片区")
    store = store_service.create_store(area.id, "新街口店", "南京", "新街口")
    room_type = store_service.create_room_type(store.id, "大床房", "大床", 2)
    twin = store_service.create_room_type(store.id, "双床房", "双床", 2)
    store_service.add_rooms(room_type.id, [f"08{index:02d}" for index in range(10)])
    store_service.add_rooms(twin.id, [f"09{index:02d}" for index in range(5)])

    account_service.bootstrap_staff(
        name="片区负责人",
        phone="13900000001",
        password="secret1",
        role=Role.AREA_MANAGER,
        area_id=area.id,
    )
    account_service.bootstrap_staff(
        name="店长",
        phone="13900000002",
        password="secret1",
        role=Role.STORE_MANAGER,
        store_id=store.id,
    )
    account_service.bootstrap_staff(
        name="前台",
        phone="13900000003",
        password="secret1",
        role=Role.FRONT_DESK,
        store_id=store.id,
    )
    account_service.register_customer("张三", "13800000001", "secret1")

    area_manager = account_service.login("13900000001", "secret1")
    manager = account_service.login("13900000002", "secret1")
    front = account_service.login("13900000003", "secret1")
    customer = account_service.login("13800000001", "secret1")

    pricing_service.set_price_range(
        area_manager,
        store_id=store.id,
        effective_date=date(2026, 1, 1),
        min_cents=20000,
        max_cents=80000,
    )
    pricing_service.set_prices(
        manager,
        room_type_id=room_type.id,
        start=date(2026, 11, 14),
        end=date(2026, 11, 27),
        price_cents=50000,
    )
    pricing_service.set_prices(
        manager,
        room_type_id=twin.id,
        start=date(2026, 11, 14),
        end=date(2026, 11, 27),
        price_cents=60000,
    )

    return {
        "area": area,
        "store": store,
        "room_type": room_type,
        "twin": twin,
        "area_manager": area_manager,
        "manager": manager,
        "front": front,
        "customer": customer,
    }
