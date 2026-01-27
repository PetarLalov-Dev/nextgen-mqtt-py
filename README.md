# NextGen MQTT Client

A Python library for connecting to NextGen MQTT infrastructure via device-shard API.

## Features

- Automatic OAuth2 authentication flow
- **WebSocket connection** via device-shard-api (recommended for external access)
- **Direct MQTT connection** via MQTTS (for internal networks)
- Support for multiple shards (1-A, 1-B)
- Async/await API with context managers
- Type hints and dataclasses throughout

## Installation

```bash
# Using UV (recommended)
uv add nextgen-mqtt

# Or install from source
uv pip install -e .
```

## Quick Start (WebSocket - Recommended)

```python
import asyncio
from nextgen_mqtt import NextGenMQTTClient

async def main():
    device_serial = "2530295"

    async with NextGenMQTTClient.staging() as client:
        # WebSocket connection (recommended for external access)
        async with client.connect_websocket(device_serial) as conn:
            print(f"Connected via {conn.connection.connection_type}")

            async for message in conn.messages():
                # Messages are protobuf-encoded bytes
                print(f"Received {len(message.payload)} bytes")

asyncio.run(main())
```

## Connection Methods

### 1. WebSocket (Recommended)

Uses affiliate credentials → user token → WebSocket to device-shard-api.

- **Best for**: External applications, user-facing apps
- **Auth**: Affiliate client_id/secret (pre-configured for staging)
- **Protocol**: WebSocket with protobuf messages

```python
async with client.connect_websocket(device_serial) as conn:
    async for message in conn.messages():
        # message.payload contains protobuf bytes
        print(message.payload.hex())
```

### 2. Direct MQTT (Internal Networks)

Uses device credentials → device token → MQTTS connection.

- **Best for**: Device simulation, internal testing
- **Auth**: Device serial + password
- **Protocol**: Standard MQTT over TLS
- **Note**: Port 8883 may not be accessible from external networks

```python
async with client.connect_mqtt(device_serial, device_password) as conn:
    async for message in conn.messages():
        # Standard MQTT message with topic
        print(f"{message.topic}: {message.payload}")
```

## Authentication Flow

### For WebSocket (Affiliate Credentials)

1. **Get OAuth2 Access Token**: POST `/oauth/token` with client_id/secret
2. **Create User Token**: POST `/v1/device/{serial}/user_token` with access token
3. **Connect WebSocket**: `wss://{shard}/v1/device/{serial}/ws` with Bearer token

### For Direct MQTT (Device Credentials)

1. **Device Login**: POST `/v1/device/{serial}/login` with device password
2. **Connect MQTT**: `ssl://{shard}:8883` with device token

```python
from nextgen_mqtt import AuthClient, StagingEnvironment

async with AuthClient(StagingEnvironment.STAGING) as auth:
    # Method 1: User token (for WebSocket)
    user_token = await auth.create_user_token("2530295", ttl_seconds=3600)

    # Method 2: Device token (for direct MQTT)
    device_token = await auth.device_login("2530295", "device_password")
```

## Configuration

### Staging Environment (Pre-configured)

```python
from nextgen_mqtt import StagingEnvironment

env = StagingEnvironment.STAGING
# Base URL: https://ngps-cr.alulastaging.net
# WebSocket: wss://ngps-ds-1-a.alulastaging.net/v1/device/{serial}/ws
# MQTT: ssl://ngps-ds-1-a.alulastaging.net:8883
```

### Custom Environment

```python
from nextgen_mqtt import Environment, ShardConfig

env = Environment(
    name="custom",
    base_url="https://your-api.example.com",
    auth_base_url="https://your-auth.example.com",
    client_id="your-client-id",
    client_secret="your-client-secret",
    shards=[
        ShardConfig(
            name="1-A",
            https_url="https://your-shard.example.com",
            mqtt_url="your-shard.example.com",
            mqtt_port=8883,
        ),
    ],
)
```

## Topics (Direct MQTT only)

When using direct MQTT, you can subscribe to specific topics:

| Topic Pattern | Description |
|--------------|-------------|
| `{serial}/cf` | Config (full) |
| `{serial}/cf/#` | Config (subtree) |
| `{serial}/s` | Status (full) |
| `{serial}/s/#` | Status (subtree) |
| `{serial}/i` | Info (full) |
| `{serial}/i/#` | Info (subtree) |
| `{serial}/r` | Response |
| `{serial}/e` | Event |

## Using Secondary Shard

```python
# Connect to secondary endpoint (1-B) instead of primary (1-A)
async with client.connect_websocket(device_serial, use_secondary=True) as conn:
    ...
```

## Simple One-liner

```python
from nextgen_mqtt import subscribe_websocket

async for message in subscribe_websocket("2530295"):
    print(f"Received: {message.payload.hex()[:50]}...")
```

## Examples

See the `examples/` directory:

- `basic_subscribe.py` - WebSocket subscription with logging
- `simple_oneliner.py` - Simplest possible usage
- `auth_only.py` - Get tokens without connecting
- `direct_mqtt.py` - Direct MQTT connection (internal networks)

## Development

```bash
# Install with dev dependencies
uv sync --all-extras

# Run examples
uv run python examples/basic_subscribe.py

# Run tests
uv run pytest
```

## Staging Environment Details

| Component | URL |
|-----------|-----|
| Base URL | `https://ngps-cr.alulastaging.net` |
| OAuth Endpoint | `/oauth/token` |
| User Token | `/v1/device/{serial}/user_token` |
| Device Login | `/v1/device/{serial}/login` |
| WebSocket 1-A | `wss://ngps-ds-1-a.alulastaging.net/v1/device/{serial}/ws` |
| WebSocket 1-B | `wss://ngps-ds-1-b.alulastaging.net/v1/device/{serial}/ws` |
| MQTT 1-A | `ssl://ngps-ds-1-a.alulastaging.net:8883` (internal) |
| MQTT 1-B | `ssl://ngps-ds-1-b.alulastaging.net:8883` (internal) |
