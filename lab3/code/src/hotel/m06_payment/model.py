"""支付、退款与对账的领域对象。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class RefundStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class ReconciliationStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


@dataclass(frozen=True)
class Payment:
    id: str
    pay_no: str
    order_id: str
    amount_cents: int
    channel: str
    txn_id: str | None
    status: PaymentStatus
    paid_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class Refund:
    id: str
    refund_no: str
    order_id: str
    payment_id: str
    amount_cents: int
    reason: str
    status: RefundStatus
    refunded_at: datetime | None


@dataclass(frozen=True)
class ReconciliationRecord:
    id: str
    payment_id: str
    rec_date: date
    diff_type: str
    diff_cents: int
    resolution: str | None
    status: ReconciliationStatus
