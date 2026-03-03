"""Helix protobuf message decoding.

Parses raw protobuf bytes into structured HelixMeta with resolved topic codes
based on the oneof field number ranges defined in main.proto.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from google.protobuf.message import Message

from .generated.main_pb2 import Helix
from .generated.topic_ranges import TOPIC_RANGES

logger = logging.getLogger(__name__)

# For the status/info range ("s/i"), build a lookup from the Helix descriptor.
# Fields with "status" in the name → "s", fields with "info" in the name → "i".
_SI_LOW = next((lo for lo, hi, code in TOPIC_RANGES if code == "s/i"), None)
_SI_HIGH = next((hi for lo, hi, code in TOPIC_RANGES if code == "s/i"), None)
_STATUS_INFO_MAP: dict[str, str] = {}
if _SI_LOW is not None and _SI_HIGH is not None:
    for _field in Helix.DESCRIPTOR.oneofs_by_name["msg"].fields:
        if _SI_LOW <= _field.number <= _SI_HIGH:
            if "status" in _field.name:
                _STATUS_INFO_MAP[_field.name] = "s"
            elif "info" in _field.name:
                _STATUS_INFO_MAP[_field.name] = "i"
            else:
                _STATUS_INFO_MAP[_field.name] = "s"


@dataclass
class HelixMeta:
    """Decoded metadata from a Helix protobuf message."""

    msg_id: int
    msg_field: int
    topic_code: str
    message_name: str
    payload: Message


def _field_to_topic(field_number: int, field_name: str) -> str:
    """Map a oneof field number to a topic code (e, s, i, cf, cd, r, c)."""
    for low, high, code in TOPIC_RANGES:
        if low <= field_number <= high:
            if code == "s/i":
                return _STATUS_INFO_MAP.get(field_name, "s")
            return code
    return "unknown"


def parse_helix_message(data: bytes) -> HelixMeta:
    """Parse raw protobuf bytes into a HelixMeta.

    Args:
        data: Raw protobuf-encoded Helix message bytes.

    Returns:
        HelixMeta with decoded fields and resolved topic code.

    Raises:
        ValueError: If the message cannot be parsed or has no oneof field set.
    """
    helix = Helix()
    helix.ParseFromString(data)

    field_name = helix.WhichOneof("msg")
    if field_name is None:
        raise ValueError("Helix message has no oneof 'msg' field set")

    field_descriptor = Helix.DESCRIPTOR.fields_by_name[field_name]
    field_number = field_descriptor.number
    topic_code = _field_to_topic(field_number, field_name)

    return HelixMeta(
        msg_id=helix.msg_id,
        msg_field=field_number,
        topic_code=topic_code,
        message_name=field_name,
        payload=getattr(helix, field_name),
    )
