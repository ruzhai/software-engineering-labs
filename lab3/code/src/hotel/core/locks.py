"""价格锁。

REQ-012 要求店长改价与顾客下单互斥，且锁只覆盖改价写入这一小段。
锁按 (房型, 日期) 分粒度，多个锁按 key 排序获取，避免两个线程反向加锁死等。
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

from hotel.core.errors import ConflictError


@contextmanager
def acquire_all(locks: Iterable[threading.Lock], timeout: float) -> Iterator[None]:
    acquired: list[threading.Lock] = []
    try:
        for lock in locks:
            if not lock.acquire(timeout=timeout):
                raise ConflictError("价格正在修改，请稍后重试", field="price")
            acquired.append(lock)
        yield
    finally:
        for lock in reversed(acquired):
            lock.release()
