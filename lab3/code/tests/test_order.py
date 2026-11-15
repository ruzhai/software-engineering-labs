"""M5 订单状态机、库存扣减与取消规则。"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from hotel.core.clock import FakeClock
from hotel.core.errors import ConflictError, NotFound, PermissionDenied, ValidationError
from hotel.m01_account.service import AccountService
from hotel.m04_inventory.service import InventoryService
from hotel.m05_order.model import OrderStatus, can_transition
from hotel.m05_order.service import OrderService, RoomRequest
from hotel.m06_payment.repository import PaymentRepository

CHECK_IN = date(2026, 11, 20)
CHECK_OUT = date(2026, 11, 22)


def _order(
    shop: dict,
    order_service: OrderService,
    request_no: str = "req-1",
    qty: int = 1,
    room_type_key: str = "room_type",
):
    return order_service.create_order(
        shop["customer"],
        store_id=shop["store"].id,
        request_no=request_no,
        items=[RoomRequest(shop[room_type_key].id, qty)],
        check_in=CHECK_IN,
        check_out=CHECK_OUT,
    )


def test_create_order_builds_nightly_items_and_reserves(
    shop: dict, order_service: OrderService, inventory_service: InventoryService
) -> None:
    order = _order(shop, order_service)

    assert order.status is OrderStatus.PENDING_PAYMENT
    assert len(order.items) == 2
    assert order.total_cents == 100_000
    assert inventory_service.query(shop["room_type"].id, CHECK_IN).online_sold == 1
    assert inventory_service.query(shop["room_type"].id, date(2026, 11, 21)).online_sold == 1


def test_duplicate_request_returns_the_same_order(shop: dict, order_service: OrderService) -> None:
    first = _order(shop, order_service, request_no="same")
    second = _order(shop, order_service, request_no="same")

    assert first.id == second.id
    assert len(order_service.list_my_orders(shop["customer"])) == 1


def test_insufficient_inventory_rolls_back_the_whole_order(
    shop: dict,
    order_service: OrderService,
    inventory_service: InventoryService,
    database,
) -> None:
    second_night = date(2026, 11, 21)
    with database.connect() as conn:
        inventory_service.query(shop["room_type"].id, CHECK_IN)
        inventory_service.query(shop["room_type"].id, second_night)
        inventory_service.reserve_online(conn, shop["room_type"].id, second_night, 10)
        conn.commit()

    with pytest.raises(ConflictError):
        _order(shop, order_service, request_no="rollback")

    assert inventory_service.query(shop["room_type"].id, CHECK_IN).online_sold == 0
    assert inventory_service.query(shop["room_type"].id, second_night).online_sold == 10


def test_invalid_dates_and_empty_items_rejected(shop: dict, order_service: OrderService) -> None:
    with pytest.raises(ValidationError):
        order_service.create_order(
            shop["customer"],
            store_id=shop["store"].id,
            request_no="bad-date",
            items=[RoomRequest(shop["room_type"].id, 1)],
            check_in=CHECK_IN,
            check_out=CHECK_IN,
        )
    with pytest.raises(ValidationError):
        order_service.create_order(
            shop["customer"],
            store_id=shop["store"].id,
            request_no="no-items",
            items=[],
            check_in=CHECK_IN,
            check_out=CHECK_OUT,
        )


def test_state_machine_rejects_illegal_transitions(shop: dict, order_service: OrderService) -> None:
    order = _order(shop, order_service)

    assert can_transition(OrderStatus.CONFIRMED, OrderStatus.CHECKED_IN)
    assert not can_transition(OrderStatus.PENDING_PAYMENT, OrderStatus.CHECKED_IN)
    assert not can_transition(OrderStatus.CHECKED_OUT, OrderStatus.CONFIRMED)

    with pytest.raises(ConflictError):
        order_service.change_status(order.id, OrderStatus.CHECKED_IN)


def test_customer_cancel_before_deadline_releases_inventory(
    shop: dict, order_service: OrderService, inventory_service: InventoryService
) -> None:
    order = _order(shop, order_service, request_no="cancel-early")

    cancelled = order_service.cancel_order(shop["customer"], order.id, "行程有变")

    assert cancelled.status is OrderStatus.CANCELLED
    assert inventory_service.query(shop["room_type"].id, CHECK_IN).online_sold == 0


def test_customer_cannot_cancel_after_deadline(
    shop: dict, order_service: OrderService, clock: FakeClock
) -> None:
    order = _order(shop, order_service, request_no="cancel-late")
    clock.set(datetime(2026, 11, 20, 18, 1))

    with pytest.raises(PermissionDenied):
        order_service.cancel_order(shop["customer"], order.id, "太晚了")


def test_front_desk_requests_cancel_and_manager_approves(
    shop: dict,
    order_service: OrderService,
    clock: FakeClock,
    inventory_service: InventoryService,
) -> None:
    order = _order(shop, order_service, request_no="cancel-request")
    clock.set(datetime(2026, 11, 20, 19, 0))

    with pytest.raises(ConflictError):
        order_service.cancel_order(shop["front"], order.id, "顾客来电")

    request = order_service.request_cancel(shop["front"], order.id, "顾客来电取消")
    with pytest.raises(PermissionDenied):
        order_service.approve_cancel_request(shop["customer"], request.id)

    cancelled = order_service.approve_cancel_request(shop["manager"], request.id)
    assert cancelled.status is OrderStatus.CANCELLED
    assert inventory_service.query(shop["room_type"].id, CHECK_IN).online_sold == 0


def test_duplicate_cancel_request_rejected(
    shop: dict, order_service: OrderService, clock: FakeClock
) -> None:
    order = _order(shop, order_service, request_no="dup-cancel")
    clock.set(datetime(2026, 11, 20, 19, 0))
    order_service.request_cancel(shop["front"], order.id, "第一次")

    with pytest.raises(ConflictError):
        order_service.request_cancel(shop["front"], order.id, "第二次")


def test_modify_order_replaces_items_and_inventory(
    shop: dict, order_service: OrderService, inventory_service: InventoryService
) -> None:
    order = _order(shop, order_service, request_no="modify")
    order_service.change_status(order.id, OrderStatus.CONFIRMED)

    modified = order_service.modify_order(
        shop["customer"],
        order.id,
        items=[RoomRequest(shop["twin"].id, 1)],
        check_in=date(2026, 11, 23),
        check_out=date(2026, 11, 24),
    )

    assert modified.check_in_date == date(2026, 11, 23)
    assert {item.room_type_id for item in modified.items} == {shop["twin"].id}
    assert inventory_service.query(shop["room_type"].id, CHECK_IN).online_sold == 0
    assert inventory_service.query(shop["twin"].id, date(2026, 11, 23)).online_sold == 1


def test_order_scope_is_enforced(
    shop: dict, order_service: OrderService, account_service: AccountService
) -> None:
    order = _order(shop, order_service, request_no="scope")
    account_service.register_customer("李四", "13800000002", "secret1")
    other = account_service.login("13800000002", "secret1")

    with pytest.raises(PermissionDenied):
        order_service.get_order(other, order.id)
    with pytest.raises(PermissionDenied):
        order_service.list_my_orders(shop["front"])


def test_missing_order_raises(shop: dict, order_service: OrderService) -> None:
    with pytest.raises(NotFound):
        order_service.get_order(shop["customer"], "no-such-order")


def test_walk_in_order_uses_offline_quota(
    shop: dict, order_service: OrderService, inventory_service: InventoryService
) -> None:
    """REQ-033：前台开单从线下保留额度扣减，不占用线上库存。"""
    for night in (CHECK_IN, date(2026, 11, 21)):
        inventory_service.set_offline_reserved(
            shop["manager"], room_type_id=shop["room_type"].id, on_date=night, reserved=3
        )

    order = order_service.create_walk_in_order(
        shop["front"],
        store_id=shop["store"].id,
        customer_id=shop["customer"].user_id,
        request_no="walkin-1",
        items=[RoomRequest(shop["room_type"].id, 1)],
        check_in=CHECK_IN,
        check_out=CHECK_OUT,
    )

    assert order.status is OrderStatus.CONFIRMED
    inventory = inventory_service.query(shop["room_type"].id, CHECK_IN)
    assert inventory.offline_sold == 1
    assert inventory.online_sold == 0


def test_walk_in_order_rejected_without_offline_quota(
    shop: dict, order_service: OrderService
) -> None:
    with pytest.raises(ConflictError):
        order_service.create_walk_in_order(
            shop["front"],
            store_id=shop["store"].id,
            customer_id=shop["customer"].user_id,
            request_no="walkin-2",
            items=[RoomRequest(shop["room_type"].id, 1)],
            check_in=CHECK_IN,
            check_out=CHECK_OUT,
        )


def test_no_show_order_can_be_cancelled_by_request(
    shop: dict,
    wired_order_service: OrderService,
    payment_service,
    clock: FakeClock,
    database,
) -> None:
    """REQ-022：未到店期间顾客主动取消按 REQ-021 处理；REQ-021：不产生退款。"""
    order = _order(shop, wired_order_service, request_no="no-show-cancel")
    payment_service.pay(payment_service.create_payment(shop["customer"], order.id).pay_no)

    clock.set(datetime(2026, 11, 20, 22, 5))
    payment_service.mark_no_show()

    clock.set(datetime(2026, 11, 20, 22, 30))
    request = wired_order_service.request_cancel(shop["front"], order.id, "顾客确认不来了")
    cancelled = wired_order_service.approve_cancel_request(shop["manager"], request.id)

    assert cancelled.status is OrderStatus.CANCELLED
    with database.connect() as conn:
        assert PaymentRepository(conn).refund_of_order(order.id) is None


def test_modify_with_refund_before_deadline_needs_no_approval(
    shop: dict,
    wired_order_service: OrderService,
    payment_service,
    database,
) -> None:
    order = _order(shop, wired_order_service, request_no="mod-free")
    payment_service.pay(payment_service.create_payment(shop["customer"], order.id).pay_no)

    modified = wired_order_service.modify_order(
        shop["customer"],
        order.id,
        items=[RoomRequest(shop["room_type"].id, 1)],
        check_in=CHECK_IN,
        check_out=date(2026, 11, 21),
    )

    assert modified.check_out_date == date(2026, 11, 21)
    assert modified.total_cents == 50_000
    with database.connect() as conn:
        assert PaymentRepository(conn).sum_refunded(order.id) == 50_000


def test_modify_with_refund_after_deadline_needs_manager_approval(
    shop: dict,
    wired_order_service: OrderService,
    payment_service,
    clock: FakeClock,
) -> None:
    order = _order(shop, wired_order_service, request_no="mod-approve")
    payment_service.pay(payment_service.create_payment(shop["customer"], order.id).pay_no)
    clock.set(datetime(2026, 11, 20, 19, 0))

    with pytest.raises(ConflictError):
        wired_order_service.modify_order(
            shop["customer"],
            order.id,
            items=[RoomRequest(shop["room_type"].id, 1)],
            check_in=CHECK_IN,
            check_out=date(2026, 11, 21),
        )

    request = wired_order_service.request_modify(
        shop["customer"],
        order.id,
        items=[RoomRequest(shop["room_type"].id, 1)],
        check_in=CHECK_IN,
        check_out=date(2026, 11, 21),
    )
    with pytest.raises(PermissionDenied):
        wired_order_service.approve_modify_request(shop["customer"], request.id)

    approved = wired_order_service.approve_modify_request(shop["manager"], request.id)
    assert approved.check_out_date == date(2026, 11, 21)
    assert approved.total_cents == 50_000


def test_modify_request_rejected_keeps_original_order(
    shop: dict,
    wired_order_service: OrderService,
    payment_service,
    clock: FakeClock,
) -> None:
    order = _order(shop, wired_order_service, request_no="mod-reject")
    payment_service.pay(payment_service.create_payment(shop["customer"], order.id).pay_no)
    clock.set(datetime(2026, 11, 20, 19, 0))
    request = wired_order_service.request_modify(
        shop["customer"],
        order.id,
        items=[RoomRequest(shop["room_type"].id, 1)],
        check_in=CHECK_IN,
        check_out=date(2026, 11, 21),
    )

    wired_order_service.reject_modify_request(shop["manager"], request.id)

    unchanged = wired_order_service.get_order(shop["customer"], order.id)
    assert unchanged.check_out_date == CHECK_OUT
    assert unchanged.total_cents == 100_000


def test_modify_to_more_expensive_needs_no_approval(
    shop: dict,
    wired_order_service: OrderService,
    payment_service,
    clock: FakeClock,
) -> None:
    order = _order(shop, wired_order_service, request_no="mod-expensive")
    payment_service.pay(payment_service.create_payment(shop["customer"], order.id).pay_no)
    clock.set(datetime(2026, 11, 20, 19, 0))

    modified = wired_order_service.modify_order(
        shop["customer"],
        order.id,
        items=[RoomRequest(shop["twin"].id, 1)],
        check_in=CHECK_IN,
        check_out=CHECK_OUT,
    )

    assert modified.total_cents == 120_000


def test_cancel_deadline_includes_18_00(
    shop: dict, order_service: OrderService, clock: FakeClock
) -> None:
    """REQ-021：18:00 整点起即按截止后处理。"""
    order = _order(shop, order_service, request_no="edge-1800")
    clock.set(datetime(2026, 11, 20, 18, 0))

    with pytest.raises(PermissionDenied):
        order_service.cancel_order(shop["customer"], order.id, "整点取消")


def test_modify_refund_at_18_00_needs_approval(
    shop: dict,
    wired_order_service: OrderService,
    payment_service,
    clock: FakeClock,
) -> None:
    order = _order(shop, wired_order_service, request_no="edge-modify")
    payment_service.pay(payment_service.create_payment(shop["customer"], order.id).pay_no)
    clock.set(datetime(2026, 11, 20, 18, 0))

    with pytest.raises(ConflictError):
        wired_order_service.modify_order(
            shop["customer"],
            order.id,
            items=[RoomRequest(shop["room_type"].id, 1)],
            check_in=CHECK_IN,
            check_out=date(2026, 11, 21),
        )
