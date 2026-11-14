"""主流程端到端：查询 → 下单 → 支付 → 查订单。"""

from __future__ import annotations

from datetime import date

from hotel.m02_store.service import StoreService
from hotel.m04_inventory.service import InventoryService
from hotel.m05_order.model import OrderStatus
from hotel.m05_order.service import OrderService, RoomRequest
from hotel.m06_payment.service import PaymentService

CHECK_IN = date(2026, 11, 20)
CHECK_OUT = date(2026, 11, 22)


def test_customer_books_and_pays_end_to_end(
    shop: dict,
    store_service: StoreService,
    order_service: OrderService,
    payment_service: PaymentService,
    inventory_service: InventoryService,
) -> None:
    found = store_service.list_room_types("南京", 2)
    assert any(item.room_type_id == shop["room_type"].id for item in found)

    order = order_service.create_order(
        shop["customer"],
        store_id=shop["store"].id,
        request_no="e2e-1",
        items=[RoomRequest(shop["room_type"].id, 2)],
        check_in=CHECK_IN,
        check_out=CHECK_OUT,
    )
    assert order.status is OrderStatus.PENDING_PAYMENT
    assert order.total_cents == 200_000
    assert len(order.items) == 2

    payment = payment_service.create_payment(shop["customer"], order.id)
    payment_service.handle_callback(payment.pay_no, "TXN-E2E", order.total_cents)

    confirmed = order_service.get_order(shop["customer"], order.id)
    assert confirmed.status is OrderStatus.CONFIRMED
    assert inventory_service.query(shop["room_type"].id, CHECK_IN).online_sold == 2
    assert inventory_service.query(shop["room_type"].id, date(2026, 11, 21)).online_sold == 2
