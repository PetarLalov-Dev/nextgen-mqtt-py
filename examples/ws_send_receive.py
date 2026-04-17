#!/usr/bin/env python3
"""WebSocket send-receive CLI tool.

Send a protobuf hex payload to a device via WebSocket and wait for the first response.
Outputs structured JSON to stdout for easy integration with other tools.

Stdout is reserved for JSON output only — all diagnostic logs go to a rotating
log file (ws_send_receive.log), so the output is always safe to pipe into jq,
python -m json.tool, or other JSON consumers.

Usage:
    # Positional args
    python ws_send_receive.py <device_serial> <hex_payload> [--timeout <seconds>]

    # JSON input
    python ws_send_receive.py --json '{"device_serial": "2530295", "hex_payload": "08 01 1a 04", "timeout": 10}'

    # Piped JSON via stdin
    echo '{"device_serial": "2530295", "hex_payload": "08 01"}' | python ws_send_receive.py --json -
"""

import argparse
import asyncio
import json
import logging
import sys
from logging.handlers import RotatingFileHandler

from google.protobuf.json_format import MessageToDict

from nextgen_mqtt import NextGenMQTTClient
from nextgen_mqtt.helix import parse_helix_message
from nextgen_mqtt.models import MQTTMessage

LOG_FILE = "ws_send_receive.log"
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT = 3
DEFAULT_TIMEOUT = 10


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging(verbose: bool = False) -> None:
    """Configure rotating file logging.

    All output goes to a file (never stdout) so the CLI's stdout stream
    stays clean JSON.  Use --verbose to switch from INFO to DEBUG level.
    """
    level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")

    handler = RotatingFileHandler(LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT)
    handler.setLevel(level)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args() -> tuple[str, str, float, bool]:
    """Parse CLI arguments and return (device_serial, hex_payload, timeout, verbose).

    Supports two input modes:
      1. Positional arguments — simple CLI usage.
      2. --json flag — accepts a JSON string (or '-' to read from stdin).
         Required JSON fields: device_serial, hex_payload.
         Optional: timeout (defaults to DEFAULT_TIMEOUT).
    """
    parser = argparse.ArgumentParser(
        description="Send a hex payload to a device via WebSocket and return the first response as JSON."
    )
    parser.add_argument("device_serial", nargs="?", help="Target device serial (e.g. 2530295)")
    parser.add_argument("hex_payload", nargs="?", help="Hex payload string, spaces allowed")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Response timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument("--json", dest="json_input", metavar="JSON", help="JSON input string or '-' for stdin")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    # --- JSON input mode ---
    if args.json_input is not None:
        raw = sys.stdin.read() if args.json_input == "-" else args.json_input
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            print(json.dumps({"status": "error", "message": f"Invalid JSON input: {e}"}))
            sys.exit(1)

        device_serial = data.get("device_serial")
        hex_payload = data.get("hex_payload")
        timeout = float(data.get("timeout", args.timeout))

        if not device_serial or not hex_payload:
            print(
                json.dumps({"status": "error", "message": "JSON input must contain 'device_serial' and 'hex_payload'"})
            )
            sys.exit(1)

        return str(device_serial), str(hex_payload), timeout, args.verbose

    # --- Positional arguments mode ---
    if not args.device_serial or not args.hex_payload:
        parser.error("device_serial and hex_payload are required (or use --json)")

    return args.device_serial, args.hex_payload, args.timeout, args.verbose


# ---------------------------------------------------------------------------
# Drain — discard stale messages that arrived before our request
# ---------------------------------------------------------------------------


async def drain_stale_messages(conn, logger: logging.Logger) -> int:
    """Drain any messages already queued on the connection before we send.

    After the WebSocket handshake the server may push pending data for
    this device (e.g. retained messages or queued responses from a
    previous session).  We consume and log them so they don't get mixed
    up with the actual response to our request.

    Returns the number of drained messages.
    """
    drained = 0
    try:
        # Use a short timeout — we only want what's already sitting in the
        # buffer, not future messages.
        async with asyncio.timeout(0.5):
            async for msg in conn.messages():
                drained += 1

                # Log the raw hex and, if the payload is valid Helix protobuf,
                # also log the decoded JSON for debugging.
                if msg.helix:
                    decoded = MessageToDict(msg.helix.message, preserving_proto_field_name=True)
                    logger.info(
                        "Drained %d bytes: %s Helix: %s",
                        len(msg.payload),
                        msg.payload.hex(),
                        json.dumps(decoded),
                    )
                else:
                    logger.info("Drained %d bytes: %s", len(msg.payload), msg.payload.hex())
    except asyncio.TimeoutError:
        # Expected — means we've consumed everything that was buffered.
        pass

    if drained:
        logger.info("Drained %d stale message(s)", drained)

    return drained


# ---------------------------------------------------------------------------
# Send — encode the hex payload and push it to the device
# ---------------------------------------------------------------------------


