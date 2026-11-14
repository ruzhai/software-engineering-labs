"""测试夹具：每个用例一个独立的 SQLite 库。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from hotel.core.clock import FakeClock
from hotel.core.db import Database
from hotel.m01_account.service import AccountService
from hotel.m02_store.service import StoreService


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "hotel.db")
    db.initialize()
    return db


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 11, 14, 10, 0))


@pytest.fixture
def store_service(database: Database) -> StoreService:
    return StoreService(database)


@pytest.fixture
def account_service(database: Database, clock: FakeClock) -> AccountService:
    return AccountService(database, clock)
