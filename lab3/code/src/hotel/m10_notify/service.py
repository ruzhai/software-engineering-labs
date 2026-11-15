"""通知的服务层。

只订阅事件，不反向调用业务模块。发送失败记下原因并进入重试，
订单状态不受影响（REQ-029）。
"""

from __future__ import annotations

import json

from hotel.core.auth import ensure_active
from hotel.core.clock import Clock
from hotel.core.db import Database, UnitOfWork
from hotel.core.errors import NotFound, PermissionDenied
from hotel.core.events import EventBus, OrderEvent
from hotel.core.ids import new_id
from hotel.core.money import format_cents
from hotel.m01_account.model import Role, Session
from hotel.m10_notify.model import (
    Channel,
    Notification,
    NotificationChannel,
    NotificationStatus,
)
from hotel.m10_notify.repository import NotificationRepository

MAX_RETRIES = 3

TEMPLATES = {
    "ORDER_CONFIRMED": "【酒店预订】订单 {order_no} 已支付成功，金额 {amount}，门店：{store}。",
    "ORDER_CANCELLED": "【酒店预订】订单 {order_no} 已取消。",
    "ORDER_NO_SHOW": "【酒店预订】订单 {order_no} 未按时到店，次日 12:00 前仍可到店办理入住。",
}


class InMemoryChannel:
    """演示用通道。`fail = True` 可以模拟通道不可用。"""

    def __init__(self) -> None:
        self.fail = False
        self.sent: list[tuple[str, str]] = []

    def send(self, phone: str, text: str) -> None:
        if self.fail:
            raise RuntimeError("通道不可用")
        self.sent.append((phone, text))


class NotificationService:
    def __init__(self, database: Database, clock: Clock, channel: NotificationChannel) -> None:
        self._db = database
        self._clock = clock
        self._channel = channel

    def subscribe(self, bus: EventBus) -> None:
        bus.subscribe(self._on_event)

    def _on_event(self, event: OrderEvent) -> None:
        if event.type not in TEMPLATES:
            return
        with UnitOfWork(self._db) as conn:
            repo = NotificationRepository(conn)
            # 同一订单同一事件只发一条（REQ-029）。
            if repo.of_order_and_type(event.order_id, event.type) is not None:
                return
            text = self._render(event)
            payload = json.dumps({"phone": event.phone, "text": text}, ensure_ascii=False)
            try:
                self._channel.send(event.phone, text)
                status, reason, sent_at = NotificationStatus.SENT, None, self._clock.now()
            # 通道异常只影响通知本身，不改订单状态。
            except Exception as exc:  # pylint: disable=broad-exception-caught
                status, reason, sent_at = NotificationStatus.FAILED, str(exc), None
            repo.insert(
                Notification(
                    id=new_id("ntf"),
                    order_id=event.order_id,
                    type=event.type,
                    channel=Channel.SMS,
                    status=status,
                    failure_reason=reason,
                    retry_count=0,
                    sent_at=sent_at,
                    payload=payload,
                )
            )

    def retry_failed(self) -> int:
        with UnitOfWork(self._db) as conn:
            repo = NotificationRepository(conn)
            pending = repo.list_failed(MAX_RETRIES)
            retried = 0
            for notification in pending:
                data = json.loads(notification.payload)
                try:
                    self._channel.send(data["phone"], data["text"])
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    retries = notification.retry_count + 1
                    status = (
                        NotificationStatus.GIVE_UP
                        if retries >= MAX_RETRIES
                        else NotificationStatus.FAILED
                    )
                    repo.update_result(notification.id, status, str(exc), retries, None)
                else:
                    repo.update_result(
                        notification.id,
                        NotificationStatus.SENT,
                        None,
                        notification.retry_count + 1,
                        self._clock.now(),
                    )
                    retried += 1
        return retried

    def list_for_store(self, actor: Session, store_id: str) -> list[Notification]:
        if actor.role not in (Role.FRONT_DESK, Role.STORE_MANAGER) or actor.store_id != store_id:
            raise PermissionDenied("只能查看本店通知")
        with UnitOfWork(self._db) as conn:
            ensure_active(conn, actor)
            return NotificationRepository(conn).list_by_store(store_id)

    def list_for_order(self, actor: Session, order_id: str) -> list[Notification]:
        with UnitOfWork(self._db) as conn:
            notifications = NotificationRepository(conn).list_by_order(order_id)
            order = conn.execute(
                "SELECT customer_id FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
        if order is None:
            raise NotFound("订单不存在", field="order_id")
        if actor.role is Role.CUSTOMER and order["customer_id"] != actor.user_id:
            raise PermissionDenied("只能查看自己的通知")
        if actor.role not in (Role.CUSTOMER, Role.FRONT_DESK, Role.STORE_MANAGER):
            raise PermissionDenied("当前角色不能查看通知")
        return notifications

    @staticmethod
    def _render(event: OrderEvent) -> str:
        template = TEMPLATES[event.type]
        return template.format(
            order_no=event.order_no,
            amount=format_cents(event.amount_cents),
            store=event.store_name,
        )
