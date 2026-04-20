"""MQTT client for NextGen infrastructure.

Supports two connection methods:
1. WebSocket via device-shard-api (uses user token from affiliate credentials)
2. Direct MQTTS connection (uses device token from device login)
"""

import logging
import secrets
import ssl
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import aiomqtt
import websockets
from websockets.asyncio.client import ClientConnection

from .auth import AuthClient, DeviceToken, UserToken
from .config import DEVICE_TOPICS, Environment, StagingEnvironment, Topics
from .helix import parse_helix_message
from .models import MQTTMessage

logger = logging.getLogger(__name__)


@dataclass
class DeviceConnection:
    """Represents a connection to a device's MQTT topics."""

    device_serial: str
    subscribed_topics: list[str]
    connection_type: str  # "websocket" or "mqtt"


MessageHandler = Callable[[MQTTMessage], Any]


class NextGenMQTTClient:
    """Client for connecting to NextGen MQTT infrastructure.

    Supports two connection methods:

    1. **WebSocket** (recommended for user applications):
       - Uses affiliate credentials to get a user token
       - Connects via WebSocket to device-shard-api
       - Messages are in protobuf format (raw bytes)

    2. **Direct MQTT** (for device simulation/testing):
       - Uses device credentials to get a device token
       - Connects directly to MQTT broker via TLS
       - Standard MQTT protocol

    Example (WebSocket with user token):
        ```python
        async with NextGenMQTTClient.staging() as client:
            async with client.connect_websocket("2530295") as conn:
                async for message in conn.messages():
                    print(f"Topic: {message.topic}, Payload: {message.payload}")
        ```

    Example (Direct MQTT with device credentials):
        ```python
        async with NextGenMQTTClient.staging() as client:
            async with client.connect_mqtt("2530295", "device_password") as conn:
                async for message in conn.messages():
                    print(f"Topic: {message.topic}, Payload: {message.payload}")
        ```
    """

    def __init__(self, env: Environment):
        """Initialize the client with an environment configuration."""
        self.env = env
        self._auth_client = AuthClient(env)

    @classmethod
    def staging(cls) -> "NextGenMQTTClient":
        """Create a client configured for the staging environment."""
        return cls(StagingEnvironment.STAGING)

    async def close(self) -> None:
        """Close all connections."""
        await self._auth_client.close()

    async def get_user_token(
        self,
        device_serial: str,
        ttl_seconds: int = 3600,
        permissions: dict[str, Any] | None = None,
    ) -> UserToken:
        """Get a user token for WebSocket connection."""
        if permissions is None:
            permissions = {
                "global": {
                    "partitions": [1, 2, 3, 4],
                    "zones": [1, 2, 3, 4, 5, 6, 7, 8, 9],
                    "haDevices": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                    "userNumber": 500,
                },
                "partition": {
                    "*": {
                        "armingLevel": {
                            "disarm": True,
                            "away": True,
                            "stay": True,
                            "night": True,
                            "level6": True,
                            "level7": True,
                            "level8": True,
                        },
                        "bypassZones": True,
                        "confirmAlarms": True,
                        "controlChimeMode": True,
                        "controlOutputs": True,
                        "manageScenes": True,
                        "manageUsers": True,
                        "manageZwaveDevices": True,
                        "master": True,
                        "silenceTroubleBeeps": True,
                        "systemTest": True,
                        "viewHistory": True,
                        "zoneSensorReset": True,
                    }
                },
            }
        return await self._auth_client.create_user_token(
            device_serial=device_serial,
            ttl_seconds=ttl_seconds,
            permissions=permissions,
        )

    async def get_device_token(
        self,
        device_serial: str,
        device_password: str,
    ) -> DeviceToken:
        """Get a device token for direct MQTT connection."""
        return await self._auth_client.device_login(
            device_serial=device_serial,
            device_password=device_password,
        )

    async def cleanup_device(self, device_serial: str, use_secondary: bool = False) -> dict:
        """Clear all retained MQTT messages for a device.

        Calls the device-shard-api cleanup endpoint which subscribes to
        {device}/# and publishes empty payloads with retain=True to clear
        all retained messages.

        Args:
            device_serial: The device serial number.
            use_secondary: If True, use secondary shard endpoint.

        Returns:
            Response dict from the API (e.g. {"device_id": "2530294", "status": "ok"}).
        """
        access_token = await self._auth_client.get_access_token()
        user_token = await self.get_user_token(device_serial)
        endpoints = user_token.secondary if use_secondary and user_token.secondary else user_token.primary
        api_base = endpoints.api[0]

        client = await self._auth_client._get_client()
        response = await client.post(
            f"{api_base}/v1/devices/{device_serial}/cleanup",
            headers={"Authorization": f"Bearer {access_token.token}"},
        )
        response.raise_for_status()
        logger.info(f"Cleaned up retained messages for device {device_serial}")
        return response.json()

    @asynccontextmanager
    async def connect_websocket(
        self,
        device_serial: str,
        ttl_seconds: int = 3600,
        use_secondary: bool = False,
    ) -> AsyncIterator["WebSocketConnection"]:
        """Connect via WebSocket to device-shard-api using user token.

        This is the recommended method for user applications.
        Uses affiliate credentials to authenticate.

        Args:
            device_serial: The device serial number.
            ttl_seconds: Token TTL in seconds.
            use_secondary: If True, connect to secondary endpoint.

        Yields:
            WebSocketConnection for receiving messages.
        """
        logger.info(f"Authenticating for device {device_serial}...")
        user_token = await self.get_user_token(device_serial, ttl_seconds=ttl_seconds)
        logger.info(f"Got user token, expires at {user_token.expires_at}")

        # WebSocket URL from token response is already fully qualified (includes /v1/device/{serial}/ws).
        endpoints = user_token.secondary if use_secondary and user_token.secondary else user_token.primary
        ws_url = endpoints.ws[0]
        logger.info(f"Connecting to WebSocket: {ws_url}")

        # Build topic list for reference
        topics = Topics.device_topics(device_serial)
        logger.info(f"Subscribing to topics: {topics}")

        async with websockets.connect(
            ws_url,
            additional_headers={"Authorization": f"Bearer {user_token.token}"},
        ) as ws:
            logger.info("WebSocket connected!")

            connection = DeviceConnection(
                device_serial=device_serial,
                subscribed_topics=topics,
                connection_type="websocket",
            )

            yield WebSocketConnection(ws, connection)

    @asynccontextmanager
    async def connect_mqtt(
        self,
        device_serial: str,
        device_password: str,
        topic_names: list[str] | None = None,
        use_secondary: bool = False,
    ) -> AsyncIterator["MQTTConnection"]:
        """Connect directly to MQTT broker using device credentials.

        This method is for device simulation or testing.
        Requires device password (not affiliate credentials).

        Args:
            device_serial: The device serial number.
            device_password: The device password.
            topic_names: List of topic suffixes to subscribe to.
            use_secondary: If True, connect to secondary (1-B) instead of primary (1-A).

        Yields:
            MQTTConnection for receiving messages.
        """
        if topic_names is None:
            topic_names = DEVICE_TOPICS

        logger.info(f"Device login for {device_serial}...")
        device_token = await self.get_device_token(device_serial, device_password)
        logger.info(f"Got device token, expires at {device_token.expires_at}")

        # Parse MQTT URL from token response - choose primary (1-A) or secondary (1-B)
        endpoints = device_token.secondary if use_secondary and device_token.secondary else device_token.primary
        mqtt_url = endpoints.mq[0]
        parsed = urlparse(mqtt_url)
        hostname = parsed.hostname
        port = parsed.port or 8883

        logger.info(f"Connecting to MQTT broker {hostname}:{port}...")

        # Use unique client ID to avoid conflicts with existing sessions
        unique_suffix = secrets.token_hex(4)
        client_id = f"py-{device_serial}-{unique_suffix}"
        logger.info(f"Using client ID: {client_id}")

        # Create SSL context for TLS connection
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.verify_mode = ssl.CERT_REQUIRED
        ssl_ctx.check_hostname = True
        ssl_ctx.load_default_certs()

        topics = Topics.device_topics(device_serial, topic_names)

        async with aiomqtt.Client(
            hostname=hostname,
            port=port,
            username=device_serial,
            password=device_token.token,
            tls_context=ssl_ctx,
            identifier=client_id,
            protocol=aiomqtt.ProtocolVersion.V5,
            timeout=30,
        ) as mqtt_client:
            for topic in topics:
                await mqtt_client.subscribe(topic, qos=1)
                logger.info(f"Subscribed to {topic}")

            connection = DeviceConnection(
                device_serial=device_serial,
                subscribed_topics=topics,
                connection_type="mqtt",
            )

            yield MQTTConnection(mqtt_client, connection)

    # Convenience alias
    connect = connect_websocket

    async def __aenter__(self) -> "NextGenMQTTClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()


