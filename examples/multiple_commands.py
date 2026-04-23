#!/usr/bin/env python3
"""Interactive example: Connect to a device, send multiple protobuf commands, see decoded responses.

Usage:
    python multiple_commands.py 2530296

Then paste hex-encoded protobuf payloads at the prompt:
    > 0801924300
    > 08019a430f0a0d08ea0f10011802200328043005
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime

from google.protobuf import json_format

from nextgen_mqtt import NextGenMQTTClient, parse_helix_message
from nextgen_mqtt.helix import HelixMeta

logging.basicConfig(level=logging.INFO)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive protobuf command sender with decoded responses."
    )
    parser.add_argument(
        "device_serial",
        nargs="?",
        default="2530296",
        help="Device serial to connect to (default: 2530296).",
    )
    return parser.parse_args()


def _format_decoded(helix: HelixMeta) -> str:
    payload_type = helix.payload.DESCRIPTOR.full_name
    payload_dict = json_format.MessageToDict(helix.payload, preserving_proto_field_name=True)
    payload_json = json.dumps(payload_dict, separators=(", ", ": "), sort_keys=True)

    meta = {}
    message = helix.message
    if helix.msg_id:
        meta["msg_id"] = helix.msg_id
    if getattr(message, "user_number", 0):
        meta["user_number"] = message.user_number
    if getattr(message, "age", 0):
        meta["age"] = message.age
    if getattr(message, "error_code", 0):
        meta["error_code"] = message.error_code

    meta_str = f"  meta={json.dumps(meta, separators=(', ', ': '))}" if meta else ""
    return f"{payload_type}{meta_str}  {payload_json}"


def _decode(payload: bytes) -> str:
    try:
        helix = parse_helix_message(payload)
    except Exception as exc:
        return f"decode error: {exc}"
    return _format_decoded(helix)


def _ts() -> str:
    return datetime.now().isoformat()


_HEX_CHARS = set("0123456789abcdefABCDEF")


async def _read_stdin_lines(queue: asyncio.Queue) -> None:
    """Read lines from stdin in a thread and put them on the async queue."""
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            await queue.put(None)
            break
        line = "".join(c for c in line if c in _HEX_CHARS)
        if line:
            await queue.put(line)


async def main(device_serial: str):
    print(f"Connecting to device {device_serial} via WebSocket...")

    async with NextGenMQTTClient.staging() as client:
        async with client.connect_websocket(device_serial, use_secondary=False) as conn:
            print(f"Connected! Type: {conn.connection.connection_type}")
            print(f"Device: {conn.device_serial}")
            print()
            print("Paste hex-encoded protobuf payloads to send.")
            print("Press Ctrl+C to exit.\n")

            input_queue: asyncio.Queue[str | None] = asyncio.Queue()
            stdin_task = asyncio.create_task(_read_stdin_lines(input_queue))

            try:
                print("> ", end="", flush=True)
                while True:
                    # Race between user input and incoming messages
                    recv_task = asyncio.create_task(
                        asyncio.wait_for(conn._ws.recv(), timeout=0.1)
                    )
                    input_task = asyncio.create_task(
                        asyncio.wait_for(input_queue.get(), timeout=0.1)
                    )

                    try:
                        done, pending = await asyncio.wait(
                            [recv_task, input_task],
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                    except asyncio.CancelledError:
                        recv_task.cancel()
                        input_task.cancel()
                        raise

                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except (asyncio.CancelledError, asyncio.TimeoutError):
                            pass

                    for task in done:
                        try:
                            result = task.result()
                        except asyncio.TimeoutError:
                            continue

                        if task is recv_task:
                            if isinstance(result, bytes) and len(result) > 0:
                                print(f"\n[{_ts()}] < {len(result)}B  {result.hex()}  {_decode(result)}")
                                print("> ", end="", flush=True)

                        elif task is input_task:
                            if result is None:
                                print("\nEOF — exiting.")
                                return

                            hex_str = result.strip()
                            if not hex_str:
                                continue

                            try:
                                payload = bytes.fromhex(hex_str)
                            except ValueError:
                                print(f"  Invalid hex: {hex_str}")
                                print("> ", end="", flush=True)
                                continue

                            await conn.send(payload)
                            print(f"[{_ts()}] > {len(payload)}B  {hex_str}  {_decode(payload)}")
                            print("> ", end="", flush=True)

            finally:
                stdin_task.cancel()
                try:
                    await stdin_task
                except asyncio.CancelledError:
                    pass


if __name__ == "__main__":
    try:
        args = parse_args()
        asyncio.run(main(args.device_serial))
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        import os
        os._exit(0)
