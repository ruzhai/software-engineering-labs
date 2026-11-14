"""定价的服务层。"""

from __future__ import annotations

from datetime import date

from hotel.core.db import Database, UnitOfWork
from hotel.core.errors import ConflictError, NotFound, PermissionDenied, ValidationError
from hotel.core.ids import new_id
from hotel.m01_account.model import Role, Session
from hotel.m03_pricing.model import (
    ChangeRequestStatus,
    DailyPrice,
    PriceChangeRequest,
    PriceRange,
    PriceSource,
)
from hotel.m03_pricing.repository import PricingRepository


class PricingService:
    def __init__(self, database: Database) -> None:
        self._db = database

    def set_price_range(
        self,
        actor: Session,
        *,
        store_id: str,
        effective_date: date,
        min_cents: int,
        max_cents: int,
    ) -> PriceRange:
        if actor.role is not Role.AREA_MANAGER:
            raise PermissionDenied("只有片区负责人能下发价格区间")
        if min_cents < 0 or max_cents < min_cents:
            raise ValidationError("价格区间不合法", field="range")
        with UnitOfWork(self._db) as conn:
            repo = PricingRepository(conn)
            area_id = repo.area_of_store(store_id)
            if area_id is None:
                raise NotFound("门店不存在", field="store_id")
            if actor.area_id != area_id:
                raise PermissionDenied("只能向本片区门店下发价格区间")
            price_range = PriceRange(
                id=new_id("pr"),
                store_id=store_id,
                effective_date=effective_date,
                min_cents=min_cents,
                max_cents=max_cents,
            )
            repo.insert_price_range(price_range)
        return price_range

    def get_price(self, room_type_id: str, on_date: date) -> DailyPrice:
        with UnitOfWork(self._db) as conn:
            price = PricingRepository(conn).get_price(room_type_id, on_date)
        if price is None:
            raise NotFound(f"{on_date} 尚未设置房价", field="price_date")
        return price

    def set_price(
        self,
        actor: Session,
        *,
        room_type_id: str,
        on_date: date,
        price_cents: int,
        source: PriceSource = PriceSource.MANAGER,
    ) -> DailyPrice:
        if actor.role is not Role.STORE_MANAGER:
            raise PermissionDenied("只有店长能改价")
        with UnitOfWork(self._db) as conn:
            repo = PricingRepository(conn)
            store_id = repo.store_of_room_type(room_type_id)
            if store_id is None:
                raise NotFound("房型不存在", field="room_type_id")
            if store_id != actor.store_id:
                raise PermissionDenied("只能修改本店房价")
            self._check_within_range(repo, store_id, on_date, price_cents)
            repo.upsert_price(room_type_id, on_date, price_cents, source)
            price = repo.get_price(room_type_id, on_date)
        assert price is not None
        return price

    def request_price_change(
        self,
        actor: Session,
        *,
        room_type_id: str,
        on_date: date,
        new_cents: int,
    ) -> PriceChangeRequest:
        """前台只能提交改价申请，由店长审批后才生效（REQ-006）。"""
        if actor.role is not Role.FRONT_DESK:
            raise PermissionDenied("只有前台能提交改价申请")
        with UnitOfWork(self._db) as conn:
            repo = PricingRepository(conn)
            store_id = repo.store_of_room_type(room_type_id)
            if store_id is None:
                raise NotFound("房型不存在", field="room_type_id")
            if store_id != actor.store_id:
                raise PermissionDenied("只能提交本店房型的改价申请")
            self._check_within_range(repo, store_id, on_date, new_cents)
            current = repo.get_price(room_type_id, on_date)
            if current is None:
                raise NotFound(f"{on_date} 尚未设置房价，无法提交改价申请", field="price_date")
            request = PriceChangeRequest(
                id=new_id("pcr"),
                room_type_id=room_type_id,
                price_date=on_date,
                old_cents=current.price_cents,
                new_cents=new_cents,
                applicant=actor.user_id,
                approver=None,
                status=ChangeRequestStatus.PENDING,
            )
            repo.insert_request(request)
        return request

    def approve_price_change(self, actor: Session, request_id: str) -> None:
        self._decide(actor, request_id, approve=True)

    def reject_price_change(self, actor: Session, request_id: str) -> None:
        self._decide(actor, request_id, approve=False)

    def list_pending_requests(self, actor: Session, store_id: str) -> list[PriceChangeRequest]:
        if actor.role is not Role.STORE_MANAGER or actor.store_id != store_id:
            raise PermissionDenied("只有本店店长能查看改价申请")
        with UnitOfWork(self._db) as conn:
            return PricingRepository(conn).list_pending_requests(store_id)

    def _decide(self, actor: Session, request_id: str, *, approve: bool) -> None:
        if actor.role is not Role.STORE_MANAGER:
            raise PermissionDenied("只有店长能审批改价申请")
        with UnitOfWork(self._db) as conn:
            repo = PricingRepository(conn)
            request = repo.get_request(request_id)
            if request is None:
                raise NotFound("改价申请不存在", field="request_id")
            store_id = repo.store_of_room_type(request.room_type_id)
            if store_id != actor.store_id:
                raise PermissionDenied("只能审批本店的改价申请")
            if request.status is not ChangeRequestStatus.PENDING:
                raise ConflictError("该申请已处理过了", field="request_id")
            if approve:
                self._check_within_range(repo, store_id, request.price_date, request.new_cents)
                repo.upsert_price(
                    request.room_type_id,
                    request.price_date,
                    request.new_cents,
                    PriceSource.APPROVED_REQUEST,
                )
                repo.set_request_status(request_id, ChangeRequestStatus.APPROVED, actor.user_id)
            else:
                repo.set_request_status(request_id, ChangeRequestStatus.REJECTED, actor.user_id)

    @staticmethod
    def _check_within_range(
        repo: PricingRepository, store_id: str, on_date: date, price_cents: int
    ) -> None:
        if price_cents < 0:
            raise ValidationError("价格不能为负", field="price")
        price_range = repo.latest_range(store_id, on_date)
        if price_range is None:
            raise ValidationError("平台尚未下发价格区间", field="price")
        if not price_range.min_cents <= price_cents <= price_range.max_cents:
            low = price_range.min_cents / 100
            high = price_range.max_cents / 100
            raise ValidationError(f"价格需在 {low:.2f} 元到 {high:.2f} 元之间", field="price")
