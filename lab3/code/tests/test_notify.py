"""M10 通知：事件订阅、失败重试与去重。"""

from __future__ import annotations

from datetime import date

import pytest

from hotel.core.clock import FakeClock
from hotel.core.errors import PermissionDenied
from hotel.m05_order.model import OrderStatus
from hotel.m05_order.service import OrderService, RoomRequest
from hotel.m06_payment.service import PaymentService
from hotel.m10_notify.model import NotificationStatus
from hotel.m10_notify.service import InMemoryChannel, NotificationService

CHECK_IN = date(2026, 11, 20)
CHECK_OUT = date(2026, 11, 21)


def _place(shop: dict, order_service: OrderService, request_no: str = "ntf-1"):
    return order_service.create_order(
        shop["customer"],
        store_id=shop["store"].id,
        request_no=request_no,
        items=[RoomRequest(shop["room_type"].id, 1)],
        check_in=CHECK_IN,
        check_out=CHECK_OUT,
    )


def test_payment_confirmation_sends_notification(
    shop: dict,
    wired: dict,
    channel: InMemoryChannel,
) -> None:
    order = _place(shop, wired["order"])
    payment = wired["payment"].create_payment(shop["customer"], order.id)
    wired["payment"].pay(payment.pay_no)

    notifications = wired["notify"].list_for_order(shop["customer"], order.id)

    assert len(notifications) == 1
    assert notifications[0].type == "ORDER_CONFIRMED"
    assert notifications[0].status is NotificationStatus.SENT
    assert order.order_no in channel.sent[0][1]


def test_same_event_not_sent_twice(shop: dict, wired: dict, channel: InMemoryChannel) -> None:
    order = _place(shop, wired["order"], "ntf-dup")
    payment = wired["payment"].create_payment(shop["customer"], order.id)
    wired["payment"].handle_callback(payment.pay_no, "TXN-1", order.total_cents)
    wired["payment"].handle_callback(payment.pay_no, "TXN-1", order.total_cents)

    notifications = wired["notify"].list_for_order(shop["customer"], order.id)

    assert len(notifications) == 1
    assert len(channel.sent) == 1


def test_channel_failure_does_not_block_order(
    shop: dict, wired: dict, channel: InMemoryChannel
) -> None:
    channel.fail = True
    order = _place(shop, wired["order"], "ntf-fail")
    payment = wired["payment"].create_payment(shop["customer"], order.id)

    wired["payment"].pay(payment.pay_no)

    assert wired["order"].get_order(shop["customer"], order.id).status is OrderStatus.CONFIRMED
    notifications = wired["notify"].list_for_order(shop["customer"], order.id)
    assert notifications[0].status is NotificationStatus.FAILED
    assert notifications[0].failure_reason == "通道不可用"


def test_retry_sends_the_failed_notification(
    shop: dict, wired: dict, channel: InMemoryChannel
) -> None:
    channel.fail = True
    order = _place(shop, wired["order"], "ntf-retry")
    payment = wired["payment"].create_payment(shop["customer"], order.id)
    wired["payment"].pay(payment.pay_no)

    channel.fail = False
    assert wired["notify"].retry_failed() == 1

    notifications = wired["notify"].list_for_order(shop["customer"], order.id)
    assert notifications[0].status is NotificationStatus.SENT
    assert len(channel.sent) == 1


def test_gives_up_after_max_retries(shop: dict, wired: dict, channel: InMemoryChannel) -> None:
    channel.fail = True
    order = _place(shop, wired["order"], "ntf-giveup")
    payment = wired["payment"].create_payment(shop["customer"], order.id)
    wired["payment"].pay(payment.pay_no)

    for _ in range(3):
        wired["notify"].retry_failed()

    notifications = wired["notify"].list_for_order(shop["customer"], order.id)
    assert notifications[0].status is NotificationStatus.GIVE_UP


def test_cancel_sends_notification(shop: dict, wired: dict, channel: InMemoryChannel) -> None:
    order = _place(shop, wired["order"], "ntf-cancel")
    wired["order"].cancel_order(shop["customer"], order.id, "行程有变")

    notifications = wired["notify"].list_for_order(shop["customer"], order.id)

    assert [item.type for item in notifications] == ["ORDER_CANCELLED"]
    assert notifications[0].status is NotificationStatus.SENT


def test_expiry_sends_cancelled_notification(shop: dict, wired: dict, clock: FakeClock) -> None:
    order = _place(shop, wired["order"], "ntf-expire")
    wired["payment"].create_payment(shop["customer"], order.id)
    clock.advance(minutes=16)

    wired["payment"].expire_unpaid_orders()

    notifications = wired["notify"].list_for_order(shop["customer"], order.id)
    assert [item.type for item in notifications] == ["ORDER_CANCELLED"]


def test_notification_scope(
    shop: dict, wired: dict, notification_service: NotificationService
) -> None:
    order = _place(shop, wired["order"], "ntf-scope")
    payment = wired["payment"].create_payment(shop["customer"], order.id)
    wired["payment"].pay(payment.pay_no)

    with pytest.raises(PermissionDenied):
        notification_service.list_for_order(shop["area_manager"], order.id)
