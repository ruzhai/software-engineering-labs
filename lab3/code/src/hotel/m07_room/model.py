"""房态状态机与工单。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from hotel.m02_store.model import RoomStatus

# REQ-005 的允许转换。前台只能沿这张表推进房态。
ALLOWED_ROOM_TRANSITIONS: dict[RoomStatus, frozenset[RoomStatus]] = {
    RoomStatus.FREE: frozenset({RoomStatus.RESERVED, RoomStatus.REPAIRING}),
    RoomStatus.RESERVED: frozenset({RoomStatus.OCCUPIED, RoomStatus.FREE}),
    RoomStatus.OCCUPIED: frozenset({RoomStatus.CHECKED_OUT}),
    RoomStatus.CHECKED_OUT: frozenset({RoomStatus.CLEANING}),
    RoomStatus.CLEANING: frozenset({RoomStatus.FREE, RoomStatus.REPAIRING}),
    RoomStatus.REPAIRING: frozenset({RoomStatus.FREE}),
}


def can_change_room(current: RoomStatus, target: RoomStatus) -> bool:
    return target in ALLOWED_ROOM_TRANSITIONS[current]


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    DONE = "DONE"
    REJECTED = "REJECTED"


class WorkOrderType(str, Enum):
    REPAIR = "REPAIR"
    CHANGE_ROOM_TYPE = "CHANGE_ROOM_TYPE"


@dataclass(frozen=True)
class WorkOrder:
    id: str
    room_id: str
    type: WorkOrderType
    reason: str
    involved_date: date
    status: WorkOrderStatus
    submitter: str
    executor: str | None
    created_at: datetime
