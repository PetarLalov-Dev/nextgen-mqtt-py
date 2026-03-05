#!/usr/bin/env python3
"""Subscribe to a device via WebSocket and print messages.

Usage:
    python examples/basic_subscribe.py 2529015
    python examples/basic_subscribe.py 2529015 --payload 0801e2400408011001
    python examples/basic_subscribe.py 2529015 --interactive
    python examples/basic_subscribe.py 2529015 --clear-retained
    python examples/basic_subscribe.py 2529015 --clear-retained --max-num 32
    python examples/basic_subscribe.py 2529015 --filter r,s
"""

import argparse
import asyncio
import logging
import sys

from google.protobuf.json_format import MessageToDict

from nextgen_mqtt import NextGenMQTTClient
from nextgen_mqtt.colors import BOLD, GRAY, RST, WHITE, topic_color

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Retained topic aliases from main.proto @mqtt.unsolicited.alias annotations
# where @mqtt.unsolicited.retained: True
RETAINED_TOPIC_TEMPLATES = [
    # status topics (s/)
    "s/sy", "s/p/{num}", "s/z/{num}", "s/io/{num}", "s/pr/{num}",
    "s/ha/{num}", "s/hu/{num}", "s/if", "s/up",
    # info topics (i/)
    "i/sy", "i/p/{num}", "i/z/{num}", "i/io/{num}", "i/pr/{num}",
    "i/ha/{num}", "i/if",
    # config topics (cf/)
    "cf/sy", "cf/p/{num}", "cf/z/{num}", "cf/io/{num}", "cf/pr/{num}",
    "cf/ha/{num}", "cf/u/{num}", "cf/in/{num}", "cf/if", "cf/m", "cf/to", "cf/cp",
]


def expand_retained_topics(max_num: int) -> list[str]:
    """Expand topic templates into suffixes (without serial prefix)."""
    topics = []
    for template in RETAINED_TOPIC_TEMPLATES:
        if "{num}" in template:
            for n in range(1, max_num + 1):
                topics.append(template.format(num=n))
        else:
            topics.append(template)
    return topics


async def clear_retained(client: NextGenMQTTClient, serial: str, password: str, use_secondary: bool, max_num: int):
    """Clear retained MQTT messages via direct MQTT connection."""
    suffixes = expand_retained_topics(max_num)
    print(f"Clearing {len(suffixes)} retained topics via direct MQTT...")

    try:
        async with client.connect_mqtt(serial, password, use_secondary=use_secondary) as conn:
            cleared = 0
            for suffix in suffixes:
                await conn.publish(suffix, b"", qos=1, retain=True)
                cleared += 1
                if cleared % 20 == 0:
                    print(f"  Cleared {cleared}/{len(suffixes)}...")
            print(f"Done. Cleared {cleared} retained topics.\n")
    except Exception as e:
        print(f"Failed to clear retained topics: {e}")
        print("Note: Direct MQTT (port 8883) may not be accessible from your network.")
        print("The MQTT broker may reject credentials from external networks.\n")

async def interactive_sender(conn):
    """Read hex payloads from stdin and send them."""
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)

    print("Interactive mode: type hex payloads to send (empty line to skip, 'q' to quit)")
    while True:
        sys.stdout.write("> ")
        sys.stdout.flush()
        line = await reader.readline()
        if not line:
            break
        text = line.decode().strip()
        if text.lower() == "q":
            break
        if not text:
            continue
        try:
            payload = bytes.fromhex(text)
            await conn.send(payload)
            print(f"Sent {len(payload)} bytes")
        except ValueError:
            print(f"Invalid hex: {text}")


async def main():
    parser = argparse.ArgumentParser(description="Subscribe to a device via WebSocket")
    parser.add_argument("serial", help="Device serial number")
    parser.add_argument("--payload", help="Hex payload to send on connect")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode: send hex payloads from stdin")
    parser.add_argument("--secondary", "-s", action="store_true", help="Use secondary shard (1-B)")
    parser.add_argument("--clear-retained", action="store_true", help="Clear all retained MQTT messages before subscribing")
    parser.add_argument("--password", "-p", default="123123", help="Device password for --clear-retained (default: 123123)")
    parser.add_argument("--max-num", type=int, default=16, help="Max number for numbered retained topics (default: 16)")
    parser.add_argument("--filter", "-f", help="Comma-separated topic codes to show (e.g. r,s,i,cf,cd,e,c)")
    args = parser.parse_args()
    topic_filter = set(args.filter.split(",")) if args.filter else None

    print(f"Subscribing to device {args.serial} via WebSocket...")

    async with NextGenMQTTClient.staging() as client:
        if args.clear_retained:
            await clear_retained(client, args.serial, args.password, args.secondary, args.max_num)

        async with client.connect_websocket(args.serial, use_secondary=args.secondary) as conn:
            print(f"Connected! Device: {conn.device_serial}")

            if args.payload:
                payload = bytes.fromhex(args.payload)
                print(f"Sending payload: {args.payload} ({len(payload)} bytes)")
                await conn.send(payload)

            if args.interactive:
                sender_task = asyncio.create_task(interactive_sender(conn))
            else:
                sender_task = None

            print("Waiting for messages (Ctrl+C to exit)...\n")

            try:
                async for message in conn.messages():
                    code = message.topic_type.value
                    if topic_filter and code not in topic_filter:
                        continue
                    cc = topic_color(code)
                    ts = message.received_at.strftime('%H:%M:%S.%f')[:-3]
                    print(f"{GRAY}{ts}{RST} {cc}{BOLD}{message.topic}{RST} {GRAY}{len(message.payload)}b{RST}")
                    print(f"  {GRAY}hex:{RST}     {GRAY}{message.payload[:50].hex()}{'...' if len(message.payload) > 50 else ''}{RST}")
                    if message.helix:
                        h = message.helix
                        print(f"  {GRAY}message:{RST} {cc}{BOLD}{h.message_name}{RST} {GRAY}msg_id={h.msg_id} field={h.msg_field}{RST}")
                        try:
                            payload_dict = MessageToDict(h.payload, preserving_proto_field_name=True)
                            if payload_dict:
                                print(f"  {GRAY}payload:{RST} {WHITE}{BOLD}{payload_dict}{RST}")
                        except Exception as e:
                            print(f"  {GRAY}error:{RST}   {topic_color('e')}{e}{RST}")
                    print()
            finally:
                if sender_task:
                    sender_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
