"""业务事件总线。

设计说明里定了一条：通知模块只订阅事件，不回头调用业务模块。所以事件载荷
必须自带渲染通知所需的全部字段——订单号、金额、顾客手机号、门店名、时间。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from hotel.m05_order.model import Order


@dataclass(frozen=True)
class OrderEvent:
    type: str
    order_id: str
    order_no: str
    amount_cents: int
    phone: str
    customer_name: str
    store_name: str
    moment: datetime


def make_order_event(
    conn: sqlite3.Connection, event_type: str, order: Order, moment: datetime
) -> OrderEvent:
    customer = conn.execute(
        "SELECT name, phone FROM user WHERE id = ?", (order.customer_id,)
    ).fetchone()
    store = conn.execute("SELECT name FROM store WHERE id = ?", (order.store_id,)).fetchone()
    return OrderEvent(
        type=event_type,
        order_id=order.id,
        order_no=order.order_no,
        amount_cents=order.total_cents,
        phone=customer["phone"] if customer else "",
        customer_name=customer["name"] if customer else "",
        store_name=store["name"] if store else "",
        moment=moment,
    )


class EventBus:
    def __init__(self) -> None:
        self._handlers: list[Callable[[OrderEvent], None]] = []

    def subscribe(self, handler: Callable[[OrderEvent], None]) -> None:
        self._handlers.append(handler)

    def publish(self, event: OrderEvent) -> None:
        for handler in self._handlers:
            try:
                handler(event)
            # 通知失败不得影响订单状态变更（REQ-029），所以这里吞掉一切异常。
            except Exception:  # pylint: disable=broad-exception-caught
                continue
