"""Authentication module for NextGen MQTT client.

Handles OAuth2 token acquisition and user token creation.
"""

import base64
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from .config import Environment
from .generated.main_pb2 import Helix

logger = logging.getLogger(__name__)


@dataclass
class AccessToken:
    """OAuth2 access token."""

    token: str
    token_type: str
    expires_in: int
    scope: str | None = None


@dataclass
class UserTokenEndpoints:
    """API and WebSocket endpoints from user token response."""

    api: list[str]
    ws: list[str]


@dataclass
class DeviceTokenEndpoints:
    """MQTT and WebSocket endpoints from device login response."""

    mq: list[str]  # MQTT endpoints
    ws: list[str] | None = None  # WebSocket endpoints


@dataclass
class DeviceToken:
    """Device token for direct MQTT connection (7-day TTL)."""

    token: str
    expires_at: datetime
    primary: DeviceTokenEndpoints
    secondary: DeviceTokenEndpoints | None = None


@dataclass
class UserToken:
    """User token for device access."""

    token: str
    expires_at: datetime
    primary: UserTokenEndpoints
    secondary: UserTokenEndpoints | None = None


_REGISTRATION_FIELDS = ("registration_get_resp", "registration_set", "registration_write")


class AuthClient:
    """Authentication client for NextGen API."""

    def __init__(self, env: Environment):
        """Initialize auth client with environment configuration.

        Args:
            env: Environment configuration containing URLs and credentials.
        """
        self.env = env
        self._http_client: httpx.AsyncClient | None = None
        self._access_token: AccessToken | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def get_access_token(self, force_refresh: bool = False) -> AccessToken:
        """Get OAuth2 access token using client credentials.

        Uses HTTP Basic Auth with client_id/client_secret.

        Args:
            force_refresh: If True, fetch a new token even if one is cached.

        Returns:
            AccessToken with the OAuth2 token details.

        Raises:
            httpx.HTTPStatusError: If the token request fails.
        """
        if self._access_token and not force_refresh:
            return self._access_token

        client = await self._get_client()

        # Encode credentials for Basic Auth
        credentials = f"{self.env.client_id}:{self.env.client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()

        response = await client.post(
            f"{self.env.auth_base_url}/oauth/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {encoded}",
            },
            data={"grant_type": "client_credentials"},
        )
        response.raise_for_status()

        data = response.json()
        self._access_token = AccessToken(
            token=data["access_token"],
            token_type=data.get("token_type", "Bearer"),
            expires_in=data.get("expires_in", 3600),
            scope=data.get("scope"),
        )
        return self._access_token

    async def create_user_token(
        self,
        device_serial: str,
        ttl_seconds: int | None = None,
        permissions: dict[str, Any] | None = None,
    ) -> UserToken:
        """Create a user token for device access.

        Args:
            device_serial: The device serial number.
            ttl_seconds: Token TTL in seconds (60-3600, default 900).
            permissions: Optional permissions dict, e.g.:
                {
                    "global": {
                        "partitions": [1, 2, 3, 4],
                        "zones": [1, 2, 3, 4, 5, 6, 7, 8, 9],
                        "haDevices": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                        "userNumber": 500
                    },
                    "partition": {
                        "*": {
                            "armingLevel": {...},
                            "bypassZones": true,
                            ...
                        }
                    }
                }

        Returns:
            UserToken with token and endpoint information.

        Raises:
            httpx.HTTPStatusError: If the request fails.
        """
        # Ensure we have an access token
        access_token = await self.get_access_token()

        client = await self._get_client()

        body: dict[str, Any] = {}
        if ttl_seconds is not None:
            body["ttlSeconds"] = ttl_seconds
        if permissions is not None:
            body["permissions"] = permissions

        response = await client.post(
            f"{self.env.base_url}/v1/device/{device_serial}/user_token",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token.token}",
            },
            json=body,
        )
        response.raise_for_status()

        data = response.json()

        # Parse expiration - can be ISO format string
        exp_str = data["exp"]
        if isinstance(exp_str, str):
            # Handle ISO format with or without Z suffix
            exp_str = exp_str.replace("Z", "+00:00")
            expires_at = datetime.fromisoformat(exp_str)
        else:
            expires_at = datetime.fromtimestamp(exp_str)

        primary = UserTokenEndpoints(
            api=data["p"]["api"],
            ws=data["p"]["ws"],
        )

        secondary = None
        if "s" in data and data["s"]:
            secondary = UserTokenEndpoints(
                api=data["s"]["api"],
                ws=data["s"]["ws"],
            )

        return UserToken(
            token=data["tok"],
            expires_at=expires_at,
            primary=primary,
            secondary=secondary,
        )

    async def device_login(
        self,
        device_serial: str,
        device_password: str,
    ) -> DeviceToken:
        """Login as a device to get a device token for direct MQTT connection.

        This is used for direct MQTT connections (not WebSocket).
        The token is valid for 7 days.

        Args:
            device_serial: The device serial number.
            device_password: The device password.

        Returns:
            DeviceToken with token and MQTT endpoint information.

        Raises:
            httpx.HTTPStatusError: If the login fails.
        """
        client = await self._get_client()

        response = await client.post(
            f"{self.env.base_url}/v1/device/{device_serial}/login",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json={
                "password": device_password,
                "message_id": 1,
            },
        )
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            data = response.json()
            exp_str = data["exp"]
            if isinstance(exp_str, str):
                exp_str = exp_str.replace("Z", "+00:00")
                expires_at = datetime.fromisoformat(exp_str)
            else:
                expires_at = datetime.fromtimestamp(exp_str)
            primary = DeviceTokenEndpoints(
                mq=data["p"]["mq"],
                ws=data["p"].get("ws"),
            )
            secondary = None
            if "s" in data and data["s"]:
                secondary = DeviceTokenEndpoints(
                    mq=data["s"]["mq"],
                    ws=data["s"].get("ws"),
                )
            return DeviceToken(
                token=data["tok"],
                expires_at=expires_at,
                primary=primary,
                secondary=secondary,
            )

        # Protobuf response: parse a Helix message carrying MqttRegistration.
        # v1.0.22 routes this via registration_get_resp; v1.0.21 used registration_write.
        helix = Helix()
        helix.ParseFromString(response.content)
        which = helix.WhichOneof("msg")
        if which not in _REGISTRATION_FIELDS:
            raise ValueError(f"unexpected Helix oneof in device_login response: {which!r}")
        reg = getattr(helix, which)
        logger.debug(
            "device_login response: oneof=%s mqtt_primary=%s mqtt_secondary=%s token=%s... expiration=%s prefix=%s",
            which, reg.mqtt_primary, reg.mqtt_secondary,
            reg.jwt_token[:20] if reg.jwt_token else "(empty)",
            reg.expiration, getattr(reg, "prefix", "N/A"),
        )

        primary = DeviceTokenEndpoints(mq=[reg.mqtt_primary])
        secondary = DeviceTokenEndpoints(mq=[reg.mqtt_secondary]) if reg.mqtt_secondary else None

        return DeviceToken(
            token=reg.jwt_token,
            expires_at=datetime.fromtimestamp(reg.expiration),
            primary=primary,
            secondary=secondary,
        )

    async def __aenter__(self) -> "AuthClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()
