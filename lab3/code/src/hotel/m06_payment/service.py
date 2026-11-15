"""支付与退款的服务层。

支付回调按 pay_no 判重；超时释放、未到店标记、逾期释放做成可手动触发的任务函数，
界面与测试直接调用，不依赖真实定时器。
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta

from hotel.core.audit import record_audit
from hotel.core.auth import ensure_active
from hotel.core.clock import Clock
from hotel.core.db import Database, UnitOfWork
from hotel.core.errors import ConflictError, NotFound, PermissionDenied, ValidationError
from hotel.core.events import make_order_event
from hotel.core.ids import new_id
from hotel.m01_account.model import Role, Session
from hotel.m04_inventory.service import InventoryService
from hotel.m05_order.model import Order, OrderStatus
from hotel.m05_order.repository import OrderRepository
from hotel.m06_payment.model import (
    Payment,
    PaymentStatus,
    ReconciliationRecord,
    ReconciliationStatus,
    Refund,
    RefundStatus,
)
from hotel.m06_payment.repository import PaymentRepository

NO_SHOW_HOUR = 22
NO_SHOW_CUTOFF_HOUR = 12


class PaymentService:
    def __init__(
        self, database: Database, clock: Clock, inventory_service: InventoryService
    ) -> None:
        self._db = database
        self._clock = clock
        self._inventory = inventory_service
        self._bus = None

    def attach_events(self, bus) -> None:
        self._bus = bus

    def _publish(self, event) -> None:
        if self._bus is not None and event is not None:
            self._bus.publish(event)

    # ---------- 支付 ----------

    def create_payment(self, actor: Session, order_id: str, channel: str = "ONLINE") -> Payment:
        if actor.role is not Role.CUSTOMER:
            raise PermissionDenied("只有顾客能发起支付")
        with UnitOfWork(self._db) as conn:
            ensure_active(conn, actor)
            order = OrderRepository(conn).get_order(order_id)
            if order is None:
                raise NotFound("订单不存在", field="order_id")
            if order.customer_id != actor.user_id:
                raise PermissionDenied("只能支付自己的订单")
            if order.status is not OrderStatus.PENDING_PAYMENT:
                raise ConflictError("订单当前状态不需要支付", field="status")
            if PaymentRepository(conn).has_active_payment(order_id):
                raise ConflictError("该订单已有支付单，请勿重复发起", field="order_id")
            payment = Payment(
                id=new_id("pmt"),
                pay_no=new_id("pay"),
                order_id=order_id,
                amount_cents=order.total_cents,
                channel=channel,
                txn_id=None,
                status=PaymentStatus.PENDING,
                paid_at=None,
                created_at=self._clock.now(),
            )
            PaymentRepository(conn).insert_payment(payment)
        return payment

    def pay(self, pay_no: str, txn_id: str = "TXN-DEMO") -> Payment:
        """演示与测试用：直接模拟支付平台回调成功。"""
        payment = self._payment_of(pay_no)
        return self.handle_callback(pay_no, txn_id, payment.amount_cents)

    def handle_callback(self, pay_no: str, txn_id: str, amount_cents: int) -> Payment:
        with UnitOfWork(self._db) as conn:
            repo = PaymentRepository(conn)
            payment = repo.get_by_pay_no(pay_no)
            if payment is None:
                raise NotFound("支付单不存在", field="pay_no")
            if payment.status is PaymentStatus.SUCCESS:
                # 重复投递的回调直接返回，不重复改单（REQ-028）。
                return payment
            if amount_cents != payment.amount_cents:
                raise ValidationError("回调金额与支付单不一致", field="amount")

            now = self._clock.now()
            repo.mark_success(payment.id, txn_id, now)
            order = OrderRepository(conn).get_order(payment.order_id)
            assert order is not None
            event = None

            if repo.count_successful(payment.order_id) > 1:
                # 同一订单收到两笔成功支付：钱扣了两次，记对账差异交人工处理。
                repo.insert_reconciliation(
                    ReconciliationRecord(
                        id=new_id("rec"),
                        payment_id=payment.id,
                        rec_date=now.date(),
                        diff_type="DUPLICATE_PAYMENT",
                        diff_cents=payment.amount_cents,
                        resolution=None,
                        status=ReconciliationStatus.OPEN,
                    )
                )

            if order.status is OrderStatus.PENDING_PAYMENT:
                OrderRepository(conn).update_status(order.id, OrderStatus.CONFIRMED)
                event = make_order_event(conn, "ORDER_CONFIRMED", order, now)
                record_audit(
                    conn,
                    operator_id="system",
                    operator_role="SYSTEM",
                    action="PAYMENT_CONFIRMED",
                    object_type="order",
                    object_id=order.id,
                    reason=f"订单 {order.order_no}",
                    before_value=OrderStatus.PENDING_PAYMENT.value,
                    after_value=OrderStatus.CONFIRMED.value,
                    moment=now,
                )
            elif order.status is not OrderStatus.CONFIRMED:
                # 订单已经取消或已入住后才收到回调，记为对账差异，不改订单状态。
                repo.insert_reconciliation(
                    ReconciliationRecord(
                        id=new_id("rec"),
                        payment_id=payment.id,
                        rec_date=now.date(),
                        diff_type=f"PAID_AFTER_{order.status.value}",
                        diff_cents=payment.amount_cents,
                        resolution=None,
                        status=ReconciliationStatus.OPEN,
                    )
                )
            updated = repo.get_by_id(payment.id)
        self._publish(event)
        assert updated is not None
        return updated

    # ---------- 退款 ----------

    def refund_for_cancelled_order(self, conn: sqlite3.Connection, order: Order) -> Refund | None:
        """由取消流程在同一事务里调用；重复取消只产生一次退款（REQ-009）。"""
        repo = PaymentRepository(conn)
        payment = repo.successful_payment_of_order(order.id)
        if payment is None:
            return None
        remaining = payment.amount_cents - repo.sum_refunded(order.id)
        if remaining <= 0:
            return None
        return self._issue_refund(conn, repo, order, payment, remaining, "订单取消退款")

    def refund_difference(
        self, conn: sqlite3.Connection, order: Order, amount_cents: int
    ) -> Refund | None:
        """改期后金额下降时退差额（REQ-031 多退少补）。"""
        if amount_cents <= 0:
            return None
        repo = PaymentRepository(conn)
        payment = repo.successful_payment_of_order(order.id)
        if payment is None:
            return None
        refundable = payment.amount_cents - repo.sum_refunded(order.id)
        return self._issue_refund(
            conn, repo, order, payment, min(amount_cents, refundable), "订单改期差额退款"
        )

    def _issue_refund(
        self,
        conn: sqlite3.Connection,
        repo: PaymentRepository,
        order: Order,
        payment: Payment,
        amount_cents: int,
        reason: str,
    ) -> Refund:
        refund = Refund(
            id=new_id("rfd"),
            refund_no=new_id("refund"),
            order_id=order.id,
            payment_id=payment.id,
            amount_cents=amount_cents,
            reason=reason,
            status=RefundStatus.SUCCESS,
            refunded_at=self._clock.now(),
        )
        repo.insert_refund(refund)
        record_audit(
            conn,
            operator_id="system",
            operator_role="SYSTEM",
            action="REFUND_ISSUED",
            object_type="order",
            object_id=order.id,
            reason=reason,
            after_value=str(amount_cents),
            moment=self._clock.now(),
        )
        return refund

    # ---------- 定时任务（可手动触发） ----------

    def expire_unpaid_orders(self) -> int:
        now = self._clock.now()
        with UnitOfWork(self._db) as conn:
            rows = conn.execute(
                "SELECT id FROM orders WHERE status = 'PENDING_PAYMENT' AND pay_deadline < ?",
                (now.isoformat(),),
            ).fetchall()
        expired = 0
        for row in rows:
            if self._expire_one(row["id"], now):
                expired += 1
        return expired

    def _expire_one(self, order_id: str, now: datetime) -> bool:
        with UnitOfWork(self._db) as conn:
            repo = OrderRepository(conn)
            order = repo.get_order(order_id)
            if order is None or order.status is not OrderStatus.PENDING_PAYMENT:
                return False
            self._release(conn, order)
            repo.update_status(order_id, OrderStatus.CANCELLED)
            record_audit(
                conn,
                operator_id="system",
                operator_role="SYSTEM",
                action="ORDER_EXPIRED",
                object_type="order",
                object_id=order_id,
                reason="超过支付时限",
                before_value=OrderStatus.PENDING_PAYMENT.value,
                after_value=OrderStatus.CANCELLED.value,
                moment=now,
            )
            event = make_order_event(conn, "ORDER_CANCELLED", order, now)
        self._publish(event)
        return True

    def mark_no_show(self) -> int:
        """入住日 22:00 仍未办理入住的已确认订单标为未到店（REQ-022）。"""
        now = self._clock.now()
        if now.hour < NO_SHOW_HOUR:
            return 0
        cutoff = datetime.combine(now.date(), time(NO_SHOW_HOUR, 0))
        with UnitOfWork(self._db) as conn:
            rows = conn.execute(
                "SELECT id FROM orders WHERE status = 'CONFIRMED' AND check_in_date = ?",
                (now.date().isoformat(),),
            ).fetchall()
        marked = 0
        for row in rows:
            event = None
            with UnitOfWork(self._db) as conn:
                repo = OrderRepository(conn)
                order = repo.get_order(row["id"])
                if order is None or order.status is not OrderStatus.CONFIRMED:
                    continue
                repo.update_status(order.id, OrderStatus.NO_SHOW)
                record_audit(
                    conn,
                    operator_id="system",
                    operator_role="SYSTEM",
                    action="ORDER_NO_SHOW",
                    object_type="order",
                    object_id=order.id,
                    reason="入住日 22:00 未到店",
                    before_value=OrderStatus.CONFIRMED.value,
                    after_value=OrderStatus.NO_SHOW.value,
                    moment=max(now, cutoff),
                )
                event = make_order_event(conn, "ORDER_NO_SHOW", order, now)
            self._publish(event)
            marked += 1
        return marked

    def release_overdue_no_show(self) -> int:
        """未到店订单次日 12:00 仍未入住则取消并释放库存。"""
        now = self._clock.now()
        with UnitOfWork(self._db) as conn:
            rows = conn.execute("SELECT id FROM orders WHERE status = 'NO_SHOW'").fetchall()
        released = 0
        for row in rows:
            event = None
            with UnitOfWork(self._db) as conn:
                repo = OrderRepository(conn)
                order = repo.get_order(row["id"])
                if order is None:
                    continue
                cutoff = datetime.combine(
                    order.check_in_date + timedelta(days=1), time(NO_SHOW_CUTOFF_HOUR, 0)
                )
                if now < cutoff:
                    continue
                self._release(conn, order)
                repo.update_status(order.id, OrderStatus.CANCELLED)
                record_audit(
                    conn,
                    operator_id="system",
                    operator_role="SYSTEM",
                    action="ORDER_CANCELLED_OVERDUE",
                    object_type="order",
                    object_id=order.id,
                    reason="未到店且超过次日 12:00",
                    before_value=OrderStatus.NO_SHOW.value,
                    after_value=OrderStatus.CANCELLED.value,
                    moment=now,
                )
                event = make_order_event(conn, "ORDER_CANCELLED", order, now)
            self._publish(event)
            released += 1
        return released

    # ---------- 对账 ----------

    def reconcile(self, on_date: date) -> list[ReconciliationRecord]:
        """把「已收钱但订单没生效」的支付记成对账差异（REQ-028）。"""
        with UnitOfWork(self._db) as conn:
            repo = PaymentRepository(conn)
            rows = conn.execute(
                "SELECT p.id AS payment_id, p.amount_cents AS amount, o.status AS status"
                " FROM payment p JOIN orders o ON o.id = p.order_id"
                " WHERE p.status = 'SUCCESS' AND substr(p.paid_at, 1, 10) = ?"
                " AND o.status IN ('CANCELLED', 'NO_SHOW')",
                (on_date.isoformat(),),
            ).fetchall()
            existing = {record.payment_id for record in repo.list_reconciliation(on_date)}
            for row in rows:
                if row["payment_id"] in existing:
                    continue
                repo.insert_reconciliation(
                    ReconciliationRecord(
                        id=new_id("rec"),
                        payment_id=row["payment_id"],
                        rec_date=on_date,
                        diff_type=f"PAID_BUT_{row['status']}",
                        diff_cents=row["amount"],
                        resolution=None,
                        status=ReconciliationStatus.OPEN,
                    )
                )
            return repo.list_reconciliation(on_date)

    # ---------- 内部 ----------

    def _payment_of(self, pay_no: str) -> Payment:
        with UnitOfWork(self._db) as conn:
            payment = PaymentRepository(conn).get_by_pay_no(pay_no)
        if payment is None:
            raise NotFound("支付单不存在", field="pay_no")
        return payment

    def _release(self, conn: sqlite3.Connection, order: Order) -> None:
        for item in order.items:
            self._inventory.release_online(conn, item.room_type_id, item.stay_date, item.qty)
