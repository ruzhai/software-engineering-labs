"""审计日志条目与删除申请。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

RETENTION_YEARS = 3


class DeletionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class AuditEntry:
    id: str
    operator_id: str
    operator_role: str
    action: str
    object_type: str
    object_id: str
    before_value: str | None
    after_value: str | None
    reason: str | None
    source: str | None
    created_at: datetime


@dataclass(frozen=True)
class DeletionRequest:
    id: str
    area_id: str
    object_type: str
    object_id: str
    reason: str
    applicant: str
    approver: str | None
    status: DeletionStatus
