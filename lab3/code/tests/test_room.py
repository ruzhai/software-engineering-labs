"""M7 房态状态机、排房与工单。"""

from __future__ import annotations

from datetime import date

import pytest

from hotel.core.db import Database
from hotel.core.errors import ConflictError, PermissionDenied, ValidationError
from hotel.m02_store.model import RoomStatus
from hotel.m02_store.service import StoreService
from hotel.m04_inventory.service import InventoryService
from hotel.m05_order.model import OrderStatus
from hotel.m05_order.service import OrderService, RoomRequest
from hotel.m06_payment.service import PaymentService
from hotel.m07_room.model import WorkOrderStatus, WorkOrderType, can_change_room
from hotel.m07_room.service import RoomService

CHECK_IN = date(2026, 11, 20)
CHECK_OUT = date(2026, 11, 21)


def _confirmed_order(
    shop: dict, order_service: OrderService, payment_service: PaymentService, request_no: str
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
    return order


def _room_id(store_service: StoreService, room_type_id: str, index: int = 0) -> str:
    return store_service.list_rooms(room_type_id)[index].id


def test_assign_room_then_check_in_and_out(
    shop: dict,
    store_service: StoreService,
    order_service: OrderService,
    payment_service: PaymentService,
    room_service: RoomService,
) -> None:
    order = _confirmed_order(shop, order_service, payment_service, "room-1")
    room_id = _room_id(store_service, shop["room_type"].id)

    assigned = room_service.assign_room(shop["front"], order.id, room_id)
    assert assigned.room_id == room_id
    assert store_service.list_rooms(shop["room_type"].id)[0].status is RoomStatus.RESERVED

    checked_in = room_service.check_in(shop["front"], order.id)
    assert checked_in.status is OrderStatus.CHECKED_IN
    assert store_service.list_rooms(shop["room_type"].id)[0].status is RoomStatus.OCCUPIED

    checked_out = room_service.check_out(shop["front"], order.id)
    assert checked_out.status is OrderStatus.CHECKED_OUT
    assert store_service.list_rooms(shop["room_type"].id)[0].status is RoomStatus.CLEANING


def test_check_in_requires_a_room(
    shop: dict,
    order_service: OrderService,
    payment_service: PaymentService,
    room_service: RoomService,
) -> None:
    order = _confirmed_order(shop, order_service, payment_service, "room-noroom")

    with pytest.raises(ConflictError):
        room_service.check_in(shop["front"], order.id)


def test_repairing_room_cannot_be_assigned(
    shop: dict,
    store_service: StoreService,
    order_service: OrderService,
    payment_service: PaymentService,
    room_service: RoomService,
) -> None:
    order = _confirmed_order(shop, order_service, payment_service, "room-repair")
    room_id = _room_id(store_service, shop["room_type"].id)
    room_service.change_room_status(
        shop["front"], room_id, RoomStatus.REPAIRING, repair_until=date(2026, 12, 1)
    )

    with pytest.raises(ConflictError):
        room_service.assign_room(shop["front"], order.id, room_id)


def test_illegal_room_transitions_are_rejected(
    shop: dict, store_service: StoreService, room_service: RoomService
) -> None:
    room_id = _room_id(store_service, shop["room_type"].id)

    assert can_change_room(RoomStatus.FREE, RoomStatus.RESERVED)
    assert not can_change_room(RoomStatus.FREE, RoomStatus.OCCUPIED)
    assert not can_change_room(RoomStatus.OCCUPIED, RoomStatus.FREE)
    assert not can_change_room(RoomStatus.REPAIRING, RoomStatus.OCCUPIED)

    with pytest.raises(ConflictError):
        room_service.change_room_status(shop["front"], room_id, RoomStatus.OCCUPIED)


def test_manager_cannot_change_room_status(
    shop: dict, store_service: StoreService, room_service: RoomService
) -> None:
    room_id = _room_id(store_service, shop["room_type"].id)

    with pytest.raises(PermissionDenied):
        room_service.change_room_status(shop["manager"], room_id, RoomStatus.REPAIRING)


def test_work_order_marks_room_repairing_and_lowers_limit(
    shop: dict,
    store_service: StoreService,
    room_service: RoomService,
    inventory_service: InventoryService,
) -> None:
    room_id = _room_id(store_service, shop["room_type"].id)
    before = inventory_service.query(shop["room_type"].id, CHECK_IN).online_limit

    work_order = room_service.submit_work_order(
        shop["manager"],
        room_id=room_id,
        work_type=WorkOrderType.REPAIR,
        reason="空调故障",
        involved_date=CHECK_IN,
    )
    done = room_service.execute_work_order(
        shop["front"], work_order.id, repair_until=date(2026, 11, 25)
    )

    assert done.status is WorkOrderStatus.DONE
    after = inventory_service.query(shop["room_type"].id, CHECK_IN).online_limit
    assert after == before - 1


def test_duplicate_open_work_order_rejected(
    shop: dict, store_service: StoreService, room_service: RoomService
) -> None:
    room_id = _room_id(store_service, shop["room_type"].id)
    room_service.submit_work_order(
        shop["manager"],
        room_id=room_id,
        work_type=WorkOrderType.REPAIR,
        reason="第一次",
        involved_date=CHECK_IN,
    )

    with pytest.raises(ConflictError):
        room_service.submit_work_order(
            shop["manager"],
            room_id=room_id,
            work_type=WorkOrderType.REPAIR,
            reason="第二次",
            involved_date=CHECK_IN,
        )


def test_reject_work_order_keeps_room_state(
    shop: dict, store_service: StoreService, room_service: RoomService
) -> None:
    room_id = _room_id(store_service, shop["room_type"].id)
    work_order = room_service.submit_work_order(
        shop["manager"],
        room_id=room_id,
        work_type=WorkOrderType.REPAIR,
        reason="门锁松动",
        involved_date=CHECK_IN,
    )

    rejected = room_service.reject_work_order(shop["front"], work_order.id, "现场检查正常")

    assert rejected.status is WorkOrderStatus.REJECTED
    assert store_service.list_rooms(shop["room_type"].id)[0].status is RoomStatus.FREE


def test_work_order_input_validation(
    shop: dict, store_service: StoreService, room_service: RoomService
) -> None:
    room_id = _room_id(store_service, shop["room_type"].id)

    with pytest.raises(ValidationError):
        room_service.submit_work_order(
            shop["manager"],
            room_id=room_id,
            work_type=WorkOrderType.REPAIR,
            reason="   ",
            involved_date=CHECK_IN,
        )
    with pytest.raises(PermissionDenied):
        room_service.submit_work_order(
            shop["front"],
            room_id=room_id,
            work_type=WorkOrderType.REPAIR,
            reason="前台不能提交",
            involved_date=CHECK_IN,
        )


def test_assigned_rooms_are_tracked(
    shop: dict,
    store_service: StoreService,
    order_service: OrderService,
    payment_service: PaymentService,
    room_service: RoomService,
    database: Database,
) -> None:
    order = _confirmed_order(shop, order_service, payment_service, "room-track")
    room_id = _room_id(store_service, shop["room_type"].id)
    room_service.assign_room(shop["front"], order.id, room_id)

    assert room_service.assigned_rooms(order.id) == [room_id]
