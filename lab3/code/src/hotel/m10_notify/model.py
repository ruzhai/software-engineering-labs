"""通知记录与渠道。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol


class NotificationStatus(str, Enum):
    SENT = "SENT"
    FAILED = "FAILED"
    GIVE_UP = "GIVE_UP"


class Channel(str, Enum):
    SMS = "SMS"
    INBOX = "INBOX"


@dataclass(frozen=True)
class Notification:
    id: str
    order_id: str | None
    type: str
    channel: Channel
    status: NotificationStatus
    failure_reason: str | None
    retry_count: int
    sent_at: datetime | None
    payload: str


class NotificationChannel(Protocol):
    def send(self, phone: str, text: str) -> None:
        """发送失败时抛异常。"""
