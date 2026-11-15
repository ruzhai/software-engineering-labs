"""M6 支付、退款与超时释放。"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from hotel.core.clock import FakeClock
from hotel.core.db import Database
from hotel.core.errors import ConflictError, NotFound, PermissionDenied, ValidationError
from hotel.m04_inventory.service import InventoryService
from hotel.m05_order.model import OrderStatus
from hotel.m05_order.service import OrderService, RoomRequest
from hotel.m06_payment.model import PaymentStatus
from hotel.m06_payment.service import PaymentService

CHECK_IN = date(2026, 11, 20)
CHECK_OUT = date(2026, 11, 22)


def _place(shop: dict, order_service: OrderService, request_no: str = "pay-1"):
    return order_service.create_order(
        shop["customer"],
        store_id=shop["store"].id,
        request_no=request_no,
        items=[RoomRequest(shop["room_type"].id, 1)],
        check_in=CHECK_IN,
        check_out=CHECK_OUT,
    )


def test_payment_confirms_order(
    shop: dict,
    order_service: OrderService,
    payment_service: PaymentService,
    database: Database,
) -> None:
    order = _place(shop, order_service)
    payment = payment_service.create_payment(shop["customer"], order.id)

    result = payment_service.handle_callback(payment.pay_no, "TXN-1", order.total_cents)

    assert result.status is PaymentStatus.SUCCESS
    assert order_service.get_order(shop["customer"], order.id).status is OrderStatus.CONFIRMED


def test_duplicate_callback_is_idempotent(
    shop: dict, order_service: OrderService, payment_service: PaymentService
) -> None:
    order = _place(shop, order_service, "pay-dup")
    payment = payment_service.create_payment(shop["customer"], order.id)

    first = payment_service.handle_callback(payment.pay_no, "TXN-1", order.total_cents)
    second = payment_service.handle_callback(payment.pay_no, "TXN-1", order.total_cents)

    assert first.id == second.id
    assert second.status is PaymentStatus.SUCCESS


def test_amount_mismatch_rejected(
    shop: dict, order_service: OrderService, payment_service: PaymentService
) -> None:
    order = _place(shop, order_service, "pay-amount")
    payment = payment_service.create_payment(shop["customer"], order.id)

    with pytest.raises(ValidationError):
        payment_service.handle_callback(payment.pay_no, "TXN", order.total_cents + 1)


def test_create_payment_requires_own_pending_order(
    shop: dict, order_service: OrderService, payment_service: PaymentService
) -> None:
    order = _place(shop, order_service, "pay-scope")
    payment_service.pay(payment_service.create_payment(shop["customer"], order.id).pay_no)

    with pytest.raises(ConflictError):
        payment_service.create_payment(shop["customer"], order.id)
    with pytest.raises(NotFound):
        payment_service.create_payment(shop["customer"], "no-such-order")


def test_expire_unpaid_releases_inventory_once(
    shop: dict,
    order_service: OrderService,
    payment_service: PaymentService,
    inventory_service: InventoryService,
    clock: FakeClock,
) -> None:
    order = _place(shop, order_service, "pay-expire")
    clock.advance(minutes=16)

    assert payment_service.expire_unpaid_orders() == 1
    assert order_service.get_order(shop["customer"], order.id).status is OrderStatus.CANCELLED
    assert inventory_service.query(shop["room_type"].id, CHECK_IN).online_sold == 0

    assert payment_service.expire_unpaid_orders() == 0
    assert inventory_service.query(shop["room_type"].id, CHECK_IN).online_sold == 0


def test_cancel_paid_order_refunds_once(
    shop: dict,
    wired_order_service: OrderService,
    payment_service: PaymentService,
    database: Database,
) -> None:
    order = _place(shop, wired_order_service, "pay-refund")
    payment_service.pay(payment_service.create_payment(shop["customer"], order.id).pay_no)

    wired_order_service.cancel_order(shop["customer"], order.id, "行程有变")

    from hotel.m06_payment.repository import PaymentRepository

    with database.connect() as conn:
        refund = PaymentRepository(conn).refund_of_order(order.id)
    assert refund is not None
    assert refund.amount_cents == order.total_cents

    with pytest.raises(ConflictError):
        wired_order_service.cancel_order(shop["customer"], order.id, "再取消一次")


def test_no_show_and_overdue_release(
    shop: dict,
    order_service: OrderService,
    payment_service: PaymentService,
    inventory_service: InventoryService,
    clock: FakeClock,
) -> None:
    order = order_service.create_order(
        shop["customer"],
        store_id=shop["store"].id,
        request_no="no-show",
        items=[RoomRequest(shop["room_type"].id, 1)],
        check_in=date(2026, 11, 14),
        check_out=date(2026, 11, 15),
    )
    payment_service.pay(payment_service.create_payment(shop["customer"], order.id).pay_no)

    clock.set(datetime(2026, 11, 14, 22, 5))
    assert payment_service.mark_no_show() == 1
    assert order_service.get_order(shop["customer"], order.id).status is OrderStatus.NO_SHOW

    clock.set(datetime(2026, 11, 15, 12, 1))
    assert payment_service.release_overdue_no_show() == 1
    assert order_service.get_order(shop["customer"], order.id).status is OrderStatus.CANCELLED
    assert inventory_service.query(shop["room_type"].id, date(2026, 11, 14)).online_sold == 0


def test_callback_after_cancel_records_reconciliation(
    shop: dict,
    order_service: OrderService,
    payment_service: PaymentService,
    clock: FakeClock,
) -> None:
    order = _place(shop, order_service, "pay-late-callback")
    payment = payment_service.create_payment(shop["customer"], order.id)
    clock.advance(minutes=16)
    payment_service.expire_unpaid_orders()

    result = payment_service.handle_callback(payment.pay_no, "TXN-LATE", order.total_cents)
    assert result.status is PaymentStatus.SUCCESS

    records = payment_service.reconcile(clock.today())
    assert any(record.payment_id == payment.id for record in records)


def test_only_customer_can_pay(
    shop: dict, order_service: OrderService, payment_service: PaymentService
) -> None:
    order = _place(shop, order_service, "pay-role")

    with pytest.raises(PermissionDenied):
        payment_service.create_payment(shop["front"], order.id)


def test_second_payment_for_same_order_rejected(
    shop: dict, order_service: OrderService, payment_service: PaymentService
) -> None:
    order = _place(shop, order_service, "pay-dup-create")
    payment_service.create_payment(shop["customer"], order.id)

    with pytest.raises(ConflictError):
        payment_service.create_payment(shop["customer"], order.id)


def test_gateway_double_charge_is_reconciled(
    shop: dict,
    order_service: OrderService,
    payment_service: PaymentService,
    clock: FakeClock,
    database: Database,
) -> None:
    """网关侧重复扣款：两笔支付都成功时，第二笔记成对账差异。"""
    order = _place(shop, order_service, "pay-dup-callback")
    first = payment_service.create_payment(shop["customer"], order.id)
    payment_service.pay(first.pay_no)

    with database.connect() as conn:
        conn.execute(
            "INSERT INTO payment (id, pay_no, order_id, amount_cents, channel, status,"
            " created_at) VALUES ('pmt_dup', 'pay_dup', ?, ?, 'ONLINE', 'PENDING', ?)",
            (order.id, order.total_cents, clock.now().isoformat()),
        )
        conn.commit()

    second = payment_service.handle_callback("pay_dup", "TXN-DUP", order.total_cents)
    assert second.status is PaymentStatus.SUCCESS

    records = payment_service.reconcile(clock.today())
    assert any(record.diff_type == "DUPLICATE_PAYMENT" for record in records)


def test_expiry_boundary_is_strict(
    shop: dict, order_service: OrderService, payment_service: PaymentService, clock: FakeClock
) -> None:
    """REQ-020：正好 15 分钟不释放，超过 1 秒才释放。"""
    order = _place(shop, order_service, "edge-expire")
    payment_service.create_payment(shop["customer"], order.id)

    clock.advance(minutes=15)
    assert payment_service.expire_unpaid_orders() == 0
    clock.advance(seconds=1)
    assert payment_service.expire_unpaid_orders() == 1


def test_no_show_boundary_starts_at_22(
    shop: dict, order_service: OrderService, payment_service: PaymentService, clock: FakeClock
) -> None:
    clock.set(datetime(2026, 11, 20, 9, 0))
    order = order_service.create_order(
        shop["customer"],
        store_id=shop["store"].id,
        request_no="edge-no-show",
        items=[RoomRequest(shop["room_type"].id, 1)],
        check_in=date(2026, 11, 20),
        check_out=date(2026, 11, 21),
    )
    payment_service.pay(payment_service.create_payment(shop["customer"], order.id).pay_no)

    clock.set(datetime(2026, 11, 20, 21, 59))
    assert payment_service.mark_no_show() == 0
    clock.set(datetime(2026, 11, 20, 22, 0))
    assert payment_service.mark_no_show() == 1


def test_overdue_release_boundary_at_next_noon(
    shop: dict, order_service: OrderService, payment_service: PaymentService, clock: FakeClock
) -> None:
    clock.set(datetime(2026, 11, 20, 9, 0))
    order = order_service.create_order(
        shop["customer"],
        store_id=shop["store"].id,
        request_no="edge-overdue",
        items=[RoomRequest(shop["room_type"].id, 1)],
        check_in=date(2026, 11, 20),
        check_out=date(2026, 11, 21),
    )
    payment_service.pay(payment_service.create_payment(shop["customer"], order.id).pay_no)
    clock.set(datetime(2026, 11, 20, 22, 5))
    payment_service.mark_no_show()

    clock.set(datetime(2026, 11, 21, 11, 59))
    assert payment_service.release_overdue_no_show() == 0
    clock.set(datetime(2026, 11, 21, 12, 0))
    assert payment_service.release_overdue_no_show() == 1
