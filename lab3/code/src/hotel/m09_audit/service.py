"""审计与数据保留的服务层。

日志查询按角色数据范围过滤；删除原始数据必须由片区负责人审批，
审批通过后删除并留下一条删除记录（REQ-014、REQ-030）。
"""

from __future__ import annotations

import sqlite3
from datetime import date

from hotel.core.audit import record_audit
from hotel.core.auth import ensure_active
from hotel.core.clock import Clock
from hotel.core.db import Database, UnitOfWork
from hotel.core.errors import ConflictError, NotFound, PermissionDenied, ValidationError
from hotel.core.ids import new_id
from hotel.m01_account.model import Role, Session
from hotel.m09_audit.model import (
    RETENTION_YEARS,
    AuditEntry,
    DeletionRequest,
    DeletionStatus,
)
from hotel.m09_audit.repository import AuditRepository

DELETABLE_TYPES = ("order", "review")


class AuditService:
    def __init__(self, database: Database, clock: Clock) -> None:
        self._db = database
        self._clock = clock

    def query_audit(
        self, actor: Session, *, action: str | None = None, limit: int = 100
    ) -> list[AuditEntry]:
        scope, params = self._scope_of(actor)
        with UnitOfWork(self._db) as conn:
            return AuditRepository(conn).list_entries(scope, params, action, limit)

    def request_deletion(
        self, actor: Session, *, object_type: str, object_id: str, reason: str
    ) -> DeletionRequest:
        if actor.role is not Role.STORE_MANAGER:
            raise PermissionDenied("只有店长能提交删除申请")
        if object_type not in DELETABLE_TYPES:
            raise ValidationError("该类型数据不支持在线删除", field="object_type")
        if not reason.strip():
            raise ValidationError("请填写删除原因", field="reason")
        with UnitOfWork(self._db) as conn:
            ensure_active(conn, actor)
            row = conn.execute(
                "SELECT area_id FROM store WHERE id = ?", (actor.store_id,)
            ).fetchone()
            if row is None:
                raise NotFound("门店不存在", field="store_id")
            request = DeletionRequest(
                id=new_id("del"),
                area_id=row["area_id"],
                object_type=object_type,
                object_id=object_id,
                reason=reason.strip(),
                applicant=actor.user_id,
                approver=None,
                status=DeletionStatus.PENDING,
            )
            AuditRepository(conn).insert_deletion_request(request)
        return request

    def approve_deletion(self, actor: Session, request_id: str) -> DeletionRequest:
        if actor.role is not Role.AREA_MANAGER:
            raise PermissionDenied("只有片区负责人能审批删除申请")
        with UnitOfWork(self._db) as conn:
            ensure_active(conn, actor)
            repo = AuditRepository(conn)
            request = repo.get_deletion_request(request_id)
            if request is None:
                raise NotFound("删除申请不存在", field="request_id")
            if request.area_id != actor.area_id:
                raise PermissionDenied("只能审批本片区的删除申请")
            if request.status is not DeletionStatus.PENDING:
                raise ConflictError("该申请已处理过了", field="request_id")
            store_id = None
            if request.object_type == "order":
                row = conn.execute(
                    "SELECT store_id FROM orders WHERE id = ?", (request.object_id,)
                ).fetchone()
                store_id = row["store_id"] if row else None
            self._delete_target(conn, request.object_type, request.object_id)
            repo.set_deletion_status(request_id, DeletionStatus.APPROVED, actor.user_id)
            # 对象已被删除，日志的门店归属只能由调用方传入。
            record_audit(
                conn,
                operator_id=actor.user_id,
                operator_role=actor.role.value,
                action="DATA_DELETED",
                object_type=request.object_type,
                object_id=request.object_id,
                reason=request.reason,
                moment=self._clock.now(),
                store_id=store_id,
            )
            updated = repo.get_deletion_request(request_id)
        assert updated is not None
        return updated

    def reject_deletion(self, actor: Session, request_id: str) -> DeletionRequest:
        if actor.role is not Role.AREA_MANAGER:
            raise PermissionDenied("只有片区负责人能审批删除申请")
        with UnitOfWork(self._db) as conn:
            ensure_active(conn, actor)
            repo = AuditRepository(conn)
            request = repo.get_deletion_request(request_id)
            if request is None:
                raise NotFound("删除申请不存在", field="request_id")
            if request.area_id != actor.area_id:
                raise PermissionDenied("只能审批本片区的删除申请")
            if request.status is not DeletionStatus.PENDING:
                raise ConflictError("该申请已处理过了", field="request_id")
            repo.set_deletion_status(request_id, DeletionStatus.REJECTED, actor.user_id)
            updated = repo.get_deletion_request(request_id)
        assert updated is not None
        return updated

    def list_deletion_requests(self, actor: Session) -> list[DeletionRequest]:
        if actor.role is not Role.AREA_MANAGER:
            raise PermissionDenied("只有片区负责人能查看删除申请")
        with UnitOfWork(self._db) as conn:
            return AuditRepository(conn).list_deletion_requests(actor.area_id)

    def retention_summary(self, actor: Session) -> dict[str, int]:
        """超过 3 年保留期的记录条数。只统计，不自动清理。"""
        if actor.role is not Role.AREA_MANAGER:
            raise PermissionDenied("只有片区负责人能查看保留策略执行情况")
        cutoff = date(self._clock.today().year - RETENTION_YEARS, 1, 1).isoformat()
        with UnitOfWork(self._db) as conn:
            repo = AuditRepository(conn)
            return {
                "orders": repo.count_older_than("orders", "created_at", cutoff),
                "payment": repo.count_older_than("payment", "created_at", cutoff),
                "refund": repo.count_older_than("refund", "refunded_at", cutoff),
                "audit_log": repo.count_older_than("audit_log", "created_at", cutoff),
            }

    @staticmethod
    def _delete_target(conn: sqlite3.Connection, object_type: str, object_id: str) -> None:
        repo = AuditRepository(conn)
        if object_type == "order":
            repo.delete_order(object_id)
        elif object_type == "review":
            conn.execute("DELETE FROM review WHERE id = ?", (object_id,))
        else:
            raise ValidationError("该类型数据不支持在线删除", field="object_type")

    @staticmethod
    def _scope_of(actor: Session) -> tuple[str, tuple]:
        if actor.role is Role.FRONT_DESK:
            return "operator_id = ?", (actor.user_id,)
        if actor.role is Role.STORE_MANAGER:
            return "store_id = ?", (actor.store_id,)
        if actor.role is Role.AREA_MANAGER:
            return (
                "store_id IN (SELECT id FROM store WHERE area_id = ?)",
                (actor.area_id,),
            )
        if actor.role is Role.CUSTOMER:
            return (
                "object_type = 'order' AND object_id IN"
                " (SELECT id FROM orders WHERE customer_id = ?)",
                (actor.user_id,),
            )
        raise PermissionDenied("当前角色不能查看操作日志")
