"""预订与订单的服务层。

下单、改期、取消都在一个事务里完成库存的扣减或释放：
任一一晚扣减失败整单回滚，不会出现「订了一半」的订单（REQ-013、REQ-032）。
"""

from __future__ import annotations

import random
import sqlite3
import threading
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

from hotel.core.audit import record_audit
from hotel.core.auth import ensure_active
from hotel.core.clock import Clock
from hotel.core.db import Database, UnitOfWork
from hotel.core.errors import ConflictError, NotFound, PermissionDenied, ValidationError
from hotel.core.events import make_order_event
from hotel.core.ids import new_id
from hotel.core.locks import acquire_all
from hotel.m01_account.model import Role, Session
from hotel.m02_store.model import StoreStatus
from hotel.m02_store.repository import StoreRepository
from hotel.m03_pricing.repository import PricingRepository
from hotel.m04_inventory.service import InventoryService
from hotel.m05_order.model import (
    CancelRequest,
    CancelRequestStatus,
    ModifyRequest,
    ModifyRequestStatus,
    Order,
    OrderItem,
    OrderStatus,
    can_transition,
)
from hotel.m05_order.repository import OrderRepository

CANCEL_DEADLINE_HOUR = 18
PAY_TIMEOUT_MINUTES = 15


@dataclass(frozen=True)
class RoomRequest:
    room_type_id: str
    qty: int


