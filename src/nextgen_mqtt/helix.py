"""Helix protobuf message decoding.

Parses raw protobuf bytes into structured HelixMeta with resolved topic codes
based on the oneof field number ranges defined in main.proto.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from google.protobuf.message import Message

from .generated.main_pb2 import Helix
from .generated.topic_ranges import FIELD_ALIASES, TOPIC_RANGES

logger = logging.getLogger(__name__)


def _disambiguate(field_name: str, candidates: list[str]) -> str:
    """Pick a topic code from overlapping-range candidates using field-name hints.

    Post-v1.0.22 main.proto declares overlapping field-number ranges:
      7-199: status + info         → distinguish by "status"/"info" in name
      600-999: cmd + config_desired → config_desired fields end in "_set"
      1600-1999: cmd_resp + cdr    → config_desired_resp fields end in "_set_resp"
    Legacy "s/i" combined code (pre-v1.0.22) is handled the same way.
    """
    if not candidates:
        return "unknown"
    if len(candidates) == 1:
        code = candidates[0]
        if code == "s/i":
            return "i" if "info" in field_name else "s"
        return code

    if "i" in candidates and "info" in field_name:
        return "i"
    if "s" in candidates and "status" in field_name:
        return "s"
    if "cdr" in candidates and field_name.endswith("_set_resp"):
        return "cdr"
    if "cd" in candidates and field_name.endswith("_set"):
        return "cd"
    if "r" in candidates and field_name.endswith("_resp"):
        return "r"
    if "c" in candidates:
        return "c"
    return candidates[0]


# Precompute field_name → topic_code map from the Helix descriptor.
_FIELD_CODE_MAP: dict[str, str] = {}
for _field in Helix.DESCRIPTOR.oneofs_by_name["msg"].fields:
    _candidates = [code for lo, hi, code in TOPIC_RANGES if lo <= _field.number <= hi]
    _FIELD_CODE_MAP[_field.name] = _disambiguate(_field.name, _candidates)


@dataclass
class HelixMeta:
    """Decoded metadata from a Helix protobuf message."""

    msg_id: int
    msg_field: int
    topic_code: str
    message_name: str
    payload: Message
    message: Message
    topic_template: str | None = None  # e.g. "{prefix}/s/p/{num}" from @mqtt.alias

    def resolve_topic(self, prefix: str) -> str:
        """Render the MQTT topic alias with {prefix} and (when present) {num}.

        Falls back to f"{prefix}/{topic_code}" when no alias is known.
        """
        if not self.topic_template:
            return f"{prefix}/{self.topic_code}"
        num = getattr(self.payload, "num", 0)
        try:
            return self.topic_template.format(prefix=prefix, num=num)
        except (KeyError, IndexError):
            return f"{prefix}/{self.topic_code}"


def _field_to_topic(field_name: str) -> str:
    """Resolve a oneof field name to its MQTT topic code."""
    return _FIELD_CODE_MAP.get(field_name, "unknown")


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
    topic_code = _field_to_topic(field_name)

    return HelixMeta(
        msg_id=helix.msg_id,
        msg_field=field_descriptor.number,
        topic_code=topic_code,
        message_name=field_name,
        payload=getattr(helix, field_name),
        message=helix,
        topic_template=FIELD_ALIASES.get(field_name),
    )
