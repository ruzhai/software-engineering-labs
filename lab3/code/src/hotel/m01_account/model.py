"""账号、角色与会话。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    CUSTOMER = "CUSTOMER"
    FRONT_DESK = "FRONT_DESK"
    STORE_MANAGER = "STORE_MANAGER"
    AREA_MANAGER = "AREA_MANAGER"


class UserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


@dataclass(frozen=True)
class User:
    id: str
    name: str
    phone: str
    role: Role
    status: UserStatus
    store_id: str | None
    area_id: str | None


@dataclass(frozen=True)
class Session:
    """登录后的身份。业务方法用它做角色与数据范围校验。"""

    user_id: str
    name: str
    role: Role
    store_id: str | None
    area_id: str | None
