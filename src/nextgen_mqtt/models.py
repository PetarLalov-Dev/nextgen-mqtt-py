"""Data models for MQTT messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .helix import HelixMeta


class TopicType(Enum):
    """Types of MQTT topics."""

    COMMAND = "c"
    RESPONSE = "r"
    EVENT = "e"
    CONFIG = "cf"
    CONFIG_DESIRED = "cd"
    CONFIG_DESIRED_RESP = "cdr"
    STATUS = "s"
    INFO = "i"
    UNKNOWN = "unknown"

    @classmethod
    def from_topic(cls, topic: str) -> "TopicType":
        """Parse topic type from full topic string.

        Args:
            topic: Full topic string like "2530295/s" or "2530295/cf/something"

        Returns:
            TopicType enum value.
        """
        parts = topic.split("/")
        if len(parts) < 2:
            return cls.UNKNOWN

        topic_prefix = parts[1]
        for member in cls:
            if member.value == topic_prefix:
                return member
        return cls.UNKNOWN


@dataclass
class MQTTMessage:
    """Represents an MQTT message received from the WebSocket."""

    topic: str
    payload: bytes
    received_at: datetime
    qos: int = 1
    helix: HelixMeta | None = field(default=None, repr=False)

    @property
    def topic_type(self) -> TopicType:
        """Get the type of this message's topic."""
        return TopicType.from_topic(self.topic)

    @property
    def device_serial(self) -> str | None:
        """Extract device serial from topic."""
        parts = self.topic.split("/")
        return parts[0] if parts else None

    @property
    def sub_topic(self) -> str | None:
        """Get the sub-topic portion after the topic type.

        For "2530295/cf/zone/1", returns "zone/1".
        """
        parts = self.topic.split("/", 2)
        return parts[2] if len(parts) > 2 else None

    def payload_str(self, encoding: str = "utf-8") -> str:
        """Get payload as string."""
        return self.payload.decode(encoding)

    def payload_json(self) -> Any:
        """Parse payload as JSON."""
        import json

        return json.loads(self.payload)


@dataclass
class ConnectionState:
    """Represents the connection state."""

    connected: bool
    device_serial: str | None = None
    last_error: str | None = None
    reconnect_count: int = 0


class MessageType(Enum):
    """WebSocket message types from device-shard-api."""

    # Client -> Server
    PUBLISH = "pub"
    SUBSCRIBE = "sub"
    UNSUBSCRIBE = "unsub"

    # Server -> Client
    MESSAGE = "msg"
    SUBSCRIBED = "subd"
    UNSUBSCRIBED = "unsubd"
    ERROR = "err"
