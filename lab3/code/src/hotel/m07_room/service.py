"""房态与工单的服务层。

房态只能沿 REQ-005 的允许路径推进。店长对房态只读（REQ-006），
所有房态变更必须用前台账号；房间转维修时同步重算该房型的可售上限（REQ-034）。
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta

from hotel.core.audit import record_audit
from hotel.core.auth import ensure_active
from hotel.core.clock import Clock
from hotel.core.db import Database, UnitOfWork
from hotel.core.errors import ConflictError, NotFound, PermissionDenied, ValidationError
from hotel.core.ids import new_id
from hotel.m01_account.model import Role, Session
from hotel.m02_store.model import RoomStatus
from hotel.m02_store.repository import StoreRepository
from hotel.m04_inventory.service import InventoryService
from hotel.m05_order.model import Order, OrderStatus
from hotel.m05_order.repository import OrderRepository
from hotel.m07_room.model import (
    WorkOrder,
    WorkOrderStatus,
    WorkOrderType,
    can_change_room,
)
from hotel.m07_room.repository import RoomStateRepository

REPAIR_HORIZON_DAYS = 30
NO_SHOW_CUTOFF_HOUR = 12


class RoomService:
    def __init__(
        self, database: Database, clock: Clock, inventory_service: InventoryService
    ) -> None:
        self._db = database
        self._clock = clock
        self._inventory = inventory_service

    # ---------- 排房与入住退房 ----------

    def assign_room(self, actor: Session, order_id: str, room_id: str) -> Order:
        self._require_front_desk(actor)
        with UnitOfWork(self._db) as conn:
            repo = OrderRepository(conn)
            order = repo.get_order(order_id)
            if order is None:
                raise NotFound("订单不存在", field="order_id")
            if order.store_id != actor.store_id:
                raise PermissionDenied("只能为本店订单排房")
            if order.status is not OrderStatus.CONFIRMED:
                raise ConflictError("只有已确认订单可以排房", field="status")

            room = StoreRepository(conn).get_room(room_id)
            if room is None:
                raise NotFound("房间不存在", field="room_id")
            room_type = StoreRepository(conn).get_room_type(room.room_type_id)
            if room_type is None or room_type.store_id != actor.store_id:
                raise PermissionDenied("只能排本店的房间")
            if room.status is not RoomStatus.FREE:
                raise ConflictError(f"房间当前状态为 {room.status.value}，不能排房", field="room")
            order_types = {item.room_type_id for item in order.items}
            if order_types != {room.room_type_id}:
                raise ValidationError("房间房型与订单不一致", field="room_id")
            state = RoomStateRepository(conn)
            if state.room_occupied_by_other(room_id, order_id):
                raise ConflictError("该房间已被其他订单占用", field="room_id")

            state.set_room_status(room_id, RoomStatus.RESERVED.value)
            for night in order_nights(order):
                state.add_occupancy(order_id, room_id, night)
            repo.set_room(order_id, room_id)
            record_audit(
                conn,
                operator_id=actor.user_id,
                operator_role=actor.role.value,
                action="ROOM_ASSIGNED",
                object_type="order",
                object_id=order_id,
                reason=f"房号 {room.room_no}",
                after_value=RoomStatus.RESERVED.value,
                moment=self._clock.now(),
            )
        return self._load_order(order_id)

    def check_in(self, actor: Session, order_id: str) -> Order:
        self._require_front_desk(actor)
        with UnitOfWork(self._db) as conn:
            repo = OrderRepository(conn)
            order = repo.get_order(order_id)
            if order is None:
                raise NotFound("订单不存在", field="order_id")
            if order.store_id != actor.store_id:
                raise PermissionDenied("只能为本店订单办理入住")
            if order.status is OrderStatus.NO_SHOW:
                cutoff = datetime.combine(
                    order.check_in_date + timedelta(days=1), time(NO_SHOW_CUTOFF_HOUR, 0)
                )
                if self._clock.now() >= cutoff:
                    raise ConflictError("已超过次日 12:00，不能再办理入住", field="status")
            elif order.status is not OrderStatus.CONFIRMED:
                raise ConflictError("只有已确认或未到店的订单可以入住", field="status")

            state = RoomStateRepository(conn)
            rooms = self._assigned_rooms(conn, order_id)
            required = self._required_rooms(order)
            if len(rooms) < required:
                raise ConflictError("请先为订单排房", field="room")
            for room_id in rooms:
                room = StoreRepository(conn).get_room(room_id)
                if room is None or room.status is not RoomStatus.RESERVED:
                    raise ConflictError("房间不在已预定状态，无法入住", field="room")
                state.set_room_status(room_id, RoomStatus.OCCUPIED.value)

            repo.update_status(order_id, OrderStatus.CHECKED_IN, checked_in_at=self._clock.now())
            record_audit(
                conn,
                operator_id=actor.user_id,
                operator_role=actor.role.value,
                action="ORDER_CHECKED_IN",
                object_type="order",
                object_id=order_id,
                before_value=order.status.value,
                after_value=OrderStatus.CHECKED_IN.value,
                moment=self._clock.now(),
            )
        return self._load_order(order_id)

    def check_out(self, actor: Session, order_id: str) -> Order:
        self._require_front_desk(actor)
        with UnitOfWork(self._db) as conn:
            repo = OrderRepository(conn)
            order = repo.get_order(order_id)
            if order is None:
                raise NotFound("订单不存在", field="order_id")
            if order.store_id != actor.store_id:
                raise PermissionDenied("只能为本店订单办理退房")
            if order.status is not OrderStatus.CHECKED_IN:
                raise ConflictError("只有已入住的订单可以退房", field="status")

            state = RoomStateRepository(conn)
            for room_id in self._assigned_rooms(conn, order_id):
                room = StoreRepository(conn).get_room(room_id)
                if room is None or room.status is not RoomStatus.OCCUPIED:
                    raise ConflictError("房间不在已入住状态", field="room")
                # 退房后房间要落到「需打扫」，两步在同一事务内完成（REQ-003、REQ-005）。
                state.set_room_status(room_id, RoomStatus.CHECKED_OUT.value)
                state.set_room_status(room_id, RoomStatus.CLEANING.value)

            repo.update_status(order_id, OrderStatus.CHECKED_OUT, checked_out_at=self._clock.now())
            record_audit(
                conn,
                operator_id=actor.user_id,
                operator_role=actor.role.value,
                action="ORDER_CHECKED_OUT",
                object_type="order",
                object_id=order_id,
                before_value=order.status.value,
                after_value=OrderStatus.CHECKED_OUT.value,
                moment=self._clock.now(),
            )
        return self._load_order(order_id)

    def assigned_rooms(self, order_id: str) -> list[str]:
        with UnitOfWork(self._db) as conn:
            return self._assigned_rooms(conn, order_id)

    # ---------- 房态推进 ----------

    def change_room_status(
        self,
        actor: Session,
        room_id: str,
        target: RoomStatus,
        repair_until: date | None = None,
    ) -> None:
        self._require_front_desk(actor)
        with UnitOfWork(self._db) as conn:
            room = StoreRepository(conn).get_room(room_id)
            if room is None:
                raise NotFound("房间不存在", field="room_id")
            room_type = StoreRepository(conn).get_room_type(room.room_type_id)
            if room_type is None or room_type.store_id != actor.store_id:
                raise PermissionDenied("只能操作本店房间")
            if not can_change_room(room.status, target):
                raise ConflictError(
                    f"房间状态不能从 {room.status.value} 变为 {target.value}", field="status"
                )
            if target is RoomStatus.REPAIRING and repair_until is None:
                raise ValidationError("转入维修需要登记预计修复日期", field="repair_until")
            RoomStateRepository(conn).set_room_status(
                room_id,
                target.value,
                repair_until if target is RoomStatus.REPAIRING else None,
            )
            if target in (RoomStatus.REPAIRING, RoomStatus.FREE):
                self._recompute_from(conn, room.room_type_id, self._clock.today())
            record_audit(
                conn,
                operator_id=actor.user_id,
                operator_role=actor.role.value,
                action="ROOM_STATUS_CHANGED",
                object_type="room",
                object_id=room_id,
                before_value=room.status.value,
                after_value=target.value,
                moment=self._clock.now(),
            )

    # ---------- 工单 ----------

    def submit_work_order(
        self,
        actor: Session,
        *,
        room_id: str,
        work_type: WorkOrderType,
        reason: str,
        involved_date: date,
    ) -> WorkOrder:
        if actor.role is not Role.STORE_MANAGER:
            raise PermissionDenied("只有店长能提交工单")
        if not reason.strip():
            raise ValidationError("请填写工单原因", field="reason")
        with UnitOfWork(self._db) as conn:
            room = StoreRepository(conn).get_room(room_id)
            if room is None:
                raise NotFound("房间不存在", field="room_id")
            room_type = StoreRepository(conn).get_room_type(room.room_type_id)
            if room_type is None or room_type.store_id != actor.store_id:
                raise PermissionDenied("只能为本店房间提交工单")
            state = RoomStateRepository(conn)
            if state.open_work_order_of_room(room_id) is not None:
                raise ConflictError("该房间已有未关闭的工单", field="room_id")
            work_order = WorkOrder(
                id=new_id("wo"),
                room_id=room_id,
                type=work_type,
                reason=reason.strip(),
                involved_date=involved_date,
                status=WorkOrderStatus.OPEN,
                submitter=actor.user_id,
                executor=None,
                created_at=self._clock.now(),
            )
            state.insert_work_order(work_order)
        return work_order

    def execute_work_order(
        self, actor: Session, work_order_id: str, repair_until: date
    ) -> WorkOrder:
        self._require_front_desk(actor)
        if repair_until < self._clock.today():
            raise ValidationError("预计修复日期不能早于今天", field="repair_until")
        with UnitOfWork(self._db) as conn:
            state = RoomStateRepository(conn)
            work_order = state.get_work_order(work_order_id)
            if work_order is None:
                raise NotFound("工单不存在", field="work_order_id")
            if work_order.status is not WorkOrderStatus.OPEN:
                raise ConflictError("该工单已处理过了", field="work_order_id")
            room = StoreRepository(conn).get_room(work_order.room_id)
            if room is None:
                raise NotFound("房间不存在", field="room_id")
            room_type = StoreRepository(conn).get_room_type(room.room_type_id)
            if room_type is None or room_type.store_id != actor.store_id:
                raise PermissionDenied("只能执行本店工单")
            if not can_change_room(room.status, RoomStatus.REPAIRING):
                raise ConflictError(
                    f"房间当前状态为 {room.status.value}，不能转入维修", field="status"
                )
            state.set_room_status(work_order.room_id, RoomStatus.REPAIRING.value, repair_until)
            state.close_work_order(work_order_id, WorkOrderStatus.DONE, actor.user_id)
            self._recompute_between(conn, room.room_type_id, work_order.involved_date, repair_until)
            record_audit(
                conn,
                operator_id=actor.user_id,
                operator_role=actor.role.value,
                action="WORK_ORDER_EXECUTED",
                object_type="work_order",
                object_id=work_order_id,
                reason=work_order.reason,
                after_value=RoomStatus.REPAIRING.value,
                moment=self._clock.now(),
            )
            updated = state.get_work_order(work_order_id)
        assert updated is not None
        return updated

    def reject_work_order(self, actor: Session, work_order_id: str, note: str) -> WorkOrder:
        self._require_front_desk(actor)
        if not note.strip():
            raise ValidationError("拒绝工单需要注明原因", field="note")
        with UnitOfWork(self._db) as conn:
            state = RoomStateRepository(conn)
            work_order = state.get_work_order(work_order_id)
            if work_order is None:
                raise NotFound("工单不存在", field="work_order_id")
            if work_order.status is not WorkOrderStatus.OPEN:
                raise ConflictError("该工单已处理过了", field="work_order_id")
            state.close_work_order(work_order_id, WorkOrderStatus.REJECTED, actor.user_id)
            record_audit(
                conn,
                operator_id=actor.user_id,
                operator_role=actor.role.value,
                action="WORK_ORDER_REJECTED",
                object_type="work_order",
                object_id=work_order_id,
                reason=note.strip(),
                moment=self._clock.now(),
            )
            updated = state.get_work_order(work_order_id)
        assert updated is not None
        return updated

    def list_open_work_orders(self, actor: Session, store_id: str) -> list[WorkOrder]:
        if actor.role not in (Role.FRONT_DESK, Role.STORE_MANAGER) or actor.store_id != store_id:
            raise PermissionDenied("只能查看本店工单")
        with UnitOfWork(self._db) as conn:
            return RoomStateRepository(conn).list_open_work_orders(store_id)

    # ---------- 内部 ----------

    def _recompute_from(self, conn: sqlite3.Connection, room_type_id: str, start: date) -> None:
        self._recompute_between(
            conn, room_type_id, start, start + timedelta(days=REPAIR_HORIZON_DAYS)
        )

    def _recompute_between(
        self, conn: sqlite3.Connection, room_type_id: str, start: date, end: date
    ) -> None:
        day = start
        while day <= end:
            self._inventory.recompute(conn, room_type_id, day)
            day += timedelta(days=1)

    @staticmethod
    def _assigned_rooms(conn: sqlite3.Connection, order_id: str) -> list[str]:
        rows = conn.execute(
            "SELECT DISTINCT room_id FROM occupancy WHERE order_id = ?", (order_id,)
        ).fetchall()
        return [row["room_id"] for row in rows]

    @staticmethod
    def _required_rooms(order: Order) -> int:
        return sum(item.qty for item in order.items if item.stay_date == order.check_in_date)

    def _load_order(self, order_id: str) -> Order:
        with UnitOfWork(self._db) as conn:
            order = OrderRepository(conn).get_order(order_id)
        if order is None:
            raise NotFound("订单不存在", field="order_id")
        return order

    def _require_front_desk(self, actor: Session) -> None:
        if actor.role is not Role.FRONT_DESK:
            raise PermissionDenied("只有前台能操作房态")
        with UnitOfWork(self._db) as conn:
            ensure_active(conn, actor)


def order_nights(order: Order) -> list[date]:
    days = (order.check_out_date - order.check_in_date).days
    return [date.fromordinal(order.check_in_date.toordinal() + offset) for offset in range(days)]
