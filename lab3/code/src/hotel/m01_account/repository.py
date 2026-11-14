"""账号的 SQLite 读写。"""

from __future__ import annotations

import sqlite3

from hotel.m01_account.model import Role, User, UserStatus


def _to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        name=row["name"],
        phone=row["phone"],
        role=Role(row["role"]),
        status=UserStatus(row["status"]),
        store_id=row["store_id"],
        area_id=row["area_id"],
    )


class UserRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def insert(
        self,
        *,
        user_id: str,
        name: str,
        phone: str,
        password_hash: str,
        role: Role,
        store_id: str | None,
        area_id: str | None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO user"
            " (id, name, phone, password_hash, role, status, store_id, area_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                name,
                phone,
                password_hash,
                role.value,
                UserStatus.ACTIVE.value,
                store_id,
                area_id,
            ),
        )

    def get_by_id(self, user_id: str) -> User | None:
        row = self.conn.execute("SELECT * FROM user WHERE id = ?", (user_id,)).fetchone()
        return _to_user(row) if row else None

    def get_credentials(self, phone: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM user WHERE phone = ?", (phone,)).fetchone()

    def get_by_phone(self, phone: str) -> User | None:
        row = self.conn.execute("SELECT * FROM user WHERE phone = ?", (phone,)).fetchone()
        return _to_user(row) if row else None

    def list_staff_of_store(self, store_id: str) -> list[User]:
        rows = self.conn.execute(
            "SELECT * FROM user WHERE store_id = ? ORDER BY name", (store_id,)
        ).fetchall()
        return [_to_user(row) for row in rows]

    def set_status(self, user_id: str, status: UserStatus) -> None:
        self.conn.execute("UPDATE user SET status = ? WHERE id = ?", (status.value, user_id))

    def bump_failed_attempts(self, user_id: str) -> int:
        self.conn.execute(
            "UPDATE user SET failed_attempts = failed_attempts + 1 WHERE id = ?", (user_id,)
        )
        row = self.conn.execute(
            "SELECT failed_attempts FROM user WHERE id = ?", (user_id,)
        ).fetchone()
        return int(row["failed_attempts"])

    def reset_failed_attempts(self, user_id: str) -> None:
        self.conn.execute("UPDATE user SET failed_attempts = 0 WHERE id = ?", (user_id,))

    def lock_until(self, user_id: str, moment_iso: str) -> None:
        self.conn.execute("UPDATE user SET locked_until = ? WHERE id = ?", (moment_iso, user_id))
