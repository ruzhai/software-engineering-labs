"""演示数据。

`python -m hotel.seed` 会重建数据库并写入一个片区、两家门店、四类账号、
房型与房间、未来两周房价。密码统一为 secret1，仅供本地演示。
"""

from __future__ import annotations

from datetime import date, timedelta

from hotel.context import DEFAULT_DB_PATH, build_services
from hotel.m01_account.model import Role

DEMO_PASSWORD = "secret1"


def main() -> None:
    path = DEFAULT_DB_PATH
    for suffix in ("", "-wal", "-shm"):
        candidate = path.with_name(path.name + suffix) if suffix else path
        if candidate.exists():
            candidate.unlink()

    services = build_services(path)
    area = services.store.create_area("南京片区")
    xinjiekou = services.store.create_store(area.id, "新街口店", "南京", "新街口")
    hexi = services.store.create_store(area.id, "河西店", "南京", "河西")

    services.account.bootstrap_staff(
        name="片区负责人",
        phone="13900000001",
        password=DEMO_PASSWORD,
        role=Role.AREA_MANAGER,
        area_id=area.id,
    )
    for name, phone, store_id in (
        ("新街口店长", "13900000002", xinjiekou.id),
        ("新街口前台", "13900000003", xinjiekou.id),
        ("河西店长", "13900000004", hexi.id),
        ("河西前台", "13900000005", hexi.id),
    ):
        role = Role.STORE_MANAGER if "店长" in name else Role.FRONT_DESK
        services.account.bootstrap_staff(
            name=name, phone=phone, password=DEMO_PASSWORD, role=role, store_id=store_id
        )
    services.account.register_customer("张三", "13800000001", DEMO_PASSWORD)

    area_manager = services.account.login("13900000001", DEMO_PASSWORD)
    for store_id in (xinjiekou.id, hexi.id):
        services.pricing.set_price_range(
            area_manager,
            store_id=store_id,
            effective_date=date.today() - timedelta(days=30),
            min_cents=20000,
            max_cents=120000,
        )

    catalog = (
        (xinjiekou.id, "大床房", "大床", 2, 10, 50000, "13900000002"),
        (xinjiekou.id, "双床房", "双床", 2, 6, 60000, "13900000002"),
        (hexi.id, "商务大床房", "大床", 2, 8, 55000, "13900000004"),
        (hexi.id, "家庭房", "三床", 4, 4, 80000, "13900000004"),
    )
    managers = {
        phone: services.account.login(phone, DEMO_PASSWORD)
        for phone in {entry[6] for entry in catalog}
    }
    today = date.today()
    for index, (store_id, name, bed, guests, rooms, price, manager_phone) in enumerate(
        catalog, start=1
    ):
        room_type = services.store.create_room_type(store_id, name, bed, guests)
        services.store.add_rooms(
            room_type.id, [f"{index}{number:02d}" for number in range(1, rooms + 1)]
        )
        services.pricing.set_prices(
            managers[manager_phone],
            room_type_id=room_type.id,
            start=today - timedelta(days=1),
            end=today + timedelta(days=14),
            price_cents=price,
        )

    print(f"数据库：{path.resolve()}")
    print("演示账号（密码均为 secret1）：")
    print("  AREA_MANAGER   13900000001  片区负责人")
    print("  STORE_MANAGER  13900000002  新街口店长")
    print("  FRONT_DESK     13900000003  新街口前台")
    print("  STORE_MANAGER  13900000004  河西店长")
    print("  FRONT_DESK     13900000005  河西前台")
    print("  CUSTOMER       13800000001  张三")


if __name__ == "__main__":
    main()
