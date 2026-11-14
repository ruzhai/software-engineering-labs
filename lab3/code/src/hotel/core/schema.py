"""建表语句。

一张表对应实验二类图里的一个类。类属性与列名一一对应，只有两处例外：
- `room_type` 不存「房间总数」，改由房间数实时统计，避免与真实房间数量不一致。
- 类图没画、但 REQ-010 需要的请求号台账单独建 `request_ledger`。

金额列一律以 `_cents` 结尾，存整数分；日期存 `YYYY-MM-DD`，时间存 ISO 字符串。
"""

from __future__ import annotations

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS area (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS store (
        id TEXT PRIMARY KEY,
        area_id TEXT NOT NULL REFERENCES area(id),
        name TEXT NOT NULL,
        city TEXT NOT NULL,
        district TEXT NOT NULL,
        status TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS user (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        phone TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        status TEXT NOT NULL,
        store_id TEXT REFERENCES store(id),
        area_id TEXT REFERENCES area(id),
        failed_attempts INTEGER NOT NULL DEFAULT 0,
        locked_until TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS shift (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES user(id),
        store_id TEXT NOT NULL REFERENCES store(id),
        work_date TEXT NOT NULL,
        shift_type TEXT NOT NULL,
        clock_in TEXT,
        clock_out TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS room_type (
        id TEXT PRIMARY KEY,
        store_id TEXT NOT NULL REFERENCES store(id),
        name TEXT NOT NULL,
        bed_type TEXT NOT NULL,
        max_guests INTEGER NOT NULL,
        is_listed INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS room (
        id TEXT PRIMARY KEY,
        room_type_id TEXT NOT NULL REFERENCES room_type(id),
        room_no TEXT NOT NULL,
        status TEXT NOT NULL,
        repair_until TEXT,
        UNIQUE (room_type_id, room_no)
    )""",
    """CREATE TABLE IF NOT EXISTS daily_price (
        room_type_id TEXT NOT NULL REFERENCES room_type(id),
        price_date TEXT NOT NULL,
        price_cents INTEGER NOT NULL,
        source TEXT NOT NULL,
        PRIMARY KEY (room_type_id, price_date)
    )""",
    """CREATE TABLE IF NOT EXISTS price_range (
        id TEXT PRIMARY KEY,
        store_id TEXT NOT NULL REFERENCES store(id),
        effective_date TEXT NOT NULL,
        min_cents INTEGER NOT NULL,
        max_cents INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS price_change_request (
        id TEXT PRIMARY KEY,
        room_type_id TEXT NOT NULL REFERENCES room_type(id),
        price_date TEXT NOT NULL,
        old_cents INTEGER NOT NULL,
        new_cents INTEGER NOT NULL,
        applicant TEXT NOT NULL,
        approver TEXT,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS daily_inventory (
        room_type_id TEXT NOT NULL REFERENCES room_type(id),
        inv_date TEXT NOT NULL,
        online_limit INTEGER NOT NULL DEFAULT 0,
        online_sold INTEGER NOT NULL DEFAULT 0,
        offline_reserved INTEGER NOT NULL DEFAULT 0,
        offline_sold INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (room_type_id, inv_date)
    )""",
    """CREATE TABLE IF NOT EXISTS orders (
        id TEXT PRIMARY KEY,
        order_no TEXT NOT NULL UNIQUE,
        request_no TEXT NOT NULL,
        customer_id TEXT NOT NULL REFERENCES user(id),
        store_id TEXT NOT NULL REFERENCES store(id),
        status TEXT NOT NULL,
        total_cents INTEGER NOT NULL,
        pay_deadline TEXT NOT NULL,
        check_in_date TEXT NOT NULL,
        check_out_date TEXT NOT NULL,
        room_id TEXT REFERENCES room(id),
        created_at TEXT NOT NULL,
        checked_in_at TEXT,
        checked_out_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS order_item (
        id TEXT PRIMARY KEY,
        order_id TEXT NOT NULL REFERENCES orders(id),
        room_type_id TEXT NOT NULL REFERENCES room_type(id),
        stay_date TEXT NOT NULL,
        qty INTEGER NOT NULL,
        unit_price_cents INTEGER NOT NULL,
        subtotal_cents INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS cancel_request (
        id TEXT PRIMARY KEY,
        order_id TEXT NOT NULL REFERENCES orders(id),
        reason TEXT NOT NULL,
        applicant TEXT NOT NULL,
        approver TEXT,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS upgrade_request (
        id TEXT PRIMARY KEY,
        order_id TEXT NOT NULL REFERENCES orders(id),
        diff_cents INTEGER NOT NULL,
        applicant TEXT NOT NULL,
        approver TEXT,
        status TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS payment (
        id TEXT PRIMARY KEY,
        pay_no TEXT NOT NULL UNIQUE,
        order_id TEXT NOT NULL REFERENCES orders(id),
        amount_cents INTEGER NOT NULL,
        channel TEXT NOT NULL,
        txn_id TEXT,
        status TEXT NOT NULL,
        paid_at TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS refund (
        id TEXT PRIMARY KEY,
        refund_no TEXT NOT NULL UNIQUE,
        order_id TEXT NOT NULL REFERENCES orders(id),
        payment_id TEXT NOT NULL REFERENCES payment(id),
        amount_cents INTEGER NOT NULL,
        reason TEXT NOT NULL,
        status TEXT NOT NULL,
        refunded_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS reconciliation (
        id TEXT PRIMARY KEY,
        payment_id TEXT NOT NULL REFERENCES payment(id),
        rec_date TEXT NOT NULL,
        diff_type TEXT NOT NULL,
        diff_cents INTEGER NOT NULL,
        resolution TEXT,
        status TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS occupancy (
        id TEXT PRIMARY KEY,
        order_id TEXT NOT NULL REFERENCES orders(id),
        room_id TEXT NOT NULL REFERENCES room(id),
        stay_date TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS work_order (
        id TEXT PRIMARY KEY,
        room_id TEXT NOT NULL REFERENCES room(id),
        type TEXT NOT NULL,
        reason TEXT NOT NULL,
        involved_date TEXT NOT NULL,
        status TEXT NOT NULL,
        submitter TEXT NOT NULL,
        executor TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS review (
        id TEXT PRIMARY KEY,
        order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),
        score INTEGER NOT NULL,
        content TEXT NOT NULL,
        submitted_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PUBLISHED'
    )""",
    """CREATE TABLE IF NOT EXISTS audit_log (
        id TEXT PRIMARY KEY,
        operator_id TEXT NOT NULL,
        operator_role TEXT NOT NULL,
        action TEXT NOT NULL,
        object_type TEXT NOT NULL,
        object_id TEXT NOT NULL,
        before_value TEXT,
        after_value TEXT,
        reason TEXT,
        source TEXT,
        store_id TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS deletion_request (
        id TEXT PRIMARY KEY,
        area_id TEXT NOT NULL REFERENCES area(id),
        object_type TEXT NOT NULL,
        object_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        applicant TEXT NOT NULL,
        approver TEXT,
        status TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS store_performance (
        id TEXT PRIMARY KEY,
        store_id TEXT NOT NULL REFERENCES store(id),
        period TEXT NOT NULL,
        order_count INTEGER NOT NULL,
        occupancy_rate REAL NOT NULL,
        avg_score REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS notification (
        id TEXT PRIMARY KEY,
        order_id TEXT REFERENCES orders(id),
        type TEXT NOT NULL,
        channel TEXT NOT NULL,
        status TEXT NOT NULL,
        failure_reason TEXT,
        retry_count INTEGER NOT NULL DEFAULT 0,
        sent_at TEXT,
        payload TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS request_ledger (
        request_no TEXT PRIMARY KEY,
        created_at TEXT NOT NULL
    )""",
)
