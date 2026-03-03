"""NextGen MQTT Client Library.

A Python library for connecting to NextGen MQTT infrastructure.

Example:
    ```python
    import asyncio
    from nextgen_mqtt import NextGenMQTTClient

    async def main():
        async with NextGenMQTTClient.staging() as client:
            async with client.connect("2530295") as conn:
                async for message in conn.messages():
                    print(f"Topic: {message.topic}")
                    print(f"Payload: {message.payload_str()}")
                    print(f"Type: {message.topic_type}")

    asyncio.run(main())
    ```
"""

from .auth import AccessToken, AuthClient, DeviceToken, DeviceTokenEndpoints, UserToken, UserTokenEndpoints
from .client import (
    DeviceConnection,
    MQTTConnection,
    NextGenMQTTClient,
    WebSocketConnection,
    subscribe_mqtt,
    subscribe_websocket,
)
from .config import (
    DEVICE_TOPICS,
    DEVICE_TOPICS_EXTENDED,
    Environment,
    ShardConfig,
    StagingEnvironment,
    Topics,
)
from .helix import HelixMeta, parse_helix_message
from .models import ConnectionState, MessageType, MQTTMessage, TopicType

__version__ = "0.1.0"

__all__ = [
    # Main client
    "NextGenMQTTClient",
    "WebSocketConnection",
    "MQTTConnection",
    "DeviceConnection",
    "subscribe_websocket",
    "subscribe_mqtt",
    # Auth
    "AuthClient",
    "AccessToken",
    "UserToken",
    "UserTokenEndpoints",
    "DeviceToken",
    "DeviceTokenEndpoints",
    # Config
    "Environment",
    "ShardConfig",
    "StagingEnvironment",
    "Topics",
    "DEVICE_TOPICS",
    "DEVICE_TOPICS_EXTENDED",
    # Models
    "MQTTMessage",
    "TopicType",
    "ConnectionState",
    "MessageType",
    # Helix
    "HelixMeta",
    "parse_helix_message",
]
