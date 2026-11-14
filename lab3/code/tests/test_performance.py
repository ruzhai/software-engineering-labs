"""M8 评价与绩效。"""

from __future__ import annotations

from datetime import date

import pytest

from hotel.core.errors import ConflictError, PermissionDenied, ValidationError
from hotel.m02_store.service import StoreService
from hotel.m05_order.service import OrderService, RoomRequest
from hotel.m06_payment.service import PaymentService
from hotel.m07_room.service import RoomService
from hotel.m08_performance.model import ReviewStatus
from hotel.m08_performance.service import PerformanceService

CHECK_IN = date(2026, 11, 20)
CHECK_OUT = date(2026, 11, 21)


def _checked_out_order(
    shop: dict,
    store_service: StoreService,
    order_service: OrderService,
    payment_service: PaymentService,
    room_service: RoomService,
    request_no: str,
):
    order = order_service.create_order(
        shop["customer"],
        store_id=shop["store"].id,
        request_no=request_no,
        items=[RoomRequest(shop["room_type"].id, 1)],
        check_in=CHECK_IN,
        check_out=CHECK_OUT,
    )
    payment_service.pay(payment_service.create_payment(shop["customer"], order.id).pay_no)
    room_id = store_service.list_rooms(shop["room_type"].id)[0].id
    room_service.assign_room(shop["front"], order.id, room_id)
    room_service.check_in(shop["front"], order.id)
    return room_service.check_out(shop["front"], order.id)


def test_review_can_only_be_submitted_once_after_checkout(
    shop: dict,
    store_service: StoreService,
    order_service: OrderService,
    payment_service: PaymentService,
    room_service: RoomService,
    performance_service: PerformanceService,
) -> None:
    order = _checked_out_order(
        shop, store_service, order_service, payment_service, room_service, "rev-1"
    )

    review = performance_service.submit_review(
        shop["customer"], order_id=order.id, score=5, content="房间干净"
    )
    assert review.score == 5
    assert review.status is ReviewStatus.PUBLISHED

    with pytest.raises(ConflictError):
        performance_service.submit_review(
            shop["customer"], order_id=order.id, score=4, content="再评一次"
        )


def test_review_requires_checked_out_order(
    shop: dict,
    order_service: OrderService,
    payment_service: PaymentService,
    performance_service: PerformanceService,
) -> None:
    order = order_service.create_order(
        shop["customer"],
        store_id=shop["store"].id,
        request_no="rev-early",
        items=[RoomRequest(shop["room_type"].id, 1)],
        check_in=CHECK_IN,
        check_out=CHECK_OUT,
    )
    payment_service.pay(payment_service.create_payment(shop["customer"], order.id).pay_no)

    with pytest.raises(ConflictError):
        performance_service.submit_review(
            shop["customer"], order_id=order.id, score=5, content="太早了"
        )


def test_review_input_validation(
    shop: dict,
    store_service: StoreService,
    order_service: OrderService,
    payment_service: PaymentService,
    room_service: RoomService,
    performance_service: PerformanceService,
) -> None:
    order = _checked_out_order(
        shop, store_service, order_service, payment_service, room_service, "rev-bad"
    )

    with pytest.raises(ValidationError):
        performance_service.submit_review(
            shop["customer"], order_id=order.id, score=0, content="零分"
        )
    with pytest.raises(ValidationError):
        performance_service.submit_review(
            shop["customer"], order_id=order.id, score=6, content="超范围"
        )
    with pytest.raises(ValidationError):
        performance_service.submit_review(
            shop["customer"], order_id=order.id, score=4, content="   "
        )
    with pytest.raises(PermissionDenied):
        performance_service.submit_review(
            shop["front"], order_id=order.id, score=4, content="前台不能评"
        )


def test_moderate_review_hides_it(
    shop: dict,
    store_service: StoreService,
    order_service: OrderService,
    payment_service: PaymentService,
    room_service: RoomService,
    performance_service: PerformanceService,
) -> None:
    order = _checked_out_order(
        shop, store_service, order_service, payment_service, room_service, "rev-mod"
    )
    review = performance_service.submit_review(
        shop["customer"], order_id=order.id, score=3, content="一般"
    )

    hidden = performance_service.moderate_review(shop["manager"], review.id, publish=False)
    assert hidden.status is ReviewStatus.HIDDEN

    with pytest.raises(PermissionDenied):
        performance_service.moderate_review(shop["customer"], review.id, publish=True)


def test_performance_aggregation(
    shop: dict,
    store_service: StoreService,
    order_service: OrderService,
    payment_service: PaymentService,
    room_service: RoomService,
    performance_service: PerformanceService,
) -> None:
    order = _checked_out_order(
        shop, store_service, order_service, payment_service, room_service, "perf-1"
    )
    performance_service.submit_review(shop["customer"], order_id=order.id, score=5, content="很好")

    performance = performance_service.aggregate_performance(
        shop["manager"],
        store_id=shop["store"].id,
        start=date(2026, 11, 1),
        end=date(2026, 11, 30),
        period="2026-11",
    )

    assert performance.order_count == 1
    assert performance.avg_score == 5.0
    assert 0 <= performance.occupancy_rate <= 1