async def send_payload(conn, hex_payload: str, logger: logging.Logger) -> None:
    """Normalize the hex string, send raw bytes over the WebSocket.

    The hex string may contain spaces for readability (e.g. "08 01 1a 04").
    Spaces are stripped before conversion to bytes.

    If the payload is valid Helix protobuf, the decoded structure is logged
    so operators can see what was actually sent.
    """
    # Strip whitespace so callers can use "08 01 1a 04" or "08011a04".
    normalized_hex = "".join(hex_payload.split())
    payload = bytes.fromhex(normalized_hex)

    # Attempt to decode the outgoing payload as Helix protobuf for logging.
    # This is best-effort — non-Helix payloads are logged as raw hex only.
    try:
        req_helix = parse_helix_message(payload)
        req_dict = MessageToDict(req_helix.message, preserving_proto_field_name=True)
        logger.info("Sending %d bytes: %s Helix: %s", len(payload), normalized_hex, json.dumps(req_dict))
    except Exception:
        logger.info("Sending %d bytes: %s", len(payload), normalized_hex)

    await conn.send(payload)


# ---------------------------------------------------------------------------
# Receive — wait for the first response and return it
# ---------------------------------------------------------------------------


async def receive_response(
    conn, device_serial: str, timeout: float, logger: logging.Logger
) -> MQTTMessage:
    """Wait for the first message after our send and return it.

    Blocks until a message arrives or the timeout expires.
    On timeout, prints a JSON timeout object to stdout and exits with code 1.
    """
    logger.info("Payload sent, waiting up to %.1fs for response", timeout)

    message_stream = conn.messages()
    try:
        # Await the next message from the async iterator with a timeout guard.
        message = await asyncio.wait_for(message_stream.__anext__(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("No response within %.1fs", timeout)
        print(
            json.dumps(
                {
                    "status": "timeout",
                    "device_serial": device_serial,
                    "timeout_seconds": timeout,
                }
            )
        )
        sys.exit(1)

    # Log the raw response and optional Helix decode.
    resp_hex = message.payload.hex()
    if message.helix:
        resp_dict = MessageToDict(message.helix.message, preserving_proto_field_name=True)
        logger.info("Response %d bytes: %s Helix: %s", len(message.payload), resp_hex, json.dumps(resp_dict))
    else:
        logger.info("Response %d bytes: %s", len(message.payload), resp_hex)

    return message


# ---------------------------------------------------------------------------
# Orchestrator — connect, drain, send, receive, print result
# ---------------------------------------------------------------------------


async def send_and_receive(device_serial: str, hex_payload: str, timeout: float) -> None:
    """Top-level async workflow: connect → drain → send → receive → output.

    1. Open a WebSocket connection to the staging shard for the target device.
    2. Wait briefly for the connection to stabilize, then drain stale messages.
    3. Send the hex payload to the device.
    4. Wait for the first response (up to `timeout` seconds).
    5. Print a JSON result object to stdout.
    """
    logger = logging.getLogger(__name__)

    async with NextGenMQTTClient.staging() as client:
        async with client.connect_websocket(device_serial, use_secondary=False) as conn:
            logger.info("Connected to device %s via WebSocket", device_serial)

            # Brief pause to let the connection fully establish and any
            # initial server-side messages to arrive in the buffer.
            await asyncio.sleep(1)

            # Step 1: Drain stale messages so we only capture our response.
            await drain_stale_messages(conn, logger)

            # Step 2: Send the request payload to the device.
            await send_payload(conn, hex_payload, logger)

            # Step 3: Wait for the device's response.
            message = await receive_response(conn, device_serial, timeout, logger)

            # Step 4: Build and print the JSON result.
            result = build_result(device_serial, message)
            print(json.dumps(result))


# ---------------------------------------------------------------------------
# Result builder — assemble the JSON output dict
# ---------------------------------------------------------------------------


def build_result(device_serial: str, message: MQTTMessage) -> dict:
    """Build the JSON-serializable result dict from a received message.

    Always includes status, device_serial, raw hex response, topic, and
    timestamp.  If the payload decoded as Helix protobuf, the decoded
    structure is included under the "helix" key.
    """
    resp_hex = message.payload.hex()

    result: dict = {
        "status": "ok",
        "device_serial": device_serial,
        "response": resp_hex,
        "topic": message.topic,
        "received_at": message.received_at.isoformat(),
    }

    # Attach the decoded Helix protobuf if available.
    if message.helix:
        result["helix"] = MessageToDict(message.helix.message, preserving_proto_field_name=True)

    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse arguments, set up logging, and run the async workflow.

    Catches KeyboardInterrupt and unexpected exceptions, printing a
    structured JSON error to stdout in both cases (exit code 1).
    """
    device_serial, hex_payload, timeout, verbose = parse_args()
    setup_logging(verbose)
    logger = logging.getLogger(__name__)
    logger.info("Starting send-receive: device=%s timeout=%.1fs", device_serial, timeout)

    try:
        asyncio.run(send_and_receive(device_serial, hex_payload, timeout))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        print(json.dumps({"status": "error", "message": "Interrupted"}))
        sys.exit(1)
    except Exception as e:
        logger.exception("Unexpected error")
        print(json.dumps({"status": "error", "message": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
