"""门店与房源的领域对象，对应类图的片区、门店、房型、房间。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class StoreStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RoomStatus(str, Enum):
    FREE = "FREE"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    CHECKED_OUT = "CHECKED_OUT"
    CLEANING = "CLEANING"
    REPAIRING = "REPAIRING"


@dataclass(frozen=True)
class Area:
    id: str
    name: str


@dataclass
class Store:
    id: str
    area_id: str
    name: str
    city: str
    district: str
    status: StoreStatus


@dataclass
class RoomType:
    id: str
    store_id: str
    name: str
    bed_type: str
    max_guests: int
    is_listed: bool


@dataclass(frozen=True)
class Room:
    id: str
    room_type_id: str
    room_no: str
    status: RoomStatus
    repair_until: date | None


@dataclass(frozen=True)
class RoomTypeOverview:
    """查询结果：房型连同所属门店、房间总数与维修间数。"""

    room_type_id: str
    room_type_name: str
    store_id: str
    store_name: str
    city: str
    bed_type: str
    max_guests: int
    total_rooms: int
    under_repair: int
