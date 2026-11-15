"""M1 账号与权限的规则。"""

from __future__ import annotations

import pytest

from hotel.core.clock import FakeClock
from hotel.core.errors import ConflictError, PermissionDenied, ValidationError
from hotel.m01_account.model import Role
from hotel.m01_account.service import AccountService
from hotel.m02_store.service import StoreService


@pytest.fixture
def scene(store_service: StoreService, account_service: AccountService) -> dict:
    area = store_service.create_area("南京片区")
    store_a = store_service.create_store(area.id, "新街口店", "南京", "新街口")
    store_b = store_service.create_store(area.id, "河西店", "南京", "河西")
    account_service.bootstrap_staff(
        name="片区负责人",
        phone="13900000001",
        password="secret1",
        role=Role.AREA_MANAGER,
        area_id=area.id,
    )
    account_service.bootstrap_staff(
        name="新街口店长",
        phone="13900000002",
        password="secret1",
        role=Role.STORE_MANAGER,
        store_id=store_a.id,
    )
    account_service.bootstrap_staff(
        name="河西店长",
        phone="13900000003",
        password="secret1",
        role=Role.STORE_MANAGER,
        store_id=store_b.id,
    )
    account_service.bootstrap_staff(
        name="新街口前台",
        phone="13900000004",
        password="secret1",
        role=Role.FRONT_DESK,
        store_id=store_a.id,
    )
    return {
        "area": area,
        "store_a": store_a,
        "store_b": store_b,
        "area_manager": account_service.login("13900000001", "secret1"),
        "manager_a": account_service.login("13900000002", "secret1"),
        "manager_b": account_service.login("13900000003", "secret1"),
        "front_a": account_service.login("13900000004", "secret1"),
    }


def test_customer_register_and_login(account_service: AccountService) -> None:
    user = account_service.register_customer("张三", "13800000001", "secret1")
    session = account_service.login("13800000001", "secret1")

    assert user.role is Role.CUSTOMER
    assert session.user_id == user.id
    assert session.store_id is None


def test_duplicate_phone_rejected(account_service: AccountService) -> None:
    account_service.register_customer("张三", "13800000001", "secret1")

    with pytest.raises(ConflictError):
        account_service.register_customer("李四", "13800000001", "secret1")


def test_invalid_registration_input(account_service: AccountService) -> None:
    with pytest.raises(ValidationError):
        account_service.register_customer("张三", "12345", "secret1")
    with pytest.raises(ValidationError):
        account_service.register_customer("张三", "13800000001", "123")
    with pytest.raises(ValidationError):
        account_service.register_customer("  ", "13800000001", "secret1")


def test_wrong_password_locks_account_then_unlocks(
    account_service: AccountService, clock: FakeClock
) -> None:
    account_service.register_customer("张三", "13800000001", "secret1")
    for _ in range(5):
        with pytest.raises(ValidationError):
            account_service.login("13800000001", "wrong")

    with pytest.raises(PermissionDenied):
        account_service.login("13800000001", "secret1")

    clock.advance(minutes=16)
    assert account_service.login("13800000001", "secret1").name == "张三"


def test_disabled_account_cannot_login(account_service: AccountService, scene: dict) -> None:
    front = scene["front_a"]
    account_service.disable_user(scene["manager_a"], front.user_id)

    with pytest.raises(PermissionDenied):
        account_service.login("13900000004", "secret1")


def test_staff_accounts_created_only_by_superior(
    account_service: AccountService, scene: dict
) -> None:
    manager_a = scene["manager_a"]
    area_manager = scene["area_manager"]

    created = account_service.create_staff(
        manager_a,
        name="新前台",
        phone="13900000011",
        password="secret1",
        role=Role.FRONT_DESK,
        store_id=scene["store_a"].id,
    )
    assert created.store_id == scene["store_a"].id

    with pytest.raises(PermissionDenied):
        account_service.create_staff(
            manager_a,
            name="别店前台",
            phone="13900000012",
            password="secret1",
            role=Role.FRONT_DESK,
            store_id=scene["store_b"].id,
        )
    with pytest.raises(PermissionDenied):
        account_service.create_staff(
            manager_a,
            name="店长",
            phone="13900000013",
            password="secret1",
            role=Role.STORE_MANAGER,
            area_id=scene["area"].id,
        )

    new_manager = account_service.create_staff(
        area_manager,
        name="新店长",
        phone="13900000014",
        password="secret1",
        role=Role.STORE_MANAGER,
        area_id=scene["area"].id,
    )
    assert new_manager.role is Role.STORE_MANAGER


def test_store_scope_is_enforced(account_service: AccountService, scene: dict) -> None:
    staff = account_service.list_staff_of_store(scene["manager_a"], scene["store_a"].id)
    assert {user.name for user in staff} >= {"新街口店长", "新街口前台"}

    with pytest.raises(PermissionDenied):
        account_service.list_staff_of_store(scene["front_a"], scene["store_b"].id)


def test_customer_cannot_access_store_data(account_service: AccountService, scene: dict) -> None:
    account_service.register_customer("张三", "13800000001", "secret1")
    customer = account_service.login("13800000001", "secret1")

    with pytest.raises(PermissionDenied):
        account_service.list_staff_of_store(customer, scene["store_a"].id)


def test_area_manager_sees_only_store_managers(
    account_service: AccountService, scene: dict
) -> None:
    """REQ-026：片区负责人可看各店店长，不查看前台个人明细。"""
    staff = account_service.list_staff_of_store(scene["area_manager"], scene["store_a"].id)

    assert [user.role for user in staff] == [Role.STORE_MANAGER]


def test_area_manager_can_disable_store_manager_of_own_area(
    account_service: AccountService, scene: dict
) -> None:
    """店长只绑门店，片区要通过门店反查，否则片区负责人永远停用不了店长。"""
    account_service.disable_user(scene["area_manager"], scene["manager_b"].user_id)

    with pytest.raises(PermissionDenied):
        account_service.login("13900000003", "secret1")


def test_disabled_session_loses_access_immediately(
    account_service: AccountService, scene: dict
) -> None:
    """REQ-001：账号停用后，已经登录的会话也要立刻失效。"""
    front = scene["front_a"]
    account_service.disable_user(scene["manager_a"], front.user_id)

    with pytest.raises(PermissionDenied):
        account_service.list_staff_of_store(front, scene["store_a"].id)
