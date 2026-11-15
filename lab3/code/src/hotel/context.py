"""服务装配。

界面和种子脚本共用同一份装配逻辑：各模块的服务在这里构造，
订单、支付、通知之间的事件订阅也只在这里发生。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hotel.core.clock import Clock, SystemClock
from hotel.core.db import Database
from hotel.core.events import EventBus
from hotel.m01_account.service import AccountService
from hotel.m02_store.service import StoreService
from hotel.m03_pricing.service import PricingService
from hotel.m04_inventory.service import InventoryService
from hotel.m05_order.service import OrderService
from hotel.m06_payment.service import PaymentService
from hotel.m07_room.service import RoomService
from hotel.m08_performance.service import PerformanceService
from hotel.m09_audit.service import AuditService
from hotel.m10_notify.service import InMemoryChannel, NotificationService

DEFAULT_DB_PATH = Path("data") / "hotel.db"


@dataclass
class Services:
    database: Database
    clock: Clock
    store: StoreService
    account: AccountService
    pricing: PricingService
    inventory: InventoryService
    order: OrderService
    payment: PaymentService
    room: RoomService
    performance: PerformanceService
    audit: AuditService
    notify: NotificationService
    channel: InMemoryChannel


def build_services(db_path: str | Path = DEFAULT_DB_PATH, clock: Clock | None = None) -> Services:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(path)
    database.initialize()
    clock = clock or SystemClock()

    store = StoreService(database)
    account = AccountService(database, clock)
    pricing = PricingService(database)
    inventory = InventoryService(database)
    order = OrderService(database, clock, inventory)
    payment = PaymentService(database, clock, inventory)
    room = RoomService(database, clock, inventory)
    performance = PerformanceService(database, clock)
    audit = AuditService(database, clock)
    channel = InMemoryChannel()
    notify = NotificationService(database, clock, channel)

    bus = EventBus()
    notify.subscribe(bus)
    order.attach_events(bus)
    order.attach_payment(payment)
    payment.attach_events(bus)

    return Services(
        database=database,
        clock=clock,
        store=store,
        account=account,
        pricing=pricing,
        inventory=inventory,
        order=order,
        payment=payment,
        room=room,
        performance=performance,
        audit=audit,
        notify=notify,
        channel=channel,
    )
