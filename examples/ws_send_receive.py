#!/usr/bin/env python3
"""WebSocket send-receive CLI tool.

Send a protobuf hex payload to a device via WebSocket and wait for the first response.
Outputs structured JSON to stdout for easy integration with other tools.

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

LOG_FILE = "ws_send_receive.log"
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT = 3
DEFAULT_TIMEOUT = 10


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")

    handler = RotatingFileHandler(LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT)
    handler.setLevel(level)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)


def parse_args() -> tuple[str, str, float, bool]:
    """Parse CLI arguments and return (device_serial, hex_payload, timeout, verbose)."""
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

    if not args.device_serial or not args.hex_payload:
        parser.error("device_serial and hex_payload are required (or use --json)")

    return args.device_serial, args.hex_payload, args.timeout, args.verbose


async def send_and_receive(device_serial: str, hex_payload: str, timeout: float) -> None:
    logger = logging.getLogger(__name__)

    async with NextGenMQTTClient.staging() as client:
        async with client.connect_websocket(device_serial, use_secondary=False) as conn:
            logger.info("Connected to device %s via WebSocket", device_serial)

            await asyncio.sleep(1)

            # Drain any messages already queued before we send
            drained = 0
            try:
                async with asyncio.timeout(0.5):
                    async for msg in conn.messages():
                        drained += 1
                        if msg.helix:
                            d = MessageToDict(msg.helix.message, preserving_proto_field_name=True)
                            logger.info("Drained %d bytes: %s Helix: %s", len(msg.payload), msg.payload.hex(), json.dumps(d))
                        else:
                            logger.info("Drained %d bytes: %s", len(msg.payload), msg.payload.hex())
            except asyncio.TimeoutError:
                pass
            if drained:
                logger.info("Drained %d stale message(s)", drained)

            normalized_hex = "".join(hex_payload.split())
            payload = bytes.fromhex(normalized_hex)
            try:
                req_helix = parse_helix_message(payload)
                req_dict = MessageToDict(req_helix.message, preserving_proto_field_name=True)
                logger.info("Sending %d bytes: %s Helix: %s", len(payload), normalized_hex, json.dumps(req_dict))
            except Exception:
                logger.info("Sending %d bytes: %s", len(payload), normalized_hex)

            await conn.send(payload)
            logger.info("Payload sent, waiting up to %.1fs for response", timeout)

            message_stream = conn.messages()
            try:
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

            resp_hex = message.payload.hex()
            if message.helix:
                resp_dict = MessageToDict(message.helix.message, preserving_proto_field_name=True)
                logger.info("Response %d bytes: %s Helix: %s", len(message.payload), resp_hex, json.dumps(resp_dict))
            else:
                logger.info("Response %d bytes: %s", len(message.payload), resp_hex)
            result = {
                "status": "ok",
                "device_serial": device_serial,
                "response": resp_hex,
                "topic": message.topic,
                "received_at": message.received_at.isoformat(),
            }
            if message.helix:
                result["helix"] = resp_dict
            print(json.dumps(result))


def main() -> None:
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
