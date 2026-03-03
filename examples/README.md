# ws_send_receive.py

CLI tool for sending a protobuf hex payload to a device via WebSocket and receiving the first response as structured JSON.

Stdout is reserved for JSON output only, making it safe to pipe into other tools. All diagnostic logs go to a rotating log file (`ws_send_receive.log`).

## Prerequisites

```bash
uv sync --all-extras
```

## Usage

### Positional arguments

```bash
uv run python examples/ws_send_receive.py <device_serial> <hex_payload> [--timeout <seconds>]
```

```bash
uv run python examples/ws_send_receive.py 2530295 "08 01 1a 04 31 32 33 34 ba 40 04 08 01 10 05"
```

With a custom timeout (default is 10 seconds):

```bash
uv run python examples/ws_send_receive.py 2530295 "08 01 1a 04" --timeout 15
```

### JSON input

Pass a JSON string directly:

```bash
uv run python examples/ws_send_receive.py --json '{"device_serial": "2530295", "hex_payload": "08 01 1a 04", "timeout": 10}'
```

Or pipe JSON via stdin:

```bash
echo '{"device_serial": "2530295", "hex_payload": "08 01 1a 04"}' | uv run python examples/ws_send_receive.py --json -
```

JSON fields:

| Field            | Required | Default | Description                    |
|------------------|----------|---------|--------------------------------|
| `device_serial`  | yes      |         | Target device serial           |
| `hex_payload`    | yes      |         | Hex bytes, spaces allowed      |
| `timeout`        | no       | 10      | Response timeout in seconds    |

### Debug logging

Add `--verbose` to enable DEBUG-level logging in the log file:

```bash
uv run python examples/ws_send_receive.py 2530295 "08 01" --verbose
```

Logs are written to `ws_send_receive.log` (5 MB max, 3 rotated backups).

## Output

All output is a single JSON object printed to stdout.

### Success (exit code 0)

```json
{
  "status": "ok",
  "device_serial": "2530295",
  "response": "0a0b0c",
  "topic": "2530295/ws",
  "received_at": "2026-03-03T12:00:00.123456"
}
```

- `response` is the raw response bytes hex-encoded.

### Timeout (exit code 1)

```json
{
  "status": "timeout",
  "device_serial": "2530295",
  "timeout_seconds": 10
}
```

### Error (exit code 1)

```json
{
  "status": "error",
  "message": "connection refused"
}
```

## Piping into other tools

Because stdout is always valid JSON, you can chain it directly:

```bash
# Pretty-print the response
uv run python examples/ws_send_receive.py 2530295 "08 01" | python -m json.tool

# Extract just the response hex with jq
uv run python examples/ws_send_receive.py 2530295 "08 01" | jq -r '.response'

# Use the exit code in a script
if uv run python examples/ws_send_receive.py 2530295 "08 01" > /tmp/result.json; then
  echo "Got response: $(jq -r .response /tmp/result.json)"
else
  echo "Failed: $(jq -r .message // .status /tmp/result.json)"
fi
```
