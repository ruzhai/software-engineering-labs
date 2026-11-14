"""SQLite 访问。

并发场景下每个线程各开一条连接：调用方通过 UnitOfWork 拿到连接，
同一事务内的多条语句要么一起提交、要么一起回滚。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import TracebackType

from hotel.core.schema import SCHEMA_STATEMENTS

SCHEMA_VERSION = 1


class Database:
    """持有数据库路径，按需开新连接。"""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    def initialize(self) -> None:
        conn = self.connect()
        try:
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)
            conn.execute("DELETE FROM schema_version")
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            conn.commit()
        finally:
            conn.close()


class UnitOfWork:
    """一个事务一个连接。异常时回滚，正常退出时提交。"""

    def __init__(self, database: Database) -> None:
        self._database = database
        self.conn: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        self.conn = self._database.connect()
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self.conn is not None
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()
            self.conn = None


def fetch_one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> sqlite3.Row | None:
    return conn.execute(sql, params).fetchone()


def fetch_all(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, params).fetchall())
