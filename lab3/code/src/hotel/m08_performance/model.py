"""评价与绩效汇总的领域对象。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ReviewStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    HIDDEN = "HIDDEN"


@dataclass(frozen=True)
class Review:
    id: str
    order_id: str
    score: int
    content: str
    submitted_at: datetime
    status: ReviewStatus


@dataclass(frozen=True)
class Performance:
    """门店绩效汇总。评价只计入门店与店长，不计入前台（REQ-003）。"""

    id: str
    store_id: str
    period: str
    order_count: int
    occupancy_rate: float
    avg_score: float
