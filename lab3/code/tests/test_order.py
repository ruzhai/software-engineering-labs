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
