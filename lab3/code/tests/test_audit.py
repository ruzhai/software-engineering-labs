"""M9 审计日志范围与删除审批。"""

from __future__ import annotations

from datetime import date

import pytest

from hotel.core.errors import ConflictError, NotFound, PermissionDenied, ValidationError
from hotel.m05_order.service import OrderService, RoomRequest
from hotel.m09_audit.model import DeletionStatus
from hotel.m09_audit.service import AuditService

CHECK_IN = date(2026, 11, 20)
CHECK_OUT = date(2026, 11, 21)


def _cancelled_order(shop: dict, order_service: OrderService, request_no: str):
    order = order_service.create_order(
        shop["customer"],
        store_id=shop["store"].id,
        request_no=request_no,
        items=[RoomRequest(shop["room_type"].id, 1)],
        check_in=CHECK_IN,
        check_out=CHECK_OUT,
    )
    order_service.cancel_order(shop["customer"], order.id, "行程有变")
    return order


def test_cancel_writes_audit_log(
    shop: dict, order_service: OrderService, audit_service: AuditService
) -> None:
    order = _cancelled_order(shop, order_service, "audit-1")

    entries = audit_service.query_audit(shop["manager"], action="ORDER_CANCELLED")

    assert any(entry.object_id == order.id for entry in entries)
    assert all(entry.operator_role == "CUSTOMER" for entry in entries)


def test_audit_scope_per_role(
    shop: dict, order_service: OrderService, audit_service: AuditService
) -> None:
    _cancelled_order(shop, order_service, "audit-2")

    customer_entries = audit_service.query_audit(shop["customer"])
    assert customer_entries, "顾客应能看到自己订单的日志"

    front_entries = audit_service.query_audit(shop["front"])
    assert front_entries == []

    manager_entries = audit_service.query_audit(shop["manager"])
    assert manager_entries, "店长应能看到本店员工的日志"

    area_entries = audit_service.query_audit(shop["area_manager"])
    assert area_entries, "片区负责人应能看到本片区日志"


def test_deletion_request_needs_area_manager_approval(
    shop: dict,
    order_service: OrderService,
    audit_service: AuditService,
) -> None:
    order = _cancelled_order(shop, order_service, "audit-del")

    request = audit_service.request_deletion(
        shop["manager"], object_type="order", object_id=order.id, reason="顾客要求删除"
    )
    assert request.status is DeletionStatus.PENDING

    with pytest.raises(PermissionDenied):
        audit_service.approve_deletion(shop["manager"], request.id)

    approved = audit_service.approve_deletion(shop["area_manager"], request.id)
    assert approved.status is DeletionStatus.APPROVED

    with pytest.raises(NotFound):
        order_service.get_order(shop["customer"], order.id)

    entries = audit_service.query_audit(shop["area_manager"], action="DATA_DELETED")
    assert any(entry.object_id == order.id for entry in entries)


def test_deletion_rejects_unsupported_types(shop: dict, audit_service: AuditService) -> None:
    with pytest.raises(ValidationError):
        audit_service.request_deletion(
            shop["manager"], object_type="payment", object_id="x", reason="随便删"
        )


def test_reject_deletion_keeps_data(
    shop: dict, order_service: OrderService, audit_service: AuditService
) -> None:
    order = _cancelled_order(shop, order_service, "audit-reject")
    request = audit_service.request_deletion(
        shop["manager"], object_type="order", object_id=order.id, reason="测试"
    )

    rejected = audit_service.reject_deletion(shop["area_manager"], request.id)

    assert rejected.status is DeletionStatus.REJECTED
    assert order_service.get_order(shop["customer"], order.id).id == order.id

    with pytest.raises(ConflictError):
        audit_service.approve_deletion(shop["area_manager"], request.id)


def test_retention_summary(shop: dict, audit_service: AuditService) -> None:
    summary = audit_service.retention_summary(shop["area_manager"])

    assert set(summary) == {"orders", "payment", "refund", "audit_log"}
    assert all(isinstance(value, int) for value in summary.values())
