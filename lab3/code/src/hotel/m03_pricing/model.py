"""定价的领域对象，对应类图的日价、价格区间、改价申请。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class PriceSource(str, Enum):
    MANAGER = "MANAGER"
    APPROVED_REQUEST = "APPROVED_REQUEST"


class ChangeRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class PriceRange:
    id: str
    store_id: str
    effective_date: date
    min_cents: int
    max_cents: int


@dataclass(frozen=True)
class DailyPrice:
    room_type_id: str
    price_date: date
    price_cents: int
    source: PriceSource


@dataclass(frozen=True)
class PriceChangeRequest:
    id: str
    room_type_id: str
    price_date: date
    old_cents: int
    new_cents: int
    applicant: str
    approver: str | None
    status: ChangeRequestStatus