class WebSocketConnection:
    """A connected WebSocket client ready to receive messages."""

    def __init__(self, ws: ClientConnection, connection: DeviceConnection):
        """Initialize with WebSocket and connection info."""
        self._ws = ws
        self.connection = connection

    @property
    def device_serial(self) -> str:
        """Get the connected device serial."""
        return self.connection.device_serial

    @property
    def topics(self) -> list[str]:
        """Get subscribed topics."""
        return self.connection.subscribed_topics

    async def messages(self) -> AsyncIterator[MQTTMessage]:
        """Iterate over incoming messages.

        Messages are decoded from Helix protobuf format. The topic is resolved
        from the oneof field number (e.g. ``{serial}/r`` for command responses).
        If decoding fails, falls back to ``{serial}/ws`` with ``helix=None``.

        Yields:
            MQTTMessage for each received message.
        """
        serial = self.connection.device_serial
        async for data in self._ws:
            raw = data if isinstance(data, bytes) else data.encode()
            topic = f"{serial}/ws"
            helix = None
            try:
                helix = parse_helix_message(raw)
                topic = helix.resolve_topic(serial)
            except Exception:
                logger.debug("Failed to decode Helix message, using raw fallback", exc_info=True)
            yield MQTTMessage(
                topic=topic,
                payload=raw,
                received_at=datetime.now(),
                qos=1,
                helix=helix,
            )

    async def send(self, payload: bytes) -> None:
        """Send a message (protobuf) to the device."""
        await self._ws.send(payload)
        logger.info(f"Sent {len(payload)} bytes to {self.connection.device_serial}")


