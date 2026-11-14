"""库存的领域对象，对应类图的日库存。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DailyInventory:
    """某房型某晚的库存。

    线上可售上限 = 当日可用房间数 − 线下保留额度（REQ-033）；
    线下剩余额度 = 线下保留额度 − 线下已售；两条线互不占用。
    """

    room_type_id: str
    inv_date: date
    online_limit: int
    online_sold: int
    offline_reserved: int
    offline_sold: int

    @property
    def online_remaining(self) -> int:
        return self.online_limit - self.online_sold

    @property
    def offline_remaining(self) -> int:
        return self.offline_reserved - self.offline_sold