class OrderService:
    def __init__(
        self, database: Database, clock: Clock, inventory_service: InventoryService
    ) -> None:
        self._db = database
        self._clock = clock
        self._inventory = inventory_service
        self._payment = None
        self._bus = None

    def attach_payment(self, payment_service) -> None:
        """支付模块建好后注入，取消订单时用它发起退款。"""
        self._payment = payment_service

    def attach_events(self, bus) -> None:
        self._bus = bus

    # ---------- 下单 ----------

    def create_order(
        self,
        actor: Session,
        *,
        store_id: str,
        request_no: str,
        items: list[RoomRequest],
        check_in: date,
        check_out: date,
    ) -> Order:
        if actor.role is not Role.CUSTOMER:
            raise PermissionDenied("只有顾客能自助下单")
        self._validate_stay(check_in, check_out)
        if not request_no.strip():
            raise ValidationError("请求号不能为空", field="request_no")
        if not items:
            raise ValidationError("至少选择一个房型", field="items")
        merged = self._merge(items)

        try:
            # 价格锁在事务之前拿：与改价保持同一加锁顺序，避免互相等待。
            with acquire_all(self._price_locks(merged, check_in, check_out), self._db.lock_timeout):
                with UnitOfWork(self._db) as conn:
                    ensure_active(conn, actor)
                    repo = OrderRepository(conn)
                    if repo.request_seen(request_no):
                        existing = repo.find_order_by_request_no(request_no)
                        if existing is not None:
                            return existing
                        raise ConflictError("该请求号已处理过", field="request_no")
                    repo.record_request(request_no, self._clock.now())

                    store = StoreRepository(conn).get_store(store_id)
                    if store is None:
                        raise NotFound("门店不存在", field="store_id")
                    if store.status is not StoreStatus.OPEN:
                        raise ConflictError("门店已停业，暂不接受新订单")

                    built = self._build_items(conn, store_id, merged, check_in, check_out)
                    self._reserve_all(conn, built)

                    now = self._clock.now()
                    order = Order(
                        id=new_id("order"),
                        order_no=self._make_order_no(now),
                        request_no=request_no,
                        customer_id=actor.user_id,
                        store_id=store_id,
                        status=OrderStatus.PENDING_PAYMENT,
                        total_cents=sum(item.subtotal_cents for item in built),
                        pay_deadline=now + timedelta(minutes=PAY_TIMEOUT_MINUTES),
                        check_in_date=check_in,
                        check_out_date=check_out,
                        room_id=None,
                        created_at=now,
                    )
                    repo.insert_order(order)
                    for item in built:
                        repo.insert_item(replace(item, order_id=order.id))
        except sqlite3.IntegrityError as exc:
            # 并发提交同一请求号：另一个线程先落单，这里返回那一单。
            with UnitOfWork(self._db) as conn:
                existing = OrderRepository(conn).find_order_by_request_no(request_no)
            if existing is not None:
                return existing
            raise ConflictError("订单提交冲突，请重试", field="request_no") from exc

        return self.get_order(actor, order.id)

    def create_walk_in_order(
        self,
        actor: Session,
        *,
        store_id: str,
        customer_id: str,
        request_no: str,
        items: list[RoomRequest],
        check_in: date,
        check_out: date,
    ) -> Order:
        """前台开单：从线下保留额度扣减，不占用线上库存（REQ-033）。

        线下开单当场收款，所以订单直接落在已确认，不经过支付。
        """
        if actor.role is not Role.FRONT_DESK or actor.store_id != store_id:
            raise PermissionDenied("只有本店前台能开单")
        self._validate_stay(check_in, check_out)
        if not request_no.strip():
            raise ValidationError("请求号不能为空", field="request_no")
        if not items:
            raise ValidationError("至少选择一个房型", field="items")
        merged = self._merge(items)

        with acquire_all(self._price_locks(merged, check_in, check_out), self._db.lock_timeout):
            with UnitOfWork(self._db) as conn:
                ensure_active(conn, actor)
                repo = OrderRepository(conn)
                if repo.request_seen(request_no):
                    existing = repo.find_order_by_request_no(request_no)
                    if existing is not None:
                        return existing
                    raise ConflictError("该请求号已处理过", field="request_no")
                repo.record_request(request_no, self._clock.now())

                store = StoreRepository(conn).get_store(store_id)
                if store is None:
                    raise NotFound("门店不存在", field="store_id")
                if store.status is not StoreStatus.OPEN:
                    raise ConflictError("门店已停业，暂不接受新订单")

                built = self._build_items(conn, store_id, merged, check_in, check_out)
                for item in built:
                    if not self._inventory.reserve_offline(
                        conn, item.room_type_id, item.stay_date, item.qty
                    ):
                        raise ConflictError(
                            f"{item.stay_date} 线下保留额度不足，请改为线上售卖", field="items"
                        )

                now = self._clock.now()
                order = Order(
                    id=new_id("order"),
                    order_no=self._make_order_no(now),
                    request_no=request_no,
                    customer_id=customer_id,
                    store_id=store_id,
                    status=OrderStatus.CONFIRMED,
                    total_cents=sum(item.subtotal_cents for item in built),
                    pay_deadline=now,
                    check_in_date=check_in,
                    check_out_date=check_out,
                    room_id=None,
                    created_at=now,
                )
                repo.insert_order(order)
                for item in built:
                    repo.insert_item(replace(item, order_id=order.id))
        return self.get_order(actor, order.id)

    # ---------- 查询 ----------

    def get_order(self, actor: Session, order_id: str) -> Order:
        with UnitOfWork(self._db) as conn:
            order = OrderRepository(conn).get_order(order_id)
            if order is None:
                raise NotFound("订单不存在", field="order_id")
            self._check_scope(conn, actor, order)
        return order

    def list_my_orders(self, actor: Session) -> list[Order]:
        if actor.role is not Role.CUSTOMER:
            raise PermissionDenied("只有顾客能查看自己的订单")
        with UnitOfWork(self._db) as conn:
            ensure_active(conn, actor)
            return OrderRepository(conn).list_by_customer(actor.user_id)

    def list_store_orders(self, actor: Session, store_id: str) -> list[Order]:
        if actor.role not in (Role.FRONT_DESK, Role.STORE_MANAGER) or actor.store_id != store_id:
            raise PermissionDenied("只能查看本店订单")
        with UnitOfWork(self._db) as conn:
            ensure_active(conn, actor)
            return OrderRepository(conn).list_by_store(store_id)

    # ---------- 取消 ----------

    def cancel_order(self, actor: Session, order_id: str, reason: str = "") -> Order:
        with UnitOfWork(self._db) as conn:
            repo = OrderRepository(conn)
            order = repo.get_order(order_id)
            if order is None:
                raise NotFound("订单不存在", field="order_id")
            self._check_scope(conn, actor, order)
            if order.status not in (
                OrderStatus.PENDING_PAYMENT,
                OrderStatus.CONFIRMED,
                OrderStatus.NO_SHOW,
            ):
                raise ConflictError("当前状态下不能取消", field="status")
            if self._clock.now() >= self._cancel_deadline(order):
                if actor.role is Role.CUSTOMER:
                    raise PermissionDenied("已过自助取消时间，请联系前台处理")
                if actor.role is Role.FRONT_DESK:
                    raise ConflictError("18:00 后取消需要提交申请并由店长审批", field="status")

            self._release_all(conn, order.items)
            repo.update_status(order_id, OrderStatus.CANCELLED)
            record_audit(
                conn,
                operator_id=actor.user_id,
                operator_role=actor.role.value,
                action="ORDER_CANCELLED",
                object_type="order",
                object_id=order_id,
                reason=reason,
                before_value=order.status.value,
                after_value=OrderStatus.CANCELLED.value,
                moment=self._clock.now(),
            )
            # REQ-021：未到店订单取消不产生退款。
            if self._payment is not None and order.status is not OrderStatus.NO_SHOW:
                self._payment.refund_for_cancelled_order(conn, order)
            event = make_order_event(conn, "ORDER_CANCELLED", order, self._clock.now())
        if self._bus is not None:
            self._bus.publish(event)
        return self.get_order(actor, order_id)

    def request_cancel(self, actor: Session, order_id: str, reason: str) -> CancelRequest:
        if actor.role is not Role.FRONT_DESK:
            raise PermissionDenied("只有前台能代顾客提交取消申请")
        if not reason.strip():
            raise ValidationError("请填写取消原因", field="reason")
        with UnitOfWork(self._db) as conn:
            repo = OrderRepository(conn)
            order = repo.get_order(order_id)
            if order is None:
                raise NotFound("订单不存在", field="order_id")
            self._check_scope(conn, actor, order)
            if order.status not in (
                OrderStatus.PENDING_PAYMENT,
                OrderStatus.CONFIRMED,
                OrderStatus.NO_SHOW,
            ):
                raise ConflictError("当前状态下不能取消", field="status")
            if repo.pending_cancel_request(order_id) is not None:
                raise ConflictError("该订单已有待审批的取消申请", field="order_id")
            request = CancelRequest(
                id=new_id("cr"),
                order_id=order_id,
                reason=reason.strip(),
                applicant=actor.user_id,
                approver=None,
                status=CancelRequestStatus.PENDING,
                created_at=self._clock.now(),
            )
            repo.insert_cancel_request(request)
        return request

    def approve_cancel_request(self, actor: Session, request_id: str) -> Order:
        if actor.role is not Role.STORE_MANAGER:
            raise PermissionDenied("只有店长能审批取消申请")
        with UnitOfWork(self._db) as conn:
            repo = OrderRepository(conn)
            request = repo.get_cancel_request(request_id)
            if request is None:
                raise NotFound("取消申请不存在", field="request_id")
            order = repo.get_order(request.order_id)
            if order is None:
                raise NotFound("订单不存在", field="order_id")
            if order.store_id != actor.store_id:
                raise PermissionDenied("只能审批本店的取消申请")
            if request.status is not CancelRequestStatus.PENDING:
                raise ConflictError("该申请已处理过了", field="request_id")
            if order.status not in (
                OrderStatus.PENDING_PAYMENT,
                OrderStatus.CONFIRMED,
                OrderStatus.NO_SHOW,
            ):
                raise ConflictError("当前状态下不能取消", field="status")
            self._release_all(conn, order.items)
            repo.update_status(order.id, OrderStatus.CANCELLED)
            repo.set_cancel_request_status(request_id, CancelRequestStatus.APPROVED, actor.user_id)
            record_audit(
                conn,
                operator_id=actor.user_id,
                operator_role=actor.role.value,
                action="CANCEL_REQUEST_APPROVED",
                object_type="order",
                object_id=order.id,
                reason=request.reason,
                before_value=order.status.value,
                after_value=OrderStatus.CANCELLED.value,
                moment=self._clock.now(),
            )
            # REQ-021：未到店订单取消不产生退款。
            if self._payment is not None and order.status is not OrderStatus.NO_SHOW:
                self._payment.refund_for_cancelled_order(conn, order)
            event = make_order_event(conn, "ORDER_CANCELLED", order, self._clock.now())
        if self._bus is not None:
            self._bus.publish(event)
        return self.get_order(actor, order.id)

    def reject_cancel_request(self, actor: Session, request_id: str) -> None:
        if actor.role is not Role.STORE_MANAGER:
            raise PermissionDenied("只有店长能审批取消申请")
        with UnitOfWork(self._db) as conn:
            repo = OrderRepository(conn)
            request = repo.get_cancel_request(request_id)
            if request is None:
                raise NotFound("取消申请不存在", field="request_id")
            order = repo.get_order(request.order_id)
            if order is None or order.store_id != actor.store_id:
                raise PermissionDenied("只能审批本店的取消申请")
            if request.status is not CancelRequestStatus.PENDING:
                raise ConflictError("该申请已处理过了", field="request_id")
            repo.set_cancel_request_status(request_id, CancelRequestStatus.REJECTED, actor.user_id)

    # ---------- 改期改房型 ----------

    def modify_order(
        self,
        actor: Session,
        order_id: str,
        *,
        items: list[RoomRequest],
        check_in: date,
        check_out: date,
    ) -> Order:
        self._validate_stay(check_in, check_out)
        if not items:
            raise ValidationError("至少选择一个房型", field="items")
        merged = self._merge(items)
        with acquire_all(self._price_locks(merged, check_in, check_out), self._db.lock_timeout):
            with UnitOfWork(self._db) as conn:
                repo = OrderRepository(conn)
                order = repo.get_order(order_id)
                if order is None:
                    raise NotFound("订单不存在", field="order_id")
                self._check_scope(conn, actor, order)
                self._ensure_modifiable(order)
                self._ensure_no_pending_request(repo, order)

                built = self._build_items(conn, order.store_id, merged, check_in, check_out)
                new_total = sum(item.subtotal_cents for item in built)
                if self._needs_approval(order, new_total):
                    raise ConflictError("改期后需要退款，请提交改期申请由店长审批", field="status")
                self._apply_modify(conn, repo, order, built, check_in, check_out, new_total)
        return self.get_order(actor, order_id)

    def request_modify(
        self,
        actor: Session,
        order_id: str,
        *,
        items: list[RoomRequest],
        check_in: date,
        check_out: date,
    ) -> ModifyRequest:
        """改期涉及退款且已过取消截止时间时，先提交申请（REQ-031）。"""
        self._validate_stay(check_in, check_out)
        if not items:
            raise ValidationError("至少选择一个房型", field="items")
        merged = self._merge(items)
        with acquire_all(self._price_locks(merged, check_in, check_out), self._db.lock_timeout):
            with UnitOfWork(self._db) as conn:
                repo = OrderRepository(conn)
                order = repo.get_order(order_id)
                if order is None:
                    raise NotFound("订单不存在", field="order_id")
                self._check_scope(conn, actor, order)
                self._ensure_modifiable(order)
                self._ensure_no_pending_request(repo, order)

                built = self._build_items(conn, order.store_id, merged, check_in, check_out)
                new_total = sum(item.subtotal_cents for item in built)
                if not self._needs_approval(order, new_total):
                    raise ConflictError("这次改期不需要审批，请直接修改", field="status")
                request = ModifyRequest(
                    id=new_id("mr"),
                    order_id=order_id,
                    items=tuple((item.room_type_id, item.qty) for item in merged),
                    check_in_date=check_in,
                    check_out_date=check_out,
                    old_total_cents=order.total_cents,
                    new_total_cents=new_total,
                    applicant=actor.user_id,
                    approver=None,
                    status=ModifyRequestStatus.PENDING,
                    created_at=self._clock.now(),
                )
                repo.insert_modify_request(request)
        return request

    def approve_modify_request(self, actor: Session, request_id: str) -> Order:
        if actor.role is not Role.STORE_MANAGER:
            raise PermissionDenied("只有店长能审批改期申请")
        request = self._pending_modify_request(request_id)
        merged = [RoomRequest(room_type_id, qty) for room_type_id, qty in request.items]
        with acquire_all(
            self._price_locks(merged, request.check_in_date, request.check_out_date),
            self._db.lock_timeout,
        ):
            with UnitOfWork(self._db) as conn:
                ensure_active(conn, actor)
                repo = OrderRepository(conn)
                order = repo.get_order(request.order_id)
                if order is None:
                    raise NotFound("订单不存在", field="order_id")
                if order.store_id != actor.store_id:
                    raise PermissionDenied("只能审批本店的改期申请")
                self._ensure_modifiable(order)
                built = self._build_items(
                    conn, order.store_id, merged, request.check_in_date, request.check_out_date
                )
                new_total = sum(item.subtotal_cents for item in built)
                self._apply_modify(
                    conn,
                    repo,
                    order,
                    built,
                    request.check_in_date,
                    request.check_out_date,
                    new_total,
                )
                repo.set_modify_request_status(
                    request_id, ModifyRequestStatus.APPROVED, actor.user_id
                )
                order_id = order.id
        return self.get_order(actor, order_id)

    def reject_modify_request(self, actor: Session, request_id: str) -> None:
        if actor.role is not Role.STORE_MANAGER:
            raise PermissionDenied("只有店长能审批改期申请")
        with UnitOfWork(self._db) as conn:
            ensure_active(conn, actor)
            repo = OrderRepository(conn)
            request = repo.get_modify_request(request_id)
            if request is None:
                raise NotFound("改期申请不存在", field="request_id")
            order = repo.get_order(request.order_id)
            if order is None or order.store_id != actor.store_id:
                raise PermissionDenied("只能审批本店的改期申请")
            if request.status is not ModifyRequestStatus.PENDING:
                raise ConflictError("该申请已处理过了", field="request_id")
            repo.set_modify_request_status(request_id, ModifyRequestStatus.REJECTED, actor.user_id)

    def list_pending_modify_requests(self, actor: Session, store_id: str) -> list[ModifyRequest]:
        if actor.role is not Role.STORE_MANAGER or actor.store_id != store_id:
            raise PermissionDenied("只有本店店长能查看改期申请")
        with UnitOfWork(self._db) as conn:
            return OrderRepository(conn).list_pending_modify_requests(store_id)

    def _pending_modify_request(self, request_id: str) -> ModifyRequest:
        with UnitOfWork(self._db) as conn:
            request = OrderRepository(conn).get_modify_request(request_id)
        if request is None:
            raise NotFound("改期申请不存在", field="request_id")
        if request.status is not ModifyRequestStatus.PENDING:
            raise ConflictError("该申请已处理过了", field="request_id")
        return request

    @staticmethod
    def _ensure_modifiable(order: Order) -> None:
        if order.status is not OrderStatus.CONFIRMED:
            raise ConflictError("只有已确认且未入住的订单可以修改", field="status")

    @staticmethod
    def _ensure_no_pending_request(repo: OrderRepository, order: Order) -> None:
        if repo.pending_modify_request(order.id) is not None:
            raise ConflictError("该订单已有待审批的改期申请", field="order_id")

    def _needs_approval(self, order: Order, new_total_cents: int) -> bool:
        """降价即产生退款；过了取消截止时间就要按取消规则走审批（REQ-031）。"""
        return new_total_cents < order.total_cents and self._clock.now() >= self._cancel_deadline(
            order
        )

    def _apply_modify(
        self,
        conn: sqlite3.Connection,
        repo: OrderRepository,
        order: Order,
        built: list[OrderItem],
        check_in: date,
        check_out: date,
        new_total: int,
    ) -> None:
        # 先释放旧占用再占新日期：同一次事务里，新日期不够就整体回滚。
        self._release_all(conn, order.items)
        self._reserve_all(conn, built)
        repo.delete_items(order.id)
        for item in built:
            repo.insert_item(replace(item, order_id=order.id))
        repo.set_dates(order.id, check_in, check_out)
        repo.set_total(order.id, new_total)
        if new_total < order.total_cents and self._payment is not None:
            self._payment.refund_difference(conn, order, order.total_cents - new_total)

    # ---------- 状态推进（供 M7 使用） ----------

    def change_status(self, order_id: str, target: OrderStatus) -> None:
        with UnitOfWork(self._db) as conn:
            repo = OrderRepository(conn)
            order = repo.get_order(order_id)
            if order is None:
                raise NotFound("订单不存在", field="order_id")
            if not can_transition(order.status, target):
                raise ConflictError(
                    f"订单状态不能从 {order.status.value} 变为 {target.value}", field="status"
                )
            now = self._clock.now()
            repo.update_status(
                order_id,
                target,
                checked_in_at=now if target is OrderStatus.CHECKED_IN else None,
                checked_out_at=now if target is OrderStatus.CHECKED_OUT else None,
            )

    # ---------- 内部 ----------

    def _validate_stay(self, check_in: date, check_out: date) -> None:
        if check_out <= check_in:
            raise ValidationError("离店日期必须晚于入住日期", field="check_out")
        if check_in < self._clock.today():
            raise ValidationError("入住日期不能早于今天", field="check_in")

    def _price_locks(
        self, merged: list[RoomRequest], check_in: date, check_out: date
    ) -> list[threading.Lock]:
        nights = [
            date.fromordinal(check_in.toordinal() + offset)
            for offset in range((check_out - check_in).days)
        ]
        return self._db.price_locks_for([item.room_type_id for item in merged], nights)

    @staticmethod
    def _merge(items: list[RoomRequest]) -> list[RoomRequest]:
        grouped: dict[str, int] = {}
        for item in items:
            if item.qty <= 0:
                raise ValidationError("间数必须为正整数", field="qty")
            grouped[item.room_type_id] = grouped.get(item.room_type_id, 0) + item.qty
        return [RoomRequest(room_type_id=key, qty=value) for key, value in grouped.items()]

    def _build_items(
        self,
        conn: sqlite3.Connection,
        store_id: str,
        merged: list[RoomRequest],
        check_in: date,
        check_out: date,
    ) -> list[OrderItem]:
        store_repo = StoreRepository(conn)
        pricing = PricingRepository(conn)
        built: list[OrderItem] = []
        nights = (check_out - check_in).days
        for request in merged:
            room_type = store_repo.get_room_type(request.room_type_id)
            if room_type is None:
                raise NotFound("房型不存在", field="room_type_id")
            if room_type.store_id != store_id:
                raise ValidationError("房型不属于该门店", field="items")
            if not room_type.is_listed:
                raise ConflictError(f"{room_type.name} 已下架", field="items")
            for offset in range(nights):
                night = date.fromordinal(check_in.toordinal() + offset)
                price = pricing.get_price(request.room_type_id, night)
                if price is None:
                    raise ValidationError(f"{night} 尚未设置房价", field="items")
                built.append(
                    OrderItem(
                        id=new_id("oi"),
                        order_id="",
                        room_type_id=request.room_type_id,
                        stay_date=night,
                        qty=request.qty,
                        unit_price_cents=price.price_cents,
                        subtotal_cents=price.price_cents * request.qty,
                    )
                )
        return built

    def _reserve_all(self, conn: sqlite3.Connection, items: list[OrderItem]) -> None:
        for item in items:
            ok = self._inventory.reserve_online(conn, item.room_type_id, item.stay_date, item.qty)
            if not ok:
                raise ConflictError(f"{item.stay_date} 库存不足，请调整日期或房型", field="items")

    def _release_all(self, conn: sqlite3.Connection, items: list[OrderItem]) -> None:
        for item in items:
            self._inventory.release_online(conn, item.room_type_id, item.stay_date, item.qty)

    def _check_scope(self, conn: sqlite3.Connection, actor: Session, order: Order) -> None:
        ensure_active(conn, actor)
        if actor.role is Role.CUSTOMER:
            if order.customer_id != actor.user_id:
                raise PermissionDenied("只能查看自己的订单")
            return
        if actor.role in (Role.FRONT_DESK, Role.STORE_MANAGER):
            if order.store_id != actor.store_id:
                raise PermissionDenied("只能查看本店订单")
            return
        if actor.role is Role.AREA_MANAGER:
            store = StoreRepository(conn).get_store(order.store_id)
            if store is None or store.area_id != actor.area_id:
                raise PermissionDenied("只能查看本片区订单")
            return
        raise PermissionDenied("无权查看该订单")

    @staticmethod
    def _cancel_deadline(order: Order) -> datetime:
        return datetime.combine(order.check_in_date, time(CANCEL_DEADLINE_HOUR, 0))

    @staticmethod
    def _make_order_no(now: datetime) -> str:
        return f"SO{now:%Y%m%d%H%M%S}{random.randint(1000, 9999)}"
