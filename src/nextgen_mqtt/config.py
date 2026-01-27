"""Configuration module for NextGen MQTT client."""

from dataclasses import dataclass, field
from typing import ClassVar


@dataclass
class ShardConfig:
    """Configuration for a device shard."""

    name: str
    https_url: str
    mqtt_url: str  # ssl:// or mqtts:// URL for direct MQTT connection
    mqtt_port: int = 8883


@dataclass
class Environment:
    """Environment configuration for connecting to NextGen infrastructure."""

    name: str
    base_url: str
    auth_base_url: str
    client_id: str
    client_secret: str
    shards: list[ShardConfig]

    # Optional defaults
    default_ttl_seconds: int = 3600

    @property
    def primary_shard(self) -> ShardConfig:
        """Get the primary (first) shard."""
        return self.shards[0]


@dataclass
class StagingEnvironment(Environment):
    """Pre-configured staging environment."""

    STAGING: ClassVar["StagingEnvironment"]

    name: str = field(default="staging")
    base_url: str = field(default="https://ngps-cr.alulastaging.net")
    auth_base_url: str = field(default="https://ngps-cr.alulastaging.net")
    client_id: str = field(default="m2m-bll")
    client_secret: str = field(default="gQeLxZQflS7b2qN8")
    shards: list[ShardConfig] = field(default_factory=lambda: [
        ShardConfig(
            name="1-A",
            https_url="https://ngps-ds-1-a.alulastaging.net",
            mqtt_url="ngps-ds-1-a.alulastaging.net",
            mqtt_port=8883,
        ),
        ShardConfig(
            name="1-B",
            https_url="https://ngps-ds-1-b.alulastaging.net",
            mqtt_url="ngps-ds-1-b.alulastaging.net",
            mqtt_port=8883,
        ),
    ])


# Pre-configured staging instance
StagingEnvironment.STAGING = StagingEnvironment()


# Device topic names for subscribing (FROM device perspective)
# Note: Wildcards are limited on some brokers, so we use specific topics
DEVICE_TOPICS = [
    "cf",  # Config
    "s",   # Status
    "i",   # Info
    "r",   # Response
    "e",   # Event
]

# Extended topics with wildcards (may not work on all broker shards)
DEVICE_TOPICS_EXTENDED = [
    "cf",    # Config - full topic
    "cf/#",  # Config - subtree
    "s",     # Status - full topic
    "s/#",   # Status - subtree
    "i",     # Info - full topic
    "i/#",   # Info - subtree
    "r",     # Response
    "e",     # Event
]


# Topic name constants
class Topics:
    """MQTT topic name constants."""

    COMMAND = "c"
    RESPONSE = "r"
    EVENT = "e"
    CONFIG = "cf"
    CONFIG_DESIRED = "cd"
    STATUS = "s"
    INFO = "i"

    @staticmethod
    def device_topics(device_serial: str, topic_names: list[str] | None = None) -> list[str]:
        """Generate full topic names for a device.

        Args:
            device_serial: The device serial number.
            topic_names: List of topic suffixes (defaults to DEVICE_TOPICS).

        Returns:
            List of full topic names like ["2530295/cf", "2530295/s", ...].
        """
        if topic_names is None:
            topic_names = DEVICE_TOPICS
        return [f"{device_serial}/{topic}" for topic in topic_names]
