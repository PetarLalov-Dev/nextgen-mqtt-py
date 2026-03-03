# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NextGen MQTT Client — an async Python library for connecting to NextGen MQTT infrastructure via device-shard API. Supports two connection methods: WebSocket (recommended, uses affiliate credentials) and Direct MQTT (internal networks, uses device credentials).

## Development Commands

```bash
# Install with dev dependencies
uv sync --all-extras

# Run examples
uv run python examples/basic_subscribe.py

# Run tests
uv run pytest

# Run a single test
uv run pytest tests/test_file.py::test_name

# Lint / format
uv run ruff check src/
uv run ruff format src/
```

## Architecture

The library is in `src/nextgen_mqtt/` with four core modules:

- **auth.py** — OAuth2 authentication flows. `AuthClient` handles access tokens (client credentials grant), user tokens (for WebSocket), and device tokens (for direct MQTT). All token types are Pydantic models with endpoint information.
- **client.py** — Main client and connection classes. `NextGenMQTTClient` is the entry point; it produces `WebSocketConnection` (protobuf over WS) or `MQTTConnection` (standard MQTTS). Both expose `messages()` as async iterators. Convenience functions `subscribe_websocket()` and `subscribe_mqtt()` provide one-liner usage.
- **config.py** — Environment and shard configuration. `StagingEnvironment` is pre-configured with credentials and two shards (1-A primary, 1-B secondary). `Topics` holds MQTT topic constants and generates device-specific topic names.
- **models.py** — Data models: `MQTTMessage` (received messages), `TopicType` (enum mapping short topic codes like "cf", "s", "r" to semantic names), `ConnectionState`, `MessageType` (WebSocket protocol message types).

### Key Design Patterns

- **Async-first**: all I/O uses async/await; connections are async context managers
- **Two-tier connection model**: affiliate credentials → WebSocket (external); device credentials → direct MQTT (internal)
- **Auth/client separation**: `AuthClient` handles all token management independently from `NextGenMQTTClient`
- **Pydantic throughout**: all data models, tokens, and configs use Pydantic dataclasses

## Code Style

- Ruff for linting and formatting, 120-char line length, target Python 3.11+
- Full type hints (`py.typed` marker present)
- pytest with `asyncio_mode = "auto"` (no need for `@pytest.mark.asyncio`)
