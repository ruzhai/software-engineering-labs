"""时钟。

业务里所有「现在几点」都从 Clock 取，测试用 FakeClock 直接跳到 17:59 / 22:00
这类边界时刻，不靠 sleep。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...

    def today(self) -> date: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now()

    def today(self) -> date:
        return date.today()


class FakeClock:
    """测试用时钟。"""

    def __init__(self, start: datetime) -> None:
        self._moment = start

    def now(self) -> datetime:
        return self._moment

    def today(self) -> date:
        return self._moment.date()

    def advance(self, **delta: float) -> None:
        self._moment += timedelta(**delta)

    def set(self, moment: datetime) -> None:
        self._moment = moment
