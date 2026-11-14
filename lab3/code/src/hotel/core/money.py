"""金额换算。

库里一律存整数分。用 Decimal 解析用户输入的元，避免 0.1 + 0.2 这类误差。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from hotel.core.errors import ValidationError


def yuan_to_cents(value: str | int | Decimal) -> int:
    try:
        amount = Decimal(str(value))
    except Exception as exc:  # noqa: BLE001 - 统一转成业务错误
        raise ValidationError("金额格式不正确", field="amount") from exc
    if amount < 0:
        raise ValidationError("金额不能为负", field="amount")
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cents_to_yuan(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def format_cents(cents: int) -> str:
    return f"¥{cents_to_yuan(cents)}"
