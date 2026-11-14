"""订单的领域对象与状态机。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class OrderStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


# REQ-008 的允许转换。不在这张表里的转换一律拒绝。
ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.PENDING_PAYMENT: frozenset({OrderStatus.CONFIRMED, OrderStatus.CANCELLED}),
    OrderStatus.CONFIRMED: frozenset(
        {OrderStatus.CHECKED_IN, OrderStatus.CANCELLED, OrderStatus.NO_SHOW}
    ),
    OrderStatus.CHECKED_IN: frozenset({OrderStatus.CHECKED_OUT}),
    OrderStatus.NO_SHOW: frozenset({OrderStatus.CHECKED_IN, OrderStatus.CANCELLED}),
    OrderStatus.CHECKED_OUT: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
}


def can_transition(current: OrderStatus, target: OrderStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


class CancelRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class OrderItem:
    id: str
    order_id: str
    room_type_id: str
    stay_date: date
    qty: int
    unit_price_cents: int
    subtotal_cents: int


@dataclass
class Order:
    id: str
    order_no: str
    request_no: str
    customer_id: str
    store_id: str
    status: OrderStatus
    total_cents: int
    pay_deadline: datetime
    check_in_date: date
    check_out_date: date
    room_id: str | None
    created_at: datetime
    checked_in_at: datetime | None = None
    checked_out_at: datetime | None = None
    items: list[OrderItem] = field(default_factory=list)


@dataclass(frozen=True)
class CancelRequest:
    id: str
    order_id: str
    reason: str
    applicant: str
    approver: str | None
    status: CancelRequestStatus
    created_at: datetime