class MQTTConnection:
    """A connected MQTT client ready to receive messages."""

    def __init__(self, mqtt_client: aiomqtt.Client, connection: DeviceConnection):
        """Initialize with MQTT client and connection info."""
        self._mqtt = mqtt_client
        self.connection = connection

    @property
    def device_serial(self) -> str:
        """Get the connected device serial."""
        return self.connection.device_serial

    @property
    def topics(self) -> list[str]:
        """Get subscribed topics."""
        return self.connection.subscribed_topics

    async def messages(self) -> AsyncIterator[MQTTMessage]:
        """Iterate over incoming MQTT messages.

        Yields:
            MQTTMessage for each received message.
        """
        async for msg in self._mqtt.messages:
            yield MQTTMessage(
                topic=str(msg.topic),
                payload=msg.payload if isinstance(msg.payload, bytes) else msg.payload.encode(),
                received_at=datetime.now(),
                qos=msg.qos,
            )

    async def publish(
        self,
        topic_suffix: str,
        payload: bytes | str,
        qos: int = 1,
        retain: bool = False,
    ) -> None:
        """Publish a message to a device topic."""
        full_topic = f"{self.connection.device_serial}/{topic_suffix}"
        if isinstance(payload, str):
            payload = payload.encode()
        await self._mqtt.publish(full_topic, payload, qos=qos, retain=retain)
        logger.info(f"Published to {full_topic}")

    async def send_command(self, payload: bytes | str) -> None:
        """Send a command to the device."""
        await self.publish(Topics.COMMAND, payload)

    async def clear_retained(self, topic_suffix: str) -> None:
        """Clear a retained message by publishing an empty payload with retain=True."""
        await self.publish(topic_suffix, b"", retain=True)

    async def clear_all_retained(self, topic_suffixes: list[str] | None = None) -> None:
        """Clear retained messages for all device topics.

        Args:
            topic_suffixes: Topics to clear. Defaults to base topics (cf, s, i, r, e).
                Note: wildcards (cf/#) can't be used to clear — you must specify exact topics.
        """
        if topic_suffixes is None:
            topic_suffixes = ["cf", "s", "i", "r", "e"]
        for suffix in topic_suffixes:
            await self.clear_retained(suffix)


async def subscribe_websocket(
    device_serial: str,
    env: Environment | None = None,
) -> AsyncIterator[MQTTMessage]:
    """Convenience function to subscribe via WebSocket.

    Args:
        device_serial: The device serial number.
        env: Environment configuration (defaults to staging).

    Yields:
        MQTTMessage for each received message.
    """
    if env is None:
        env = StagingEnvironment.STAGING

    async with NextGenMQTTClient(env) as client:
        async with client.connect_websocket(device_serial) as conn:
            async for message in conn.messages():
                yield message


async def subscribe_mqtt(
    device_serial: str,
    device_password: str,
    env: Environment | None = None,
) -> AsyncIterator[MQTTMessage]:
    """Convenience function to subscribe via direct MQTT.

    Args:
        device_serial: The device serial number.
        device_password: The device password.
        env: Environment configuration (defaults to staging).

    Yields:
        MQTTMessage for each received message.
    """
    if env is None:
        env = StagingEnvironment.STAGING

    async with NextGenMQTTClient(env) as client:
        async with client.connect_mqtt(device_serial, device_password) as conn:
            async for message in conn.messages():
                yield message
