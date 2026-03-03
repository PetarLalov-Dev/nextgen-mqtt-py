# Helix Protobuf Decoding — Design Document

## Overview

WebSocket messages from the NextGen device-shard API arrive as raw protobuf bytes. Prior to this feature, the library assigned a synthetic topic `{serial}/ws` to all of them, discarding real topic and message-type information embedded in the protobuf structure.

This document describes the design for decoding those messages using the Helix protobuf definitions, resolving each message to its correct MQTT topic code and exposing structured metadata to consumers.

## Problem

- All WebSocket frames were treated as opaque bytes with a generic `{serial}/ws` topic.
- Consumers had no way to determine the message type (command, response, status, config, etc.) without manually parsing protobuf.
- Topic-based filtering (e.g. "show me only responses") was impossible on WebSocket connections.

## Solution

Add `helix-protobuf` as a git submodule, generate standard Python `_pb2.py` modules from its `.proto` definitions, and decode every incoming WebSocket frame into a structured `HelixMeta` object with the resolved topic code.

## Architecture

```
lib/helix-protobuf/            # git submodule (pinned to tag)
  protos/
    main.proto                  # Helix message with oneof msg
    security.proto, zone.proto, ...
    buf/validate/validate.proto # vendored dependency

scripts/generate_proto.py       # compilation script

src/nextgen_mqtt/
  generated/                    # output of generate_proto.py
    __init__.py
    main_pb2.py
    security_pb2.py, ...
    buf/validate/validate_pb2.py
    topic_ranges.py             # extracted @mqtt.range annotations
  helix.py                      # HelixMeta + parse_helix_message()
  models.py                     # MQTTMessage.helix field
  client.py                     # WebSocketConnection.messages() integration
```

### Data Flow

```
WebSocket frame (bytes)
  │
  ▼
parse_helix_message(data)
  │  Helix().ParseFromString(data)
  │  WhichOneof("msg") → field_name
  │  Descriptor lookup  → field_number
  │  TOPIC_RANGES       → topic_code
  │
  ▼
HelixMeta(msg_id, msg_field, topic_code, message_name, payload)
  │
  ▼
MQTTMessage(
  topic="{serial}/{topic_code}",   # e.g. "2530294/r"
  payload=raw_bytes,
  helix=HelixMeta(...)
)
```

## Key Components

### `HelixMeta` (dataclass)

| Field          | Type              | Description                                      |
|----------------|-------------------|--------------------------------------------------|
| `msg_id`       | `int`             | Helix message ID (matches request to response)   |
| `msg_field`    | `int`             | Protobuf oneof field number (e.g. 619)           |
| `topic_code`   | `str`             | Resolved MQTT topic code (`e`, `s`, `i`, `cf`, `cd`, `r`, `c`) |
| `message_name` | `str`             | Protobuf field name (e.g. `arm_resp`)            |
| `payload`      | `protobuf.Message`| The decoded sub-message                          |

### Topic Resolution

The `Helix` message in `main.proto` uses a `oneof msg` with field numbers allocated in ranges that map to MQTT topics:

| Range       | Topic Code | Meaning           |
|-------------|------------|--------------------|
| 5           | `e`        | Event              |
| 6–199       | `s` or `i` | Status or Info     |
| 200–399     | `cf`       | Config             |
| 400–599     | `cd`       | Config Desired     |
| 600–999     | `r`        | Command Response   |
| 1000–1399   | `c`        | Command            |

> **Note:** Ranges are extracted from `@mqtt.range.*` annotations in `main.proto`
> at generation time and written to `generated/topic_ranges.py`. This makes them
> automatically correct for any proto version.

For the status/info range, the field name is inspected: fields containing `"status"` map to `s`, fields containing `"info"` map to `i`, and ambiguous fields default to `s`.

### Fallback Behavior

If protobuf decoding fails (malformed data, unknown fields, no oneof set), `WebSocketConnection.messages()` falls back to:
- `topic = "{serial}/ws"` (the original behavior)
- `helix = None`

This ensures the library never drops messages due to decode errors.

## Proto Generation

The generation script (`scripts/generate_proto.py`) handles:

1. **Compilation** — Runs `grpc_tools.protoc` on all `.proto` files including `buf/validate/validate.proto`.
2. **Import fixup** — Rewrites bare `import foo_pb2` to `from . import foo_pb2` for correct intra-package resolution.
3. **Range extraction** — Parses `@mqtt.range.*` annotations from `main.proto` and writes `topic_ranges.py`.

### Regeneration

When the proto definitions change (e.g. updating the submodule to a new tag):

```bash
# Update submodule to new tag
git -C lib/helix-protobuf checkout v1.0.21

# Regenerate
uv run python scripts/generate_proto.py

# Verify
uv run ruff check src/
uv run pytest
```

### `buf/validate/validate.proto` Dependency

All Helix proto files import `buf/validate/validate.proto` for field constraints. This file is managed by the `buf` CLI in the upstream repo and is not checked into the submodule.

It must be placed at `lib/helix-protobuf/protos/buf/validate/validate.proto` before generation. Options:
- Run `buf dep update && buf export` in the submodule (if `buf` CLI is available)
- Download from [bufbuild/protovalidate](https://github.com/bufbuild/protovalidate) (`proto/protovalidate/buf/validate/validate.proto`)

The validation constraints are compile-time only — the generated Python code imports the module but doesn't use it at runtime for deserialization.

## Dependencies

| Package        | Scope   | Purpose                    |
|----------------|---------|----------------------------|
| `protobuf`     | Runtime | Protobuf message parsing   |
| `grpcio-tools` | Dev     | `protoc` compiler for generation |

## Example Output

```json
{
  "status": "ok",
  "device_serial": "2530294",
  "response": "0801da26020801",
  "topic": "2530294/r",
  "message_type": "arm_resp",
  "msg_id": 1,
  "received_at": "2026-03-03T22:49:54.377433"
}
```

## Files Changed

| File | Action |
|------|--------|
| `lib/helix-protobuf` | Git submodule pinned to `v1.0.20` |
| `scripts/generate_proto.py` | Proto compilation + range extraction script |
| `src/nextgen_mqtt/generated/` | Generated `*_pb2.py` + `topic_ranges.py` |
| `src/nextgen_mqtt/helix.py` | `HelixMeta` + `parse_helix_message()` |
| `src/nextgen_mqtt/models.py` | Added `helix` field to `MQTTMessage` |
| `src/nextgen_mqtt/client.py` | Decode in `WebSocketConnection.messages()` |
| `src/nextgen_mqtt/__init__.py` | Export `HelixMeta`, `parse_helix_message` |
| `pyproject.toml` | `protobuf` dep, `grpcio-tools` dev dep, ruff exclude |
| `examples/ws_send_receive.py` | Include `message_type` and `msg_id` in output |
