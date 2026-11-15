"""账号与权限的服务层。

权限模型是「角色 + 数据范围」：店长和前台绑定门店，片区负责人绑定片区，
顾客没有数据范围，只能看自己的数据（REQ-001、REQ-026）。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import sqlite3
from datetime import timedelta

from hotel.core.auth import ensure_active
from hotel.core.clock import Clock
from hotel.core.db import Database, UnitOfWork
from hotel.core.errors import (
    AppError,
    ConflictError,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from hotel.core.ids import new_id
from hotel.m01_account.model import Role, Session, User, UserStatus
from hotel.m01_account.repository import UserRepository

MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15
PHONE_PATTERN = re.compile(r"^1\d{10}$")
MIN_PASSWORD_LENGTH = 6
_HASH_ITERATIONS = 120_000


def _hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or new_id("salt")
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _HASH_ITERATIONS
    )
    return f"pbkdf2_sha256${_HASH_ITERATIONS}${salt}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)
    )
    return hmac.compare_digest(digest.hex(), expected)


def _validate_credentials(name: str, phone: str, password: str) -> None:
    if not name.strip():
        raise ValidationError("姓名不能为空", field="name")
    if not PHONE_PATTERN.match(phone):
        raise ValidationError("手机号格式不正确", field="phone")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"密码至少 {MIN_PASSWORD_LENGTH} 位", field="password")


class AccountService:
    def __init__(self, database: Database, clock: Clock) -> None:
        self._db = database
        self._clock = clock

    def register_customer(self, name: str, phone: str, password: str) -> User:
        _validate_credentials(name, phone, password)
        user_id = new_id("user")
        try:
            with UnitOfWork(self._db) as conn:
                repo = UserRepository(conn)
                if repo.get_by_phone(phone) is not None:
                    raise ConflictError("该手机号已注册", field="phone")
                repo.insert(
                    user_id=user_id,
                    name=name.strip(),
                    phone=phone,
                    password_hash=_hash_password(password),
                    role=Role.CUSTOMER,
                    store_id=None,
                    area_id=None,
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("该手机号已注册", field="phone") from exc
        return self.get_user(user_id)

    def create_staff(
        self,
        actor: Session,
        *,
        name: str,
        phone: str,
        password: str,
        role: Role,
        store_id: str | None = None,
        area_id: str | None = None,
    ) -> User:
        """员工账号只能由上级创建，不开放自助注册（REQ-036）。"""
        if role is Role.CUSTOMER:
            raise ValidationError("员工账号不能是顾客角色", field="role")
        if role is Role.FRONT_DESK:
            if actor.role is not Role.STORE_MANAGER:
                raise PermissionDenied("只有店长能创建前台账号")
            if not actor.store_id or store_id != actor.store_id:
                raise PermissionDenied("只能为本店创建前台账号")
        elif role is Role.STORE_MANAGER:
            if actor.role is not Role.AREA_MANAGER:
                raise PermissionDenied("只有片区负责人能创建店长账号")
            if not actor.area_id or area_id != actor.area_id:
                raise PermissionDenied("只能为本片区创建店长账号")
        else:
            raise PermissionDenied("该角色不能由当前账号创建")

        _validate_credentials(name, phone, password)
        user_id = new_id("user")
        try:
            with UnitOfWork(self._db) as conn:
                ensure_active(conn, actor)
                repo = UserRepository(conn)
                if repo.get_by_phone(phone) is not None:
                    raise ConflictError("该手机号已注册", field="phone")
                repo.insert(
                    user_id=user_id,
                    name=name.strip(),
                    phone=phone,
                    password_hash=_hash_password(password),
                    role=role,
                    store_id=store_id,
                    area_id=area_id,
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("该手机号已注册", field="phone") from exc
        return self.get_user(user_id)

    def bootstrap_staff(
        self,
        *,
        name: str,
        phone: str,
        password: str,
        role: Role,
        store_id: str | None = None,
        area_id: str | None = None,
    ) -> User:
        """初始化种子数据用，跳过上级审批。

        正式流程里员工账号由店长或片区负责人创建，见 `create_staff`；
        系统第一次部署时没有任何账号能扮演上级，所以留这个入口。
        """
        _validate_credentials(name, phone, password)
        user_id = new_id("user")
        try:
            with UnitOfWork(self._db) as conn:
                UserRepository(conn).insert(
                    user_id=user_id,
                    name=name.strip(),
                    phone=phone,
                    password_hash=_hash_password(password),
                    role=role,
                    store_id=store_id,
                    area_id=area_id,
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("该手机号已注册", field="phone") from exc
        return self.get_user(user_id)

    def login(self, phone: str, password: str) -> Session:
        # 登录失败次数必须落库，所以先在事务里写完再抛错：
        # 在 UnitOfWork 内部 raise 会让事务回滚，失败计数就白记了。
        error: AppError | None = None
        session: Session | None = None
        with UnitOfWork(self._db) as conn:
            repo = UserRepository(conn)
            row = repo.get_credentials(phone)
            if row is None:
                # 不区分「手机号不存在」和「密码错误」，避免被用来枚举账号。
                error = ValidationError("手机号或密码不正确", field="password")
            elif not _verify_password(password, row["password_hash"]):
                attempts = repo.bump_failed_attempts(row["id"])
                if attempts >= MAX_FAILED_ATTEMPTS:
                    locked = self._clock.now() + timedelta(minutes=LOCK_MINUTES)
                    repo.lock_until(row["id"], locked.isoformat())
                error = ValidationError("手机号或密码不正确", field="password")
            elif row["status"] == UserStatus.DISABLED.value:
                error = PermissionDenied("账号已停用")
            elif row["locked_until"] and self._clock.now().isoformat() < row["locked_until"]:
                error = PermissionDenied("账号已锁定，请稍后再试")
            else:
                repo.reset_failed_attempts(row["id"])
                session = Session(
                    user_id=row["id"],
                    name=row["name"],
                    role=Role(row["role"]),
                    store_id=row["store_id"],
                    area_id=row["area_id"],
                )
        if error is not None:
            raise error
        assert session is not None
        return session

    def get_user(self, user_id: str) -> User:
        with UnitOfWork(self._db) as conn:
            user = UserRepository(conn).get_by_id(user_id)
        if user is None:
            raise NotFound("账号不存在", field="user_id")
        return user

    def disable_user(self, actor: Session, user_id: str) -> None:
        target = self.get_user(user_id)
        if actor.role is Role.STORE_MANAGER:
            if target.store_id != actor.store_id:
                raise PermissionDenied("只能停用本店员工")
        elif actor.role is Role.AREA_MANAGER:
            if target.role is not Role.STORE_MANAGER or target.area_id != actor.area_id:
                raise PermissionDenied("只能停用本片区店长")
        else:
            raise PermissionDenied("当前角色不能停用账号")
        with UnitOfWork(self._db) as conn:
            ensure_active(conn, actor)
            UserRepository(conn).set_status(user_id, UserStatus.DISABLED)

    def list_staff_of_store(self, actor: Session, store_id: str) -> list[User]:
        self.require_store(actor, store_id)
        with UnitOfWork(self._db) as conn:
            ensure_active(conn, actor)
            if actor.role is Role.AREA_MANAGER:
                # REQ-026：片区负责人只看各店店长，不查看前台个人明细。
                store = conn.execute(
                    "SELECT area_id FROM store WHERE id = ?", (store_id,)
                ).fetchone()
                if store is None or store["area_id"] != actor.area_id:
                    raise PermissionDenied("只能查看本片区门店")
                return [
                    user
                    for user in UserRepository(conn).list_staff_of_store(store_id)
                    if user.role is Role.STORE_MANAGER
                ]
            return UserRepository(conn).list_staff_of_store(store_id)

    @staticmethod
    def require_role(session: Session, *roles: Role) -> None:
        if session.role not in roles:
            raise PermissionDenied("当前角色无权执行该操作")

    @staticmethod
    def require_store(session: Session, store_id: str) -> None:
        """店长与前台只能操作本店；片区负责人按片区放行在调用方处理。"""
        if session.role in (Role.FRONT_DESK, Role.STORE_MANAGER):
            if session.store_id != store_id:
                raise PermissionDenied("只能操作本门店的数据")
        elif session.role is not Role.AREA_MANAGER:
            raise PermissionDenied("当前角色无权访问门店数据")
